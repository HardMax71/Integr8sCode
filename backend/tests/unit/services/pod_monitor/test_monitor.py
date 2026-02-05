import logging
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.metrics import KubernetesMetrics
from app.domain.events.typed import (
    BaseEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionStartedEvent,
    ResourceUsageDomain,
)
from app.events.core import EventPublisher
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.services.pod_monitor.monitor import (
    PodEvent,
    PodMonitor,
    WatchEventType,
)
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

_test_logger = logging.getLogger("test.pod_monitor")


# ===== Test doubles for EventPublisher =====


class FakeEventPublisher(EventPublisher):
    """Fake producer that captures events without Kafka."""

    def __init__(self) -> None:
        # Don't call super().__init__ - we don't need real Kafka
        self.produced_events: list[tuple[BaseEvent, str | None]] = []
        self.logger = _test_logger

    async def publish(
            self, event: BaseEvent, key: str | None = None
    ) -> str:
        self.produced_events.append((event, key))
        return event.event_id

    async def aclose(self) -> None:
        pass


# ===== Helpers to create test instances with pure DI =====


def make_mock_api_client() -> MagicMock:
    """Create a mock ApiClient."""
    mock = MagicMock(spec=k8s_client.ApiClient)
    mock.close = AsyncMock()
    return mock


def make_pod_monitor(
        kubernetes_metrics: KubernetesMetrics,
        config: PodMonitorConfig | None = None,
        producer: FakeEventPublisher | None = None,
        api_client: k8s_client.ApiClient | None = None,
        event_mapper: PodEventMapper | None = None,
        mock_v1: Any | None = None,
        mock_watch: Any | None = None,
        pods: list[V1Pod] | None = None,
        events: list[dict[str, Any]] | None = None,
        resource_version: str = "rv1",
        list_resource_version: str = "list-rv1",
) -> tuple[PodMonitor, FakeEventPublisher]:
    """Create PodMonitor with sensible test defaults."""
    cfg = config or PodMonitorConfig()
    client = api_client or make_mock_api_client()
    mapper = event_mapper or PodEventMapper(logger=_test_logger, k8s_api=make_mock_v1_api("{}"))
    fake_producer = producer or FakeEventPublisher()

    monitor = PodMonitor(
        config=cfg,
        producer=fake_producer,
        logger=_test_logger,
        api_client=client,
        event_mapper=mapper,
        kubernetes_metrics=kubernetes_metrics,
    )

    # Replace internal clients with mocks for testing
    monitor._v1 = mock_v1 or make_mock_v1_api(pods=pods, list_resource_version=list_resource_version)
    monitor._watch = mock_watch or make_mock_watch(events or [], resource_version)

    return monitor, fake_producer


# ===== Tests =====


@pytest.mark.asyncio
async def test_watch_pod_events_list_then_watch(
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    """First call does LIST + WATCH; second call skips LIST."""
    cfg = PodMonitorConfig()

    pod = make_pod(name="existing", phase="Running", resource_version="rv1")

    pm, _ = make_pod_monitor(
        kubernetes_metrics, config=cfg,
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
    kubernetes_metrics: KubernetesMetrics,
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

    pm, _ = make_pod_monitor(
        kubernetes_metrics, config=cfg,
        mock_v1=tracking_v1, mock_watch=tracking_watch,
    )

    await pm.watch_pod_events()

    assert any("field_selector" in kw for kw in watch_kwargs)


@pytest.mark.asyncio
async def test_watch_pod_events_raises_api_exception(
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    """watch_pod_events propagates ApiException to the caller."""
    cfg = PodMonitorConfig()
    pm, _ = make_pod_monitor(kubernetes_metrics, config=cfg)

    # Pre-set resource version so LIST is skipped
    pm._last_resource_version = "rv1"

    mock_watch_obj = MagicMock()
    mock_watch_obj.stream.side_effect = ApiException(status=410)
    pm._watch = mock_watch_obj

    with pytest.raises(ApiException):
        await pm.watch_pod_events()


@pytest.mark.asyncio
async def test_watch_resets_after_410(
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    """After 410 Gone resets _last_resource_version, next call re-LISTs."""
    cfg = PodMonitorConfig()

    pod = make_pod(name="p1", phase="Running", resource_version="rv10")

    pm, _ = make_pod_monitor(
        kubernetes_metrics, config=cfg,
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
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()
    pm, _ = make_pod_monitor(kubernetes_metrics, config=cfg)

    # Should not raise - invalid events are caught and logged
    await pm._process_raw_event({})


@pytest.mark.asyncio
async def test_process_raw_event_with_metadata(
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()
    pm, _ = make_pod_monitor(kubernetes_metrics, config=cfg)

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
    kubernetes_metrics: KubernetesMetrics,
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

    pm, _ = make_pod_monitor(kubernetes_metrics, config=cfg, event_mapper=MockMapper())  # type: ignore[arg-type]

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
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()

    class FailMapper:
        async def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:
            raise RuntimeError("Mapping failed")

        def clear_cache(self) -> None:
            pass

    pm, _ = make_pod_monitor(kubernetes_metrics, config=cfg, event_mapper=FailMapper())  # type: ignore[arg-type]

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="fail-pod", phase="Pending"),
        resource_version=None,
    )

    # Should not raise - errors are caught and logged
    await pm._process_pod_event(event)


@pytest.mark.asyncio
async def test_publish_event_full_flow(
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()
    pm, fake_producer = make_pod_monitor(kubernetes_metrics, config=cfg)

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
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()

    class FailingProducer(FakeEventPublisher):
        async def produce(
                self, event: BaseEvent, key: str | None = None
        ) -> str:
            raise RuntimeError("Publish failed")

    failing_producer = FailingProducer()

    pm, _ = make_pod_monitor(kubernetes_metrics, config=cfg, producer=failing_producer)

    event = ExecutionStartedEvent(
        execution_id="exec1",
        pod_name="test-pod",
        metadata=EventMetadata(service_name="test", service_version="1.0"),
    )

    pod = make_pod(name="no-meta-pod", phase="Pending")
    pod.metadata = None  # type: ignore[assignment]

    # Should not raise - errors are caught and logged
    await pm._publish_event(event, pod)
