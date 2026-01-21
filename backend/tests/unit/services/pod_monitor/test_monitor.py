import asyncio
import logging
import types
from typing import Any

import pytest
from app.core.metrics import EventMetrics, KubernetesMetrics
from app.db.repositories.event_repository import EventRepository
from app.domain.events.typed import (
    DomainEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionStartedEvent,
    ResourceUsageAvro,
)
from app.events.core import UnifiedProducer
from app.services.kafka_event_service import KafkaEventService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.services.pod_monitor.monitor import (
    PodEvent,
    PodMonitor,
    WatchEventType,
)
from app.settings import Settings
from dishka import AsyncContainer
from kubernetes.client.rest import ApiException

from tests.helpers.fakes.kafka import FakeAIOKafkaProducer
from tests.helpers.k8s_fakes import (
    FakeApi,
    FakeV1Api,
    FakeWatch,
    FakeWatchStream,
    make_k8s_clients,
    make_pod,
    make_watch,
)

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.pod_monitor")


# ===== Tests using default pod_monitor fixture =====


@pytest.mark.asyncio
async def test_process_raw_event_invalid_and_backoff(pod_monitor: PodMonitor) -> None:
    await pod_monitor._process_raw_event({})

    pod_monitor.config.watch_reconnect_delay = 0
    pod_monitor._reconnect_attempts = 0
    await pod_monitor._backoff()
    await pod_monitor._backoff()
    assert pod_monitor._reconnect_attempts >= 2


@pytest.mark.asyncio
async def test_backoff_max_attempts(pod_monitor: PodMonitor) -> None:
    pod_monitor.config.max_reconnect_attempts = 2
    pod_monitor._reconnect_attempts = 2

    with pytest.raises(RuntimeError, match="Max reconnect attempts exceeded"):
        await pod_monitor._backoff()


@pytest.mark.asyncio
async def test_watch_loop_with_cancellation(pod_monitor: PodMonitor) -> None:
    pod_monitor.config.enable_state_reconciliation = False
    watch_count: list[int] = []

    async def mock_run_watch() -> None:
        watch_count.append(1)
        if len(watch_count) >= 3:
            raise asyncio.CancelledError()

    pod_monitor._run_watch = mock_run_watch  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await pod_monitor._watch_loop()

    assert len(watch_count) == 3


@pytest.mark.asyncio
async def test_watch_loop_api_exception_410(pod_monitor: PodMonitor) -> None:
    pod_monitor.config.enable_state_reconciliation = False
    pod_monitor._last_resource_version = "v123"
    call_count = 0

    async def mock_run_watch() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ApiException(status=410)
        raise asyncio.CancelledError()

    async def mock_backoff() -> None:
        pass

    pod_monitor._run_watch = mock_run_watch  # type: ignore[method-assign]
    pod_monitor._backoff = mock_backoff  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await pod_monitor._watch_loop()

    assert pod_monitor._last_resource_version is None


@pytest.mark.asyncio
async def test_watch_loop_generic_exception(pod_monitor: PodMonitor) -> None:
    pod_monitor.config.enable_state_reconciliation = False
    call_count = 0
    backoff_count = 0

    async def mock_run_watch() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Unexpected error")
        raise asyncio.CancelledError()

    async def mock_backoff() -> None:
        nonlocal backoff_count
        backoff_count += 1

    pod_monitor._run_watch = mock_run_watch  # type: ignore[method-assign]
    pod_monitor._backoff = mock_backoff  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await pod_monitor._watch_loop()

    assert backoff_count == 1


@pytest.mark.asyncio
async def test_cleanup_on_cancel(pod_monitor: PodMonitor) -> None:
    """Test cleanup of tracked pods on cancellation."""
    watch_started = asyncio.Event()

    async def _blocking_watch() -> None:
        pod_monitor._tracked_pods = {"pod1"}
        watch_started.set()
        await asyncio.sleep(10)

    pod_monitor._watch_loop = _blocking_watch  # type: ignore[method-assign]

    task = asyncio.create_task(pod_monitor.run())
    await asyncio.wait_for(watch_started.wait(), timeout=1.0)
    assert "pod1" in pod_monitor._tracked_pods

    task.cancel()
    await task

    assert len(pod_monitor._tracked_pods) == 0


@pytest.mark.asyncio
async def test_process_raw_event_with_metadata(pod_monitor: PodMonitor) -> None:
    processed: list[PodEvent] = []

    async def mock_process(event: PodEvent) -> None:
        processed.append(event)

    pod_monitor._process_pod_event = mock_process  # type: ignore[method-assign]

    raw_event = {
        "type": "ADDED",
        "object": types.SimpleNamespace(metadata=types.SimpleNamespace(resource_version="v1")),
    }

    await pod_monitor._process_raw_event(raw_event)
    assert len(processed) == 1
    assert processed[0].resource_version == "v1"

    raw_event_no_meta = {"type": "MODIFIED", "object": types.SimpleNamespace(metadata=None)}

    await pod_monitor._process_raw_event(raw_event_no_meta)
    assert len(processed) == 2
    assert processed[1].resource_version is None


@pytest.mark.asyncio
async def test_watch_loop_api_exception_other_status(pod_monitor: PodMonitor) -> None:
    pod_monitor.config.enable_state_reconciliation = False
    call_count = 0
    backoff_count = 0

    async def mock_run_watch() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ApiException(status=500)
        raise asyncio.CancelledError()

    async def mock_backoff() -> None:
        nonlocal backoff_count
        backoff_count += 1

    pod_monitor._run_watch = mock_run_watch  # type: ignore[method-assign]
    pod_monitor._backoff = mock_backoff  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await pod_monitor._watch_loop()

    assert backoff_count == 1


@pytest.mark.asyncio
async def test_watch_loop_with_reconciliation(pod_monitor: PodMonitor) -> None:
    """Test that reconciliation is called before each watch restart."""
    pod_monitor.config.enable_state_reconciliation = True

    reconcile_count = 0
    watch_count = 0

    async def mock_reconcile() -> None:
        nonlocal reconcile_count
        reconcile_count += 1

    async def mock_run_watch() -> None:
        nonlocal watch_count
        watch_count += 1
        if watch_count >= 2:
            raise asyncio.CancelledError()

    pod_monitor._reconcile = mock_reconcile  # type: ignore[method-assign]
    pod_monitor._run_watch = mock_run_watch  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await pod_monitor._watch_loop()

    assert reconcile_count == 2
    assert watch_count == 2


@pytest.mark.asyncio
async def test_publish_event_full_flow(
    pod_monitor: PodMonitor,
    fake_kafka_producer: FakeAIOKafkaProducer,
) -> None:
    initial_count = len(fake_kafka_producer.sent_messages)

    event = ExecutionCompletedEvent(
        execution_id="exec1",
        aggregate_id="exec1",
        exit_code=0,
        resource_usage=ResourceUsageAvro(),
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )

    pod = make_pod(name="test-pod", phase="Succeeded", labels={"execution-id": "exec1"})
    await pod_monitor._publish_event(event, pod)

    assert len(fake_kafka_producer.sent_messages) > initial_count


# ===== Tests requiring custom setup =====


class SpyMapper:
    """Spy event mapper that tracks clear_cache calls."""

    def __init__(self) -> None:
        self.cleared = False

    def clear_cache(self) -> None:
        self.cleared = True

    def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:  # noqa: ARG002
        return []


@pytest.mark.asyncio
async def test_run_and_cancel_lifecycle(
    kafka_event_service: KafkaEventService,
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
    k8s_v1: FakeV1Api,
    k8s_watch: FakeWatch,
) -> None:
    """Test that run() blocks until cancelled and cleans up on cancellation."""
    pod_monitor_config.enable_state_reconciliation = False

    spy = SpyMapper()
    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_event_service,
        logger=_test_logger,
        k8s_v1=k8s_v1,
        k8s_watch=k8s_watch,
        event_mapper=spy,  # type: ignore[arg-type]
        kubernetes_metrics=kubernetes_metrics,
    )

    watch_started = asyncio.Event()

    async def _blocking_watch() -> None:
        watch_started.set()
        await asyncio.sleep(10)

    pm._watch_loop = _blocking_watch  # type: ignore[method-assign]

    task = asyncio.create_task(pm.run())
    await asyncio.wait_for(watch_started.wait(), timeout=1.0)

    task.cancel()
    await task

    assert spy.cleared is True


@pytest.mark.asyncio
async def test_run_watch_flow_and_publish(
    kafka_event_service: KafkaEventService,
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.enable_state_reconciliation = False

    pod = make_pod(name="p", phase="Succeeded", labels={"execution-id": "e1"}, term_exit=0, resource_version="rv1")
    v1, watch = make_k8s_clients(events=[{"type": "MODIFIED", "object": pod}], resource_version="rv2")

    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_event_service,
        logger=_test_logger,
        k8s_v1=v1,
        k8s_watch=watch,
        event_mapper=PodEventMapper(logger=_test_logger, k8s_api=FakeApi("{}")),
        kubernetes_metrics=kubernetes_metrics,
    )

    await pm._run_watch()
    assert pm._last_resource_version == "rv2"


@pytest.mark.asyncio
async def test_reconcile_success(
    kafka_event_service: KafkaEventService,
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.namespace = "test"
    pod_monitor_config.label_selector = "app=test"

    pod1 = make_pod(name="pod1", phase="Running", resource_version="v1")
    pod2 = make_pod(name="pod2", phase="Running", resource_version="v1")
    v1, watch = make_k8s_clients(pods=[pod1, pod2])

    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_event_service,
        logger=_test_logger,
        k8s_v1=v1,
        k8s_watch=watch,
        event_mapper=PodEventMapper(logger=_test_logger, k8s_api=FakeApi("{}")),
        kubernetes_metrics=kubernetes_metrics,
    )
    pm._tracked_pods = {"pod2", "pod3"}

    processed: list[str] = []

    async def mock_process(event: PodEvent) -> None:
        processed.append(event.pod.metadata.name)

    pm._process_pod_event = mock_process  # type: ignore[method-assign]

    await pm._reconcile()

    assert "pod1" in processed
    assert "pod3" not in pm._tracked_pods


@pytest.mark.asyncio
async def test_reconcile_exception(
    kafka_event_service: KafkaEventService,
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    class FailV1(FakeV1Api):
        def list_namespaced_pod(self, namespace: str, label_selector: str) -> Any:
            raise RuntimeError("API error")

    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_event_service,
        logger=_test_logger,
        k8s_v1=FailV1(),
        k8s_watch=make_watch([]),
        event_mapper=PodEventMapper(logger=_test_logger, k8s_api=FakeApi("{}")),
        kubernetes_metrics=kubernetes_metrics,
    )

    # Should not raise - errors are caught and logged
    await pm._reconcile()


@pytest.mark.asyncio
async def test_process_pod_event_full_flow(
    kafka_event_service: KafkaEventService,
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
    k8s_v1: FakeV1Api,
    k8s_watch: FakeWatch,
) -> None:
    pod_monitor_config.ignored_pod_phases = ["Unknown"]

    class MockMapper:
        def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:  # noqa: ARG002
            class Event:
                event_type = types.SimpleNamespace(value="test_event")
                metadata = types.SimpleNamespace(correlation_id=None)
                aggregate_id = "agg1"

            return [Event()]

        def clear_cache(self) -> None:
            pass

    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_event_service,
        logger=_test_logger,
        k8s_v1=k8s_v1,
        k8s_watch=k8s_watch,
        event_mapper=MockMapper(),  # type: ignore[arg-type]
        kubernetes_metrics=kubernetes_metrics,
    )

    published: list[Any] = []

    async def mock_publish(event: Any, pod: Any) -> None:  # noqa: ARG001
        published.append(event)

    pm._publish_event = mock_publish  # type: ignore[method-assign]

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="test-pod", phase="Running"),
        resource_version="v1",
    )

    await pm._process_pod_event(event)
    assert "test-pod" in pm._tracked_pods
    assert pm._last_resource_version == "v1"
    assert len(published) == 1

    event_del = PodEvent(
        event_type=WatchEventType.DELETED,
        pod=make_pod(name="test-pod", phase="Succeeded"),
        resource_version="v2",
    )

    await pm._process_pod_event(event_del)
    assert "test-pod" not in pm._tracked_pods
    assert pm._last_resource_version == "v2"

    event_ignored = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="ignored-pod", phase="Unknown"),
        resource_version="v3",
    )

    published.clear()
    await pm._process_pod_event(event_ignored)
    assert len(published) == 0


@pytest.mark.asyncio
async def test_process_pod_event_exception_handling(
    kafka_event_service: KafkaEventService,
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
    k8s_v1: FakeV1Api,
    k8s_watch: FakeWatch,
) -> None:
    class FailMapper:
        def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:
            raise RuntimeError("Mapping failed")

        def clear_cache(self) -> None:
            pass

    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_event_service,
        logger=_test_logger,
        k8s_v1=k8s_v1,
        k8s_watch=k8s_watch,
        event_mapper=FailMapper(),  # type: ignore[arg-type]
        kubernetes_metrics=kubernetes_metrics,
    )

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="fail-pod", phase="Pending"),
        resource_version=None,
    )

    # Should not raise
    await pm._process_pod_event(event)


@pytest.mark.asyncio
async def test_publish_event_exception_handling(
    unit_container: AsyncContainer,
    event_metrics: EventMetrics,
    kubernetes_metrics: KubernetesMetrics,
    test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
    k8s_v1: FakeV1Api,
    k8s_watch: FakeWatch,
) -> None:
    event_repo = await unit_container.get(EventRepository)

    class FailingProducer(UnifiedProducer):
        def __init__(self) -> None:
            self.logger = _test_logger

        async def produce(
                self, event_to_produce: DomainEvent, key: str | None = None, headers: dict[str, str] | None = None
        ) -> None:
            raise RuntimeError("Publish failed")

    failing_service = KafkaEventService(
        event_repository=event_repo,
        kafka_producer=FailingProducer(),
        settings=test_settings,
        logger=_test_logger,
        event_metrics=event_metrics,
    )

    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=failing_service,
        logger=_test_logger,
        k8s_v1=k8s_v1,
        k8s_watch=k8s_watch,
        event_mapper=PodEventMapper(logger=_test_logger, k8s_api=FakeApi("{}")),
        kubernetes_metrics=kubernetes_metrics,
    )

    event = ExecutionStartedEvent(
        execution_id="exec1",
        pod_name="test-pod",
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )

    pod = make_pod(name="no-meta-pod", phase="Pending")
    pod.metadata = None  # type: ignore[assignment]

    # Should not raise
    await pm._publish_event(event, pod)


@pytest.mark.asyncio
async def test_pod_monitor_run_lifecycle(
    kafka_event_service: KafkaEventService,
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    """Test PodMonitor lifecycle via run() method."""
    pod_monitor_config.enable_state_reconciliation = False

    mock_v1 = FakeV1Api()
    mock_watch = make_watch([])
    event_mapper = PodEventMapper(logger=_test_logger, k8s_api=mock_v1)

    monitor = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_event_service,
        logger=_test_logger,
        k8s_v1=mock_v1,
        k8s_watch=mock_watch,
        event_mapper=event_mapper,
        kubernetes_metrics=kubernetes_metrics,
    )

    assert monitor._v1 is mock_v1

    watch_started = asyncio.Event()

    async def _blocking_watch() -> None:
        watch_started.set()
        await asyncio.sleep(10)

    monitor._watch_loop = _blocking_watch  # type: ignore[method-assign]

    task = asyncio.create_task(monitor.run())
    await asyncio.wait_for(watch_started.wait(), timeout=1.0)
    task.cancel()
    await task


def test_update_resource_version(
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
    k8s_v1: FakeV1Api,
    k8s_watch: FakeWatch,
) -> None:
    # Sync test needs minimal mock
    class MockKafkaService:
        pass

    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=MockKafkaService(),  # type: ignore[arg-type]
        logger=_test_logger,
        k8s_v1=k8s_v1,
        k8s_watch=k8s_watch,
        event_mapper=PodEventMapper(logger=_test_logger, k8s_api=FakeApi("{}")),
        kubernetes_metrics=kubernetes_metrics,
    )

    class Stream:
        _stop_event = types.SimpleNamespace(resource_version="v123")

    pm._update_resource_version(Stream())
    assert pm._last_resource_version == "v123"

    class BadStream:
        pass

    pm._update_resource_version(BadStream())


@pytest.mark.asyncio
async def test_run_watch_with_field_selector(
    kafka_event_service: KafkaEventService,
    kubernetes_metrics: KubernetesMetrics,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.field_selector = "status.phase=Running"
    pod_monitor_config.enable_state_reconciliation = False

    watch_kwargs: list[dict[str, Any]] = []

    class TrackingV1(FakeV1Api):
        def list_namespaced_pod(self, namespace: str, label_selector: str) -> Any:
            watch_kwargs.append({"namespace": namespace, "label_selector": label_selector})
            return None

    class TrackingWatch(FakeWatch):
        def stream(self, func: Any, **kwargs: Any) -> FakeWatchStream:
            watch_kwargs.append(kwargs)
            return FakeWatchStream([], "rv1")

    pm = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=kafka_event_service,
        logger=_test_logger,
        k8s_v1=TrackingV1(),
        k8s_watch=TrackingWatch([], "rv1"),
        event_mapper=PodEventMapper(logger=_test_logger, k8s_api=FakeApi("{}")),
        kubernetes_metrics=kubernetes_metrics,
    )

    await pm._run_watch()

    assert any("field_selector" in kw for kw in watch_kwargs)
