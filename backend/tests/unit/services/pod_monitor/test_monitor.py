import asyncio
import logging
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from kubernetes_asyncio import client as k8s_client

from app.core.metrics import EventMetrics, KubernetesMetrics
from app.db.repositories.event_repository import EventRepository
from app.domain.events.typed import (
    DomainEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionStartedEvent,
    ResourceUsageDomain,
)
from app.events.core import UnifiedProducer
from app.services.kafka_event_service import KafkaEventService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.services.pod_monitor.monitor import (
    MonitorState,
    PodEvent,
    PodMonitor,
    ReconciliationResult,
    WatchEventType,
)
from app.settings import Settings
from kubernetes_asyncio.client.rest import ApiException

from kubernetes_asyncio.client import V1Pod

from tests.unit.conftest import (
    MockWatchStream,
    make_mock_v1_api,
    make_mock_watch,
    make_pod,
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


def create_test_kafka_event_service(event_metrics: EventMetrics) -> tuple[KafkaEventService, FakeUnifiedProducer]:
    """Create real KafkaEventService with fake dependencies for testing."""
    fake_producer = FakeUnifiedProducer()
    fake_repo = FakeEventRepository()
    settings = Settings(config_path="config.test.toml")

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

    async def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:  # noqa: ARG002
        return []


def make_mock_api_client() -> MagicMock:
    """Create a mock ApiClient."""
    mock = MagicMock(spec=k8s_client.ApiClient)
    mock.close = AsyncMock()
    return mock


def make_pod_monitor(
        event_metrics: EventMetrics,
        kubernetes_metrics: KubernetesMetrics,
        config: PodMonitorConfig | None = None,
        kafka_service: KafkaEventService | None = None,
        api_client: k8s_client.ApiClient | None = None,
        event_mapper: PodEventMapper | None = None,
        mock_v1: Any | None = None,
        mock_watch: Any | None = None,
        pods: list[V1Pod] | None = None,
        events: list[dict[str, Any]] | None = None,
        resource_version: str = "rv1",
) -> PodMonitor:
    """Create PodMonitor with sensible test defaults.

    Since PodMonitor creates its own v1/watch from api_client,
    we create the monitor and then replace _v1 and _watch with mocks.
    """
    cfg = config or PodMonitorConfig()
    client = api_client or make_mock_api_client()
    mapper = event_mapper or PodEventMapper(logger=_test_logger, k8s_api=make_mock_v1_api("{}"))
    service = kafka_service or create_test_kafka_event_service(event_metrics)[0]

    monitor = PodMonitor(
        config=cfg,
        kafka_event_service=service,
        logger=_test_logger,
        api_client=client,
        event_mapper=mapper,
        kubernetes_metrics=kubernetes_metrics,
    )

    # Replace internal clients with mocks for testing
    monitor._v1 = mock_v1 or make_mock_v1_api(pods=pods)
    monitor._watch = mock_watch or make_mock_watch(events or [], resource_version)

    return monitor


# ===== Tests =====


@pytest.mark.asyncio
async def test_start_and_stop_lifecycle(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    spy = SpyMapper()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, event_mapper=spy)  # type: ignore[arg-type]

    # Replace _watch_pods to avoid real watch loop
    async def _quick_watch() -> None:
        return None

    pm._watch_pods = _quick_watch  # type: ignore[method-assign]

    await pm.start()
    assert pm.state == MonitorState.RUNNING

    await pm.stop()
    final_state: MonitorState = pm.state
    assert final_state == MonitorState.STOPPED
    assert spy.cleared is True


@pytest.mark.asyncio
async def test_watch_pod_events_flow_and_publish(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False

    pod = make_pod(name="p", phase="Succeeded", labels={"execution-id": "e1"}, term_exit=0, resource_version="rv1")

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, config=cfg,
        events=[{"type": "MODIFIED", "object": pod}], resource_version="rv2"
    )
    pm._state = MonitorState.RUNNING

    await pm._watch_pod_events()
    assert pm._last_resource_version == "rv2"


@pytest.mark.asyncio
async def test_process_raw_event_invalid_and_handle_watch_error(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)

    await pm._process_raw_event({})

    pm.config.watch_reconnect_delay = 0
    pm._reconnect_attempts = 0
    await pm._handle_watch_error()
    await pm._handle_watch_error()
    assert pm._reconnect_attempts >= 2


@pytest.mark.asyncio
async def test_get_status(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.namespace = "test-ns"
    cfg.label_selector = "app=test"
    cfg.enable_state_reconciliation = True

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._tracked_pods = {"pod1", "pod2"}
    pm._reconnect_attempts = 3
    pm._last_resource_version = "v123"

    status = await pm.get_status()
    assert "idle" in status["state"].lower()
    assert status["tracked_pods"] == 2
    assert status["reconnect_attempts"] == 3
    assert status["last_resource_version"] == "v123"
    assert status["config"]["namespace"] == "test-ns"
    assert status["config"]["label_selector"] == "app=test"
    assert status["config"]["enable_reconciliation"] is True


@pytest.mark.asyncio
async def test_reconciliation_loop_and_state(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True
    cfg.reconcile_interval_seconds = 0  # sleep(0) yields control immediately

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._state = MonitorState.RUNNING

    reconcile_called: list[bool] = []

    async def mock_reconcile() -> ReconciliationResult:
        reconcile_called.append(True)
        return ReconciliationResult(missing_pods={"p1"}, extra_pods={"p2"}, duration_seconds=0.1, success=True)

    evt = asyncio.Event()

    async def wrapped_reconcile() -> ReconciliationResult:
        res = await mock_reconcile()
        evt.set()
        return res

    pm._reconcile_state = wrapped_reconcile  # type: ignore[method-assign]

    task = asyncio.create_task(pm._reconciliation_loop())
    await asyncio.wait_for(evt.wait(), timeout=1.0)
    pm._state = MonitorState.STOPPED
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(reconcile_called) > 0


@pytest.mark.asyncio
async def test_reconcile_state_success(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.namespace = "test"
    cfg.label_selector = "app=test"

    pod1 = make_pod(name="pod1", phase="Running", resource_version="v1")
    pod2 = make_pod(name="pod2", phase="Running", resource_version="v1")

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, pods=[pod1, pod2])
    pm._tracked_pods = {"pod2", "pod3"}

    processed: list[str] = []

    async def mock_process(event: PodEvent) -> None:
        processed.append(event.pod.metadata.name)

    pm._process_pod_event = mock_process  # type: ignore[method-assign]

    result = await pm._reconcile_state()

    assert result.success is True
    assert result.missing_pods == {"pod1"}
    assert result.extra_pods == {"pod3"}
    assert "pod1" in processed
    assert "pod3" not in pm._tracked_pods


@pytest.mark.asyncio
async def test_reconcile_state_exception(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()

    fail_v1 = MagicMock()
    fail_v1.list_namespaced_pod = AsyncMock(side_effect=RuntimeError("API error"))

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, mock_v1=fail_v1)

    result = await pm._reconcile_state()
    assert result.success is False
    assert result.error is not None
    assert "API error" in result.error


@pytest.mark.asyncio
async def test_process_pod_event_full_flow(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.ignored_pod_phases = ["Unknown"]

    class MockMapper:
        async def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:  # noqa: ARG002
            class Event:
                event_type = types.SimpleNamespace(value="test_event")
                metadata = types.SimpleNamespace(correlation_id=None)
                aggregate_id = "agg1"

            return [Event()]

        def clear_cache(self) -> None:
            pass

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, event_mapper=MockMapper())  # type: ignore[arg-type]

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
async def test_process_pod_event_exception_handling(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()

    class FailMapper:
        async def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:
            raise RuntimeError("Mapping failed")

        def clear_cache(self) -> None:
            pass

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, event_mapper=FailMapper())  # type: ignore[arg-type]

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="fail-pod", phase="Pending"),
        resource_version=None,
    )

    # Should not raise - errors are caught and logged
    await pm._process_pod_event(event)


@pytest.mark.asyncio
async def test_publish_event_full_flow(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    service, fake_producer = create_test_kafka_event_service(event_metrics)
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, kafka_service=service)

    event = ExecutionCompletedEvent(
        execution_id="exec1",
        aggregate_id="exec1",
        exit_code=0,
        resource_usage=ResourceUsageDomain(),
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )

    pod = make_pod(name="test-pod", phase="Succeeded", labels={"execution-id": "exec1"})
    await pm._publish_event(event, pod)

    assert len(fake_producer.produced_events) == 1
    assert fake_producer.produced_events[0][1] == "exec1"


@pytest.mark.asyncio
async def test_publish_event_exception_handling(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()

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
        settings=Settings(config_path="config.test.toml"),
        logger=_test_logger,
        event_metrics=event_metrics,
    )

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, kafka_service=failing_service)

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
async def test_handle_watch_error_max_attempts(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.max_reconnect_attempts = 2

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._state = MonitorState.RUNNING
    pm._reconnect_attempts = 2

    await pm._handle_watch_error()

    assert pm._state == MonitorState.STOPPING


@pytest.mark.asyncio
async def test_watch_pods_main_loop(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._state = MonitorState.RUNNING

    watch_count: list[int] = []

    async def mock_watch() -> None:
        watch_count.append(1)
        if len(watch_count) > 2:
            pm._state = MonitorState.STOPPED

    async def mock_handle_error() -> None:
        pass

    pm._watch_pod_events = mock_watch  # type: ignore[method-assign]
    pm._handle_watch_error = mock_handle_error  # type: ignore[method-assign]

    await pm._watch_pods()
    assert len(watch_count) > 2


@pytest.mark.asyncio
async def test_watch_pods_api_exception(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._state = MonitorState.RUNNING

    async def mock_watch() -> None:
        raise ApiException(status=410)

    error_handled: list[bool] = []

    async def mock_handle() -> None:
        error_handled.append(True)
        pm._state = MonitorState.STOPPED

    pm._watch_pod_events = mock_watch  # type: ignore[method-assign]
    pm._handle_watch_error = mock_handle  # type: ignore[method-assign]

    await pm._watch_pods()

    assert pm._last_resource_version is None
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_watch_pods_generic_exception(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._state = MonitorState.RUNNING

    async def mock_watch() -> None:
        raise RuntimeError("Unexpected error")

    error_handled: list[bool] = []

    async def mock_handle() -> None:
        error_handled.append(True)
        pm._state = MonitorState.STOPPED

    pm._watch_pod_events = mock_watch  # type: ignore[method-assign]
    pm._handle_watch_error = mock_handle  # type: ignore[method-assign]

    await pm._watch_pods()
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_start_and_stop(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test explicit start() and stop() methods."""
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = False
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)

    assert pm.state == MonitorState.IDLE

    await pm.start()
    state_after_start: MonitorState = pm.state
    assert state_after_start == MonitorState.RUNNING

    await pm.stop()
    state_after_stop: MonitorState = pm.state
    assert state_after_stop == MonitorState.STOPPED


@pytest.mark.asyncio
async def test_stop_with_tasks(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test cleanup of tasks on stop()."""
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._state = MonitorState.RUNNING

    async def dummy_task() -> None:
        await asyncio.Event().wait()

    pm._watch_task = asyncio.create_task(dummy_task())
    pm._reconcile_task = asyncio.create_task(dummy_task())
    pm._tracked_pods = {"pod1"}

    await pm.stop()

    assert pm._state == MonitorState.STOPPED
    assert len(pm._tracked_pods) == 0


@pytest.mark.asyncio
async def test_process_raw_event_with_metadata(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)

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
async def test_watch_pods_api_exception_other_status(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._state = MonitorState.RUNNING

    async def mock_watch() -> None:
        raise ApiException(status=500)

    error_handled: list[bool] = []

    async def mock_handle() -> None:
        error_handled.append(True)
        pm._state = MonitorState.STOPPED

    pm._watch_pod_events = mock_watch  # type: ignore[method-assign]
    pm._handle_watch_error = mock_handle  # type: ignore[method-assign]

    await pm._watch_pods()
    assert len(error_handled) > 0


@pytest.mark.asyncio
async def test_watch_pod_events_with_field_selector(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.field_selector = "status.phase=Running"
    cfg.enable_state_reconciliation = False

    watch_kwargs: list[dict[str, Any]] = []

    tracking_v1 = MagicMock()

    def track_list(namespace: str, label_selector: str) -> None:
        watch_kwargs.append({"namespace": namespace, "label_selector": label_selector})
        return None

    tracking_v1.list_namespaced_pod.side_effect = track_list

    tracking_watch = MagicMock()

    def track_stream(func: Any, **kwargs: Any) -> MockWatchStream:  # noqa: ARG001
        watch_kwargs.append(kwargs)
        return MockWatchStream([], "rv1")

    tracking_watch.stream.side_effect = track_stream
    tracking_watch.stop.return_value = None
    tracking_watch.resource_version = "rv1"

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, config=cfg,
        mock_v1=tracking_v1, mock_watch=tracking_watch
    )
    pm._state = MonitorState.RUNNING

    await pm._watch_pod_events()

    assert any("field_selector" in kw for kw in watch_kwargs)


@pytest.mark.asyncio
async def test_reconciliation_loop_exception(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True
    cfg.reconcile_interval_seconds = 0  # sleep(0) yields control immediately

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)
    pm._state = MonitorState.RUNNING

    hit = asyncio.Event()

    async def raising() -> ReconciliationResult:
        hit.set()
        raise RuntimeError("Reconcile error")

    pm._reconcile_state = raising  # type: ignore[method-assign]

    task = asyncio.create_task(pm._reconciliation_loop())
    await asyncio.wait_for(hit.wait(), timeout=1.0)
    pm._state = MonitorState.STOPPED
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_start_with_reconciliation(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    cfg = PodMonitorConfig()
    cfg.enable_state_reconciliation = True

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)

    async def mock_watch() -> None:
        return None

    async def mock_reconcile() -> None:
        return None

    pm._watch_pods = mock_watch  # type: ignore[method-assign]
    pm._reconciliation_loop = mock_reconcile  # type: ignore[method-assign]

    await pm.start()
    assert pm._watch_task is not None
    assert pm._reconcile_task is not None

    await pm.stop()
