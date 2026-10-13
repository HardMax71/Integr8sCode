import types
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client import V1ListMeta, V1Pod, V1PodList
from kubernetes_asyncio.client.rest import ApiException

from app.core.metrics import EventMetrics, KubernetesMetrics
from app.domain.enums import EventType
from app.domain.events import (
    DomainEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    ResourceUsageDomain,
)
from app.events.core import UnifiedProducer
from app.services.pod_monitor import ErrorType, PodEventMapper, PodMonitor, PodMonitorConfig, WatchEventType
from app.services.pod_monitor.monitor import PodEvent
from tests.unit.conftest import (
    make_mock_v1_api,
    make_mock_watch,
    make_pod,
)

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.pod_monitor")


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


def make_mock_api_client() -> MagicMock:
    """Create a mock ApiClient."""
    mock = MagicMock(spec=k8s_client.ApiClient)
    mock.close = AsyncMock()
    return mock


def make_pod_monitor(
    event_metrics: EventMetrics,
    kubernetes_metrics: KubernetesMetrics,
    config: PodMonitorConfig | None = None,
    producer: UnifiedProducer | None = None,
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
    mapper = event_mapper or PodEventMapper(logger=_test_logger, k8s_api=make_mock_v1_api())

    with patch("app.services.pod_monitor.monitor.k8s_watch.Watch"):
        monitor = PodMonitor(
            config=cfg,
            producer=producer or FakeUnifiedProducer(),
            logger=_test_logger,
            api_client=client,
            event_mapper=mapper,
            kubernetes_metrics=kubernetes_metrics,
        )

    # Replace internal clients with mocks for testing
    monitor._v1 = mock_v1 or make_mock_v1_api(pods=pods, list_resource_version=list_resource_version)
    monitor._watch = mock_watch or make_mock_watch(events or [], resource_version)

    return monitor


async def test_watch_pod_events_list_then_watch(
    event_metrics: EventMetrics,
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    """First call does LIST + WATCH; second call skips LIST."""
    cfg = PodMonitorConfig()

    pod = make_pod(name="existing", phase="Running", resource_version="rv1")

    mock_v1 = make_mock_v1_api(pods=[pod], list_resource_version="list-rv5")
    pm = make_pod_monitor(
        event_metrics,
        kubernetes_metrics,
        config=cfg,
        mock_v1=mock_v1,
        events=[{"type": "MODIFIED", "object": make_pod(name="existing", phase="Succeeded", resource_version="rv6")}],
        resource_version="rv7",
    )

    # First call: LIST (gets list-rv5) then WATCH (ends at rv7)
    await pm.watch_pod_events()
    assert pm._last_resource_version == "rv7"
    assert mock_v1.list_namespaced_pod.await_count == 1

    # Second call: no LIST needed, just WATCH
    pm._watch = make_mock_watch([], "rv8")
    await pm.watch_pod_events()
    assert pm._last_resource_version == "rv8"
    assert mock_v1.list_namespaced_pod.await_count == 1


async def test_watch_pod_events_with_field_selector(
    event_metrics: EventMetrics,
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()
    cfg.field_selector = "status.phase=Running"

    tracking_v1 = MagicMock()
    tracking_v1.list_namespaced_pod = AsyncMock(
        return_value=V1PodList(items=[], metadata=V1ListMeta(resource_version="rv1"))
    )
    tracking_watch = make_mock_watch([], "rv1")

    pm = make_pod_monitor(
        event_metrics,
        kubernetes_metrics,
        config=cfg,
        mock_v1=tracking_v1,
        mock_watch=tracking_watch,
    )

    await pm.watch_pod_events()

    assert tracking_watch.stream.call_args.kwargs["field_selector"] == "status.phase=Running"


async def test_watch_pod_events_raises_api_exception(
    event_metrics: EventMetrics,
    kubernetes_metrics: KubernetesMetrics,
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


async def test_watch_resets_after_410(
    event_metrics: EventMetrics,
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    """After 410 Gone resets _last_resource_version, next call re-LISTs."""
    cfg = PodMonitorConfig()

    pod = make_pod(name="p1", phase="Running", resource_version="rv10")
    mock_v1 = make_mock_v1_api(pods=[pod], list_resource_version="list-rv10")
    pm = make_pod_monitor(
        event_metrics,
        kubernetes_metrics,
        config=cfg,
        mock_v1=mock_v1,
        events=[],
        resource_version="rv11",
    )

    # What watch_cycle does on a 410
    pm._last_resource_version = None

    await pm.watch_pod_events()

    # LIST was called, resource version set from list
    assert mock_v1.list_namespaced_pod.await_count == 1
    assert pm._last_resource_version == "rv11"


async def test_process_pod_event_full_flow(
    event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = PodMonitorConfig()
    cfg.ignored_pod_phases = ["Unknown"]

    mapper = AsyncMock(spec=PodEventMapper)
    mapper.map_pod_event.return_value = [types.SimpleNamespace(event_type=EventType.POD_RUNNING, aggregate_id="agg1")]
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, event_mapper=mapper)
    publish = AsyncMock()
    monkeypatch.setattr(pm, "_publish_event", publish)

    event = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="test-pod", phase="Running"),
    )

    await pm._process_pod_event(event)
    assert publish.await_count == 1

    event_del = PodEvent(
        event_type=WatchEventType.DELETED,
        pod=make_pod(name="test-pod", phase="Succeeded"),
    )

    await pm._process_pod_event(event_del)
    assert publish.await_count == 2

    event_ignored = PodEvent(
        event_type=WatchEventType.ADDED,
        pod=make_pod(name="ignored-pod", phase="Unknown"),
    )

    await pm._process_pod_event(event_ignored)
    assert publish.await_count == 2


async def test_process_pod_event_exception_handling(event_metrics: EventMetrics) -> None:
    cfg = PodMonitorConfig()

    mapper = AsyncMock(spec=PodEventMapper)
    mapper.map_pod_event.side_effect = RuntimeError("Mapping failed")
    metrics = MagicMock(spec=KubernetesMetrics)
    pm = make_pod_monitor(event_metrics, metrics, config=cfg, event_mapper=mapper)

    pod = make_pod(name="fail-pod", phase="Pending")
    await pm._process_pod_event(PodEvent(event_type=WatchEventType.ADDED, pod=pod))

    metrics.record_pod_monitor_watch_error.assert_called_once_with(ErrorType.PROCESSING_ERROR)


async def test_publish_event_full_flow(
    event_metrics: EventMetrics,
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()
    fake_producer = FakeUnifiedProducer()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, producer=fake_producer)

    event = ExecutionCompletedEvent(
        execution_id="exec1",
        aggregate_id="exec1",
        exit_code=0,
        resource_usage=ResourceUsageDomain(),
        metadata=EventMetadata(service_name="test", service_version="1.0", user_id="u1"),
    )

    pod = make_pod(name="test-pod", phase="Succeeded", labels={"execution-id": "exec1"})
    await pm._publish_event(event, pod)

    assert len(fake_producer.produced_events) == 1
    assert fake_producer.produced_events[0][1] == "exec1"


async def test_publish_event_exception_handling(
    event_metrics: EventMetrics,
    kubernetes_metrics: KubernetesMetrics,
) -> None:
    cfg = PodMonitorConfig()

    producer = AsyncMock(spec=UnifiedProducer)
    producer.produce.side_effect = RuntimeError("Publish failed")
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, producer=producer)

    event = ExecutionCompletedEvent(
        execution_id="exec1",
        exit_code=0,
        resource_usage=ResourceUsageDomain(),
        metadata=EventMetadata(service_name="test", service_version="1.0", user_id="u1"),
    )

    pod = make_pod(name="failing-pod", phase="Pending")

    # Exception propagates — _process_pod_event's broad except handles it
    with pytest.raises(RuntimeError, match="Publish failed"):
        await pm._publish_event(event, pod)


async def test_list_and_watch_keep_pods_by_phase_current(event_metrics: EventMetrics) -> None:
    metrics = MagicMock(spec=KubernetesMetrics)
    pm = make_pod_monitor(
        event_metrics,
        metrics,
        pods=[make_pod(name="p1", phase="Pending"), make_pod(name="p2", phase="Running")],
        events=[
            {"type": "MODIFIED", "object": make_pod(name="p1", phase="Running")},
            {"type": "DELETED", "object": make_pod(name="p2", phase="Succeeded")},
        ],
    )

    await pm.watch_pod_events()

    metrics.record_pod_monitor_reconciliation_run.assert_called_once_with()
    counts = [dict(c.args[0]) for c in metrics.update_pods_by_phase.call_args_list]
    assert counts == [{}, {"Pending": 1}, {"Pending": 1, "Running": 1}, {"Running": 2}, {"Running": 1}]


@pytest.mark.parametrize(("fresh", "expected"), [(["fresh"], {"Pending": 1}), ([], {})])
async def test_relist_drops_pods_the_watch_missed(
    event_metrics: EventMetrics, fresh: list[str], expected: dict[str, int]
) -> None:
    metrics = MagicMock(spec=KubernetesMetrics)
    pm = make_pod_monitor(event_metrics, metrics, pods=[make_pod(name="gone", phase="Running")])
    await pm.watch_pod_events()

    pm._last_resource_version = None
    pm._v1 = make_mock_v1_api(pods=[make_pod(name=name, phase="Pending") for name in fresh])
    pm._watch = make_mock_watch([])
    await pm.watch_pod_events()

    assert metrics.record_pod_monitor_reconciliation_run.call_count == 2
    assert dict(metrics.update_pods_by_phase.call_args.args[0]) == expected


async def test_terminal_event_records_pod_lifetime(
    event_metrics: EventMetrics, monkeypatch: pytest.MonkeyPatch
) -> None:
    mapper = AsyncMock(spec=PodEventMapper)
    mapper.map_pod_event.return_value = [
        types.SimpleNamespace(event_type=EventType.EXECUTION_COMPLETED, execution_id="exec1")
    ]
    metrics = MagicMock(spec=KubernetesMetrics)
    mock_v1 = make_mock_v1_api()
    mock_v1.delete_namespaced_pod = AsyncMock()
    pm = make_pod_monitor(event_metrics, metrics, event_mapper=mapper, mock_v1=mock_v1)
    monkeypatch.setattr(pm, "_publish_event", AsyncMock())

    pod = make_pod(name="done", phase="Succeeded", labels={"language": "python"})
    pod.metadata.creation_timestamp = datetime.now(timezone.utc) - timedelta(seconds=30)
    await pm._process_pod_event(PodEvent(event_type=WatchEventType.MODIFIED, pod=pod))

    metrics.record_pod_lifetime.assert_called_once()
    lifetime, phase, language = metrics.record_pod_lifetime.call_args.args
    assert lifetime >= 30
    assert (phase, language) == ("Succeeded", "python")
    mock_v1.delete_namespaced_pod.assert_awaited_once()


async def test_non_terminal_event_records_no_lifetime(
    event_metrics: EventMetrics, monkeypatch: pytest.MonkeyPatch
) -> None:
    mapper = AsyncMock(spec=PodEventMapper)
    mapper.map_pod_event.return_value = [types.SimpleNamespace(event_type=EventType.POD_RUNNING, execution_id="exec1")]
    metrics = MagicMock(spec=KubernetesMetrics)
    pm = make_pod_monitor(event_metrics, metrics, event_mapper=mapper)
    monkeypatch.setattr(pm, "_publish_event", AsyncMock())

    pod = make_pod(name="busy", phase="Running", labels={"language": "python"})
    pod.metadata.creation_timestamp = datetime.now(timezone.utc)
    await pm._process_pod_event(PodEvent(event_type=WatchEventType.MODIFIED, pod=pod))

    metrics.record_pod_lifetime.assert_not_called()


@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (ApiException(status=410), ErrorType.RESOURCE_VERSION_EXPIRED),
        (ApiException(status=500), ErrorType.API_ERROR),
        (RuntimeError("boom"), ErrorType.UNEXPECTED),
    ],
)
async def test_watch_cycle_counts_the_error_that_ended_it(
    event_metrics: EventMetrics, error: Exception, error_type: ErrorType, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics = MagicMock(spec=KubernetesMetrics)
    pm = make_pod_monitor(event_metrics, metrics)
    pm._last_resource_version = "rv-before"
    monkeypatch.setattr(pm, "watch_pod_events", AsyncMock(side_effect=error))

    await pm.watch_cycle()

    metrics.record_pod_monitor_watch_error.assert_called_once_with(error_type)
    metrics.increment_pod_monitor_watch_reconnects.assert_called_once()
    expired = error_type == ErrorType.RESOURCE_VERSION_EXPIRED
    assert pm._last_resource_version == (None if expired else "rv-before")


async def test_watch_cycle_counts_nothing_when_the_watch_ends_normally(
    event_metrics: EventMetrics, monkeypatch: pytest.MonkeyPatch
) -> None:
    metrics = MagicMock(spec=KubernetesMetrics)
    pm = make_pod_monitor(event_metrics, metrics)
    monkeypatch.setattr(pm, "watch_pod_events", AsyncMock())

    await pm.watch_cycle()

    metrics.record_pod_monitor_watch_error.assert_not_called()
