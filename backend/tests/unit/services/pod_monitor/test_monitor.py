import structlog
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.metrics import EventMetrics, KubernetesMetrics
from app.domain.events import (
    DomainEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionStartedEvent,
    ResourceUsageDomain,
)
from app.events.core import UnifiedProducer
from app.services.kafka_event_service import KafkaEventService
from app.services.pod_monitor import PodEventMapper, PodMonitor, PodMonitorConfig, WatchEventType
from app.services.pod_monitor.monitor import PodEvent
from app.settings import Settings
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client import V1Pod
from kubernetes_asyncio.client.rest import ApiException

from tests.unit.conftest import (
    MockWatchStream,
    make_mock_v1_api,
    make_mock_watch,
    make_pod,
)

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.pod_monitor")


# ===== Test doubles for KafkaEventService dependencies =====


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
    settings = Settings(config_path="config.test.toml")

    service = KafkaEventService(
        kafka_producer=fake_producer,
        settings=settings,
        logger=_test_logger,
        event_metrics=event_metrics,
    )
    return service, fake_producer


# ===== Helpers to create test instances with pure DI =====


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
        list_resource_version: str = "list-rv1",
) -> PodMonitor:
    """Create PodMonitor with sensible test defaults."""
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
    monitor._v1 = mock_v1 or make_mock_v1_api(pods=pods, list_resource_version=list_resource_version)
    monitor._watch = mock_watch or make_mock_watch(events or [], resource_version)

    return monitor


# ===== Tests =====


@pytest.mark.asyncio
async def test_watch_pod_events_list_then_watch(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
    """First call does LIST + WATCH; second call skips LIST."""
    cfg = PodMonitorConfig()

    pod = make_pod(name="existing", phase="Running", resource_version="rv1")

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, config=cfg,
        pods=[pod], list_resource_version="list-rv5",
        events=[{"type": "MODIFIED", "object": make_pod(name="existing", phase="Succeeded", resource_version="rv6")}],
        resource_version="rv7",
    )

    # First call: LIST (gets list-rv5) then WATCH (ends at rv7)
    await pm.watch_pod_events()
    assert pm._last_resource_version == "rv7"
    assert pm._v1.list_namespaced_pod.await_count == 1  # type: ignore[attr-defined]  # LIST was called

    # Second call: no LIST needed, just WATCH
    pm._watch = make_mock_watch([], "rv8")
    await pm.watch_pod_events()
    assert pm._last_resource_version == "rv8"
    assert pm._v1.list_namespaced_pod.await_count == 1  # type: ignore[attr-defined]  # LIST not called again


@pytest.mark.asyncio
async def test_watch_pod_events_with_field_selector(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()
    cfg.field_selector = "status.phase=Running"

    watch_kwargs: list[dict[str, Any]] = []

    tracking_v1 = MagicMock()

    # LIST returns a pod list with metadata
    class FakePodList:
        items: list[V1Pod] = []
        metadata = types.SimpleNamespace(resource_version="rv1")

    tracking_v1.list_namespaced_pod = AsyncMock(return_value=FakePodList())

    tracking_watch = MagicMock()

    def track_stream(func: Any, **kwargs: Any) -> MockWatchStream:  # noqa: ARG001
        watch_kwargs.append(kwargs)
        return MockWatchStream([], "rv1")

    tracking_watch.stream.side_effect = track_stream
    tracking_watch.stop.return_value = None
    tracking_watch.resource_version = "rv1"

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, config=cfg,
        mock_v1=tracking_v1, mock_watch=tracking_watch,
    )

    await pm.watch_pod_events()

    assert any("field_selector" in kw for kw in watch_kwargs)


@pytest.mark.asyncio
async def test_watch_pod_events_raises_api_exception(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
    """watch_pod_events propagates ApiException to the caller."""
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)

    # Pre-set resource version so LIST is skipped
    pm._last_resource_version = "rv1"

    mock_watch_obj = MagicMock()
    mock_watch_obj.stream.side_effect = ApiException(status=410)
    pm._watch = mock_watch_obj

    with pytest.raises(ApiException):
        await pm.watch_pod_events()


@pytest.mark.asyncio
async def test_watch_resets_after_410(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
    """After 410 Gone resets _last_resource_version, next call re-LISTs."""
    cfg = PodMonitorConfig()

    pod = make_pod(name="p1", phase="Running", resource_version="rv10")

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, config=cfg,
        pods=[pod], list_resource_version="list-rv10",
        events=[], resource_version="rv11",
    )

    # Simulate 410 recovery: provider sets _last_resource_version = None
    pm._last_resource_version = None

    await pm.watch_pod_events()

    # LIST was called, resource version set from list
    assert pm._v1.list_namespaced_pod.await_count == 1  # type: ignore[attr-defined]
    assert pm._last_resource_version == "rv11"


@pytest.mark.asyncio
async def test_process_raw_event_invalid(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg)

    # Should not raise - invalid events are caught and logged
    await pm._process_raw_event({})


@pytest.mark.asyncio
async def test_process_raw_event_with_metadata(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
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
async def test_process_pod_event_full_flow(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
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
    assert pm._last_resource_version == "v1"
    assert len(published) == 1

    event_del = PodEvent(
        event_type=WatchEventType.DELETED,
        pod=make_pod(name="test-pod", phase="Succeeded"),
        resource_version="v2",
    )

    await pm._process_pod_event(event_del)
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
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
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
async def test_publish_event_full_flow(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
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
async def test_publish_event_exception_handling(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()

    class FailingProducer(FakeUnifiedProducer):
        async def produce(
                self, event_to_produce: DomainEvent, key: str | None = None, headers: dict[str, str] | None = None
        ) -> None:
            raise RuntimeError("Publish failed")

    failing_producer = FailingProducer()
    failing_service = KafkaEventService(
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

    pod = make_pod(name="no-meta-pod", phase="Pending")
    pod.metadata = None  # type: ignore[assignment]

    # Should not raise - errors are caught and logged
    await pm._publish_event(event, pod)
