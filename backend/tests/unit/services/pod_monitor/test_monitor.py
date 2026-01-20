import asyncio
import logging
import types
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.core.k8s_clients import K8sClients
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
from kubernetes.client.rest import ApiException

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


# ===== Test doubles for KafkaEventService dependencies =====


class FakeEventRepository(EventRepository):
    """In-memory event repository for testing."""

    def __init__(self) -> None:
        super().__init__(_test_logger)
        self.stored_events: list[DomainEvent] = []

    async def store_event(self, event: DomainEvent) -> str:
        self.stored_events.append(event)
        return event.event_id


class FakeUnifiedProducer(UnifiedProducer):
    """Fake producer that captures events without Kafka."""

    def __init__(self) -> None:
        # Don't call super().__init__ - we don't need real Kafka
        self.produced_events: list[tuple[DomainEvent, str | None]] = []
        self.logger = _test_logger

    async def produce(
            self, event_to_produce: DomainEvent, key: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        self.produced_events.append((event_to_produce, key))

    async def aclose(self) -> None:
        pass


def create_test_kafka_event_service(
    event_metrics: EventMetrics, settings: Settings
) -> tuple[KafkaEventService, FakeUnifiedProducer]:
    """Create real KafkaEventService with fake dependencies for testing."""
    fake_producer = FakeUnifiedProducer()
    fake_repo = FakeEventRepository()

    service = KafkaEventService(
        event_repository=fake_repo,
        kafka_producer=fake_producer,
        settings=settings,
        logger=_test_logger,
        event_metrics=event_metrics,
    )
    return service, fake_producer


# ===== Helpers to create test instances with pure DI =====


class SpyMapper:
    """Spy event mapper that tracks clear_cache calls."""

    def __init__(self) -> None:
        self.cleared = False

    def clear_cache(self) -> None:
        self.cleared = True

    def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:  # noqa: ARG002
        return []


def make_k8s_clients_di(
        events: list[dict[str, Any]] | None = None,
        resource_version: str = "rv1",
        pods: list[Any] | None = None,
) -> K8sClients:
    """Create K8sClients for DI with fakes."""
    v1, watch = make_k8s_clients(events=events, resource_version=resource_version, pods=pods)
    return K8sClients(
        api_client=MagicMock(),
        v1=v1,
        apps_v1=MagicMock(),
        networking_v1=MagicMock(),
        watch=watch,
    )


def make_pod_monitor(
        event_metrics: EventMetrics,
        kubernetes_metrics: KubernetesMetrics,
        settings: Settings,
        config: PodMonitorConfig | None = None,
        kafka_service: KafkaEventService | None = None,
        k8s_clients: K8sClients | None = None,
        event_mapper: PodEventMapper | None = None,
) -> PodMonitor:
    """Create PodMonitor with sensible test defaults."""
    cfg = config or PodMonitorConfig()
    clients = k8s_clients or make_k8s_clients_di()
    mapper = event_mapper or PodEventMapper(logger=_test_logger, k8s_api=FakeApi("{}"))
    service = kafka_service or create_test_kafka_event_service(event_metrics, settings)[0]
    return PodMonitor(
        config=cfg,
        kafka_event_service=service,
        logger=_test_logger,
        k8s_clients=clients,
        event_mapper=mapper,
        kubernetes_metrics=kubernetes_metrics,
    )


# ===== Tests =====


@pytest.mark.asyncio
async def test_run_and_cancel_lifecycle(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    """Test that run() blocks until cancelled and cleans up on cancellation."""
    pod_monitor_config.enable_state_reconciliation = False

    spy = SpyMapper()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config, event_mapper=spy)  # type: ignore[arg-type]

    # Track when watch_loop is entered
    watch_started = asyncio.Event()

    async def _blocking_watch() -> None:
        watch_started.set()
        await asyncio.sleep(10)

    pm._watch_loop = _blocking_watch  # type: ignore[method-assign]

    # Start run() as a task
    task = asyncio.create_task(pm.run())

    # Wait until we're actually in the watch loop
    await asyncio.wait_for(watch_started.wait(), timeout=1.0)

    # Cancel it - run() catches CancelledError and exits gracefully
    task.cancel()
    await task  # Should complete without raising (graceful shutdown)

    # Verify cleanup happened
    assert spy.cleared is True


@pytest.mark.asyncio
async def test_run_watch_flow_and_publish(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.enable_state_reconciliation = False

    pod = make_pod(name="p", phase="Succeeded", labels={"execution-id": "e1"}, term_exit=0, resource_version="rv1")
    k8s_clients = make_k8s_clients_di(events=[{"type": "MODIFIED", "object": pod}], resource_version="rv2")

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config, k8s_clients=k8s_clients
    )

    await pm._run_watch()
    assert pm._last_resource_version == "rv2"


@pytest.mark.asyncio
async def test_process_raw_event_invalid_and_backoff(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

    await pm._process_raw_event({})

    pm.config.watch_reconnect_delay = 0
    pm._reconnect_attempts = 0
    await pm._backoff()
    await pm._backoff()
    assert pm._reconnect_attempts >= 2


@pytest.mark.asyncio
async def test_get_status(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.namespace = "test-ns"
    pod_monitor_config.label_selector = "app=test"
    pod_monitor_config.enable_state_reconciliation = True

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)
    pm._tracked_pods = {"pod1", "pod2"}
    pm._reconnect_attempts = 3
    pm._last_resource_version = "v123"

    status = await pm.get_status()
    assert status["tracked_pods"] == 2
    assert status["reconnect_attempts"] == 3
    assert status["last_resource_version"] == "v123"
    assert status["config"]["namespace"] == "test-ns"
    assert status["config"]["label_selector"] == "app=test"
    assert status["config"]["enable_reconciliation"] is True


@pytest.mark.asyncio
async def test_reconcile_success(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.namespace = "test"
    pod_monitor_config.label_selector = "app=test"

    pod1 = make_pod(name="pod1", phase="Running", resource_version="v1")
    pod2 = make_pod(name="pod2", phase="Running", resource_version="v1")
    k8s_clients = make_k8s_clients_di(pods=[pod1, pod2])

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config, k8s_clients=k8s_clients
    )
    pm._tracked_pods = {"pod2", "pod3"}

    processed: list[str] = []

    async def mock_process(event: PodEvent) -> None:
        processed.append(event.pod.metadata.name)

    pm._process_pod_event = mock_process  # type: ignore[method-assign]

    await pm._reconcile()

    # pod1 was missing and should have been processed
    assert "pod1" in processed
    # pod3 was extra and should have been removed from tracking
    assert "pod3" not in pm._tracked_pods


@pytest.mark.asyncio
async def test_reconcile_exception(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    class FailV1(FakeV1Api):
        def list_namespaced_pod(self, namespace: str, label_selector: str) -> Any:
            raise RuntimeError("API error")

    fail_v1 = FailV1()
    k8s_clients = K8sClients(
        api_client=MagicMock(),
        v1=fail_v1,
        apps_v1=MagicMock(),
        networking_v1=MagicMock(),
        watch=make_watch([]),
    )

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config, k8s_clients=k8s_clients
    )

    # Should not raise - errors are caught and logged
    await pm._reconcile()


@pytest.mark.asyncio
async def test_process_pod_event_full_flow(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
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

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, test_settings,
        config=pod_monitor_config,
        event_mapper=MockMapper(),  # type: ignore[arg-type]
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
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    class FailMapper:
        def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:
            raise RuntimeError("Mapping failed")

        def clear_cache(self) -> None:
            pass

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, test_settings,
        config=pod_monitor_config,
        event_mapper=FailMapper(),  # type: ignore[arg-type]
    )

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="fail-pod", phase="Pending"),
        resource_version=None,
    )

    # Should not raise - errors are caught and logged
    await pm._process_pod_event(event)


@pytest.mark.asyncio
async def test_publish_event_full_flow(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    service, fake_producer = create_test_kafka_event_service(event_metrics, test_settings)
    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config, kafka_service=service
    )

    event = ExecutionCompletedEvent(
        execution_id="exec1",
        aggregate_id="exec1",
        exit_code=0,
        resource_usage=ResourceUsageAvro(),
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )

    pod = make_pod(name="test-pod", phase="Succeeded", labels={"execution-id": "exec1"})
    await pm._publish_event(event, pod)

    assert len(fake_producer.produced_events) == 1
    assert fake_producer.produced_events[0][1] == "exec1"


@pytest.mark.asyncio
async def test_publish_event_exception_handling(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    class FailingProducer(FakeUnifiedProducer):
        async def produce(
                self, event_to_produce: DomainEvent, key: str | None = None, headers: dict[str, str] | None = None
        ) -> None:
            raise RuntimeError("Publish failed")

    # Create service with failing producer
    failing_producer = FailingProducer()
    fake_repo = FakeEventRepository()
    failing_service = KafkaEventService(
        event_repository=fake_repo,
        kafka_producer=failing_producer,
        settings=test_settings,
        logger=_test_logger,
        event_metrics=event_metrics,
    )

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config, kafka_service=failing_service
    )

    event = ExecutionStartedEvent(
        execution_id="exec1",
        pod_name="test-pod",
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )

    # Use pod with no metadata to exercise edge case
    pod = make_pod(name="no-meta-pod", phase="Pending")
    pod.metadata = None  # type: ignore[assignment]

    # Should not raise - errors are caught and logged
    await pm._publish_event(event, pod)


@pytest.mark.asyncio
async def test_backoff_max_attempts(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.max_reconnect_attempts = 2

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)
    pm._reconnect_attempts = 2

    with pytest.raises(RuntimeError, match="Max reconnect attempts exceeded"):
        await pm._backoff()


@pytest.mark.asyncio
async def test_watch_loop_with_cancellation(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.enable_state_reconciliation = False
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

    watch_count: list[int] = []

    async def mock_run_watch() -> None:
        watch_count.append(1)
        if len(watch_count) >= 3:
            raise asyncio.CancelledError()

    pm._run_watch = mock_run_watch  # type: ignore[method-assign]

    # watch_loop propagates CancelledError (correct behavior for structured concurrency)
    with pytest.raises(asyncio.CancelledError):
        await pm._watch_loop()

    assert len(watch_count) == 3


@pytest.mark.asyncio
async def test_watch_loop_api_exception_410(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.enable_state_reconciliation = False
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

    pm._last_resource_version = "v123"
    call_count = 0

    async def mock_run_watch() -> None:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ApiException(status=410)
        raise asyncio.CancelledError()

    async def mock_backoff() -> None:
        pass

    pm._run_watch = mock_run_watch  # type: ignore[method-assign]
    pm._backoff = mock_backoff  # type: ignore[method-assign]

    # watch_loop propagates CancelledError
    with pytest.raises(asyncio.CancelledError):
        await pm._watch_loop()

    # Resource version should be reset on 410
    assert pm._last_resource_version is None


@pytest.mark.asyncio
async def test_watch_loop_generic_exception(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.enable_state_reconciliation = False
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

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

    pm._run_watch = mock_run_watch  # type: ignore[method-assign]
    pm._backoff = mock_backoff  # type: ignore[method-assign]

    # watch_loop propagates CancelledError
    with pytest.raises(asyncio.CancelledError):
        await pm._watch_loop()

    assert backoff_count == 1


@pytest.mark.asyncio
async def test_pod_monitor_run_lifecycle(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    """Test PodMonitor lifecycle via run() method."""
    pod_monitor_config.enable_state_reconciliation = False

    mock_v1 = FakeV1Api()
    mock_watch = make_watch([])
    mock_k8s_clients = K8sClients(
        api_client=MagicMock(),
        v1=mock_v1,
        apps_v1=MagicMock(),
        networking_v1=MagicMock(),
        watch=mock_watch,
    )

    service, _ = create_test_kafka_event_service(event_metrics, test_settings)
    event_mapper = PodEventMapper(logger=_test_logger, k8s_api=mock_v1)

    monitor = PodMonitor(
        config=pod_monitor_config,
        kafka_event_service=service,
        logger=_test_logger,
        k8s_clients=mock_k8s_clients,
        event_mapper=event_mapper,
        kubernetes_metrics=kubernetes_metrics,
    )

    # Verify DI wiring
    assert monitor._clients is mock_k8s_clients
    assert monitor._v1 is mock_v1

    # Track when watch_loop is entered
    watch_started = asyncio.Event()

    async def _blocking_watch() -> None:
        watch_started.set()
        await asyncio.sleep(10)

    monitor._watch_loop = _blocking_watch  # type: ignore[method-assign]

    # Start and cancel - run() exits gracefully on cancel
    task = asyncio.create_task(monitor.run())
    await asyncio.wait_for(watch_started.wait(), timeout=1.0)
    task.cancel()
    await task  # Should complete without raising


@pytest.mark.asyncio
async def test_cleanup_on_cancel(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    """Test cleanup of tracked pods on cancellation."""
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

    watch_started = asyncio.Event()

    # Replace _watch_loop to add tracked pods and wait
    async def _blocking_watch() -> None:
        pm._tracked_pods = {"pod1"}
        watch_started.set()
        await asyncio.sleep(10)

    pm._watch_loop = _blocking_watch  # type: ignore[method-assign]

    task = asyncio.create_task(pm.run())
    await asyncio.wait_for(watch_started.wait(), timeout=1.0)
    assert "pod1" in pm._tracked_pods

    # Cancel - run() exits gracefully
    task.cancel()
    await task  # Should complete without raising

    # Cleanup should have cleared tracked pods
    assert len(pm._tracked_pods) == 0


def test_update_resource_version(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

    class Stream:
        _stop_event = types.SimpleNamespace(resource_version="v123")

    pm._update_resource_version(Stream())
    assert pm._last_resource_version == "v123"

    class BadStream:
        pass

    pm._update_resource_version(BadStream())


@pytest.mark.asyncio
async def test_process_raw_event_with_metadata(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

    processed: list[PodEvent] = []

    async def mock_process(event: PodEvent) -> None:
        processed.append(event)

    pm._process_pod_event = mock_process  # type: ignore[method-assign]

    raw_event = {
        "type": "ADDED",
        "object": types.SimpleNamespace(metadata=types.SimpleNamespace(resource_version="v1")),
    }

    await pm._process_raw_event(raw_event)
    assert len(processed) == 1
    assert processed[0].resource_version == "v1"

    raw_event_no_meta = {"type": "MODIFIED", "object": types.SimpleNamespace(metadata=None)}

    await pm._process_raw_event(raw_event_no_meta)
    assert len(processed) == 2
    assert processed[1].resource_version is None


@pytest.mark.asyncio
async def test_watch_loop_api_exception_other_status(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    pod_monitor_config.enable_state_reconciliation = False
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

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

    pm._run_watch = mock_run_watch  # type: ignore[method-assign]
    pm._backoff = mock_backoff  # type: ignore[method-assign]

    # watch_loop propagates CancelledError
    with pytest.raises(asyncio.CancelledError):
        await pm._watch_loop()

    assert backoff_count == 1


@pytest.mark.asyncio
async def test_run_watch_with_field_selector(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
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

    k8s_clients = K8sClients(
        api_client=MagicMock(),
        v1=TrackingV1(),
        apps_v1=MagicMock(),
        networking_v1=MagicMock(),
        watch=TrackingWatch([], "rv1"),
    )

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config, k8s_clients=k8s_clients
    )

    await pm._run_watch()

    assert any("field_selector" in kw for kw in watch_kwargs)


@pytest.mark.asyncio
async def test_watch_loop_with_reconciliation(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, test_settings: Settings,
    pod_monitor_config: PodMonitorConfig,
) -> None:
    """Test that reconciliation is called before each watch restart."""
    pod_monitor_config.enable_state_reconciliation = True
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, test_settings, config=pod_monitor_config)

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

    pm._reconcile = mock_reconcile  # type: ignore[method-assign]
    pm._run_watch = mock_run_watch  # type: ignore[method-assign]

    # watch_loop propagates CancelledError
    with pytest.raises(asyncio.CancelledError):
        await pm._watch_loop()

    # Reconcile should be called before each watch restart
    assert reconcile_count == 2
    assert watch_count == 2
