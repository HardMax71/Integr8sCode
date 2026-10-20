from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client import V1ListMeta, V1Pod, V1PodList
from kubernetes_asyncio.client.rest import ApiException
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from app.domain.events import (
    DomainEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    PodRunningEvent,
    ResourceUsageDomain,
)
from app.events.core import UnifiedProducer
from app.services.execution_scheduler import ExecutionScheduler
from app.services.pod_monitor import ErrorType, PodEventMapper, PodMonitor, PodMonitorConfig, WatchEventType
from app.services.pod_monitor.monitor import PodEvent
from app.services.result_processor import ResultProcessor
from tests.unit.conftest import (
    make_mock_v1_api,
    make_mock_watch,
    make_pod,
)

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.pod_monitor")

_METADATA = EventMetadata(service_name="pod-monitor", service_version="1.0.0", user_id="u1")


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
    tracer: trace.Tracer,
    config: PodMonitorConfig | None = None,
    producer: UnifiedProducer | None = None,
    api_client: k8s_client.ApiClient | None = None,
    event_mapper: PodEventMapper | None = None,
    results: ResultProcessor | None = None,
    scheduler: ExecutionScheduler | None = None,
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
            results=results or AsyncMock(spec=ResultProcessor),
            scheduler=scheduler or AsyncMock(spec=ExecutionScheduler),
            tracer=tracer,
        )

    # Replace internal clients with mocks for testing
    monitor._v1 = mock_v1 or make_mock_v1_api(pods=pods, list_resource_version=list_resource_version)
    monitor._watch = mock_watch or make_mock_watch(events or [], resource_version)

    return monitor


def span_attributes(exporter: InMemorySpanExporter, name: str) -> list[dict[str, Any]]:
    """The attributes of every finished span with this name, in the order they ended."""
    return [dict(span.attributes or {}) for span in exporter.get_finished_spans() if span.name == name]


async def test_watch_pod_events_list_then_watch(tracer: trace.Tracer) -> None:
    """First call does LIST + WATCH; second call skips LIST."""
    cfg = PodMonitorConfig()

    pod = make_pod(name="existing", phase="Running", resource_version="rv1")

    mock_v1 = make_mock_v1_api(pods=[pod], list_resource_version="list-rv5")
    pm = make_pod_monitor(
        tracer,
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


async def test_watch_pod_events_with_field_selector(tracer: trace.Tracer) -> None:
    cfg = PodMonitorConfig()
    cfg.field_selector = "status.phase=Running"

    tracking_v1 = MagicMock()
    tracking_v1.list_namespaced_pod = AsyncMock(
        return_value=V1PodList(items=[], metadata=V1ListMeta(resource_version="rv1"))
    )
    tracking_watch = make_mock_watch([], "rv1")

    pm = make_pod_monitor(tracer, config=cfg, mock_v1=tracking_v1, mock_watch=tracking_watch)

    await pm.watch_pod_events()

    assert tracking_watch.stream.call_args.kwargs["field_selector"] == "status.phase=Running"


async def test_watch_pod_events_raises_api_exception(tracer: trace.Tracer) -> None:
    """watch_pod_events propagates ApiException to the caller."""
    cfg = PodMonitorConfig()
    pm = make_pod_monitor(tracer, config=cfg)

    # Pre-set resource version so LIST is skipped
    pm._last_resource_version = "rv1"

    mock_watch_obj = MagicMock()
    mock_watch_obj.stream.side_effect = ApiException(status=410)
    pm._watch = mock_watch_obj

    with pytest.raises(ApiException):
        await pm.watch_pod_events()


async def test_watch_resets_after_410(tracer: trace.Tracer) -> None:
    """After 410 Gone resets _last_resource_version, next call re-LISTs."""
    cfg = PodMonitorConfig()

    pod = make_pod(name="p1", phase="Running", resource_version="rv10")
    mock_v1 = make_mock_v1_api(pods=[pod], list_resource_version="list-rv10")
    pm = make_pod_monitor(tracer, config=cfg, mock_v1=mock_v1, events=[], resource_version="rv11")

    # What watch_cycle does on a 410
    pm._last_resource_version = None

    await pm.watch_pod_events()

    # LIST was called, resource version set from list
    assert mock_v1.list_namespaced_pod.await_count == 1
    assert pm._last_resource_version == "rv11"


async def test_process_pod_event_full_flow(tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
    cfg = PodMonitorConfig()
    cfg.ignored_pod_phases = ["Unknown"]

    mapper = AsyncMock(spec=PodEventMapper)
    running = PodRunningEvent(execution_id="exec1", pod_name="test-pod", metadata=_METADATA)
    mapper.map_pod_event.return_value = [running]
    producer = FakeUnifiedProducer()
    results = AsyncMock(spec=ResultProcessor)
    pm = make_pod_monitor(tracer, config=cfg, event_mapper=mapper, producer=producer, results=results)

    await pm._process_pod_event(
        PodEvent(event_type=WatchEventType.ADDED, pod=make_pod(name="test-pod", phase="Running"))
    )
    await pm._process_pod_event(
        PodEvent(event_type=WatchEventType.DELETED, pod=make_pod(name="test-pod", phase="Succeeded"))
    )
    await pm._process_pod_event(
        PodEvent(event_type=WatchEventType.ADDED, pod=make_pod(name="ignored-pod", phase="Unknown"))
    )

    assert [key for _, key in producer.produced_events] == ["exec1", "exec1"]
    assert results.handle_pod_progress.await_count == 2
    assert span_attributes(span_exporter, "pod_monitor.event") == [
        {"pod_monitor.watch_event": "ADDED", "pod.phase": "Running", "pod_monitor.published": 1},
        {"pod_monitor.watch_event": "DELETED", "pod.phase": "Succeeded", "pod_monitor.published": 1},
    ]


async def test_process_pod_event_exception_handling(tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
    mapper = AsyncMock(spec=PodEventMapper)
    mapper.map_pod_event.side_effect = RuntimeError("Mapping failed")
    pm = make_pod_monitor(tracer, event_mapper=mapper)

    pod = make_pod(name="fail-pod", phase="Pending")
    await pm._process_pod_event(PodEvent(event_type=WatchEventType.ADDED, pod=pod))

    [attributes] = span_attributes(span_exporter, "pod_monitor.event")
    assert attributes["pod_monitor.error_type"] == ErrorType.PROCESSING_ERROR


async def test_watch_cycle_reports_every_phase(tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
    pm = make_pod_monitor(
        tracer,
        pods=[make_pod(name="p1", phase="Pending"), make_pod(name="p2", phase="Running")],
        events=[
            {"type": "MODIFIED", "object": make_pod(name="p1", phase="Running")},
            {"type": "DELETED", "object": make_pod(name="p2", phase="Succeeded")},
        ],
    )

    await pm.watch_cycle()

    assert len(span_attributes(span_exporter, "pod_monitor.list")) == 1
    phases = {a["pod.phase"]: a["pod_monitor.pods"] for a in span_attributes(span_exporter, "pod_monitor.pods")}
    assert phases == {"Pending": 0, "Running": 1, "Succeeded": 0, "Failed": 0, "Unknown": 0}


@pytest.mark.parametrize(("fresh", "pending"), [(["fresh"], 1), ([], 0)])
async def test_relist_drops_pods_the_watch_missed(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter, fresh: list[str], pending: int
) -> None:
    pm = make_pod_monitor(tracer, pods=[make_pod(name="gone", phase="Running")])
    await pm.watch_pod_events()

    pm._last_resource_version = None
    pm._v1 = make_mock_v1_api(pods=[make_pod(name=name, phase="Pending") for name in fresh])
    pm._watch = make_mock_watch([])
    await pm.watch_cycle()

    assert len(span_attributes(span_exporter, "pod_monitor.list")) == 2
    phases = {a["pod.phase"]: a["pod_monitor.pods"] for a in span_attributes(span_exporter, "pod_monitor.pods")}
    assert (phases["Pending"], phases["Running"]) == (pending, 0)


async def test_terminal_event_records_pod_lifetime(tracer: trace.Tracer, span_exporter: InMemorySpanExporter) -> None:
    mapper = AsyncMock(spec=PodEventMapper)
    completed = ExecutionCompletedEvent(
        execution_id="exec1", exit_code=0, resource_usage=ResourceUsageDomain(), metadata=_METADATA
    )
    mapper.map_pod_event.return_value = [completed]
    mock_v1 = make_mock_v1_api()
    mock_v1.delete_namespaced_pod = AsyncMock()
    producer = FakeUnifiedProducer()
    results = AsyncMock(spec=ResultProcessor)
    scheduler = AsyncMock(spec=ExecutionScheduler)
    pm = make_pod_monitor(
        tracer, event_mapper=mapper, mock_v1=mock_v1, producer=producer, results=results, scheduler=scheduler
    )

    pod = make_pod(name="done", phase="Succeeded", labels={"language": "python"})
    pod.metadata.creation_timestamp = datetime.now(timezone.utc) - timedelta(seconds=30)
    await pm._process_pod_event(PodEvent(event_type=WatchEventType.MODIFIED, pod=pod))

    [attributes] = span_attributes(span_exporter, "pod_monitor.event")
    assert attributes["pod.lifetime_seconds"] >= 30
    assert (attributes["pod.phase"], attributes["pod.language"]) == ("Succeeded", "python")
    mock_v1.delete_namespaced_pod.assert_awaited_once()
    # The processor publishes the result once it's stored, and the slot frees for the next execution
    results.handle_execution_completed.assert_awaited_once_with(completed)
    assert producer.produced_events == []
    scheduler.finish.assert_awaited_once_with("exec1")


async def test_non_terminal_event_records_no_lifetime(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter
) -> None:
    mapper = AsyncMock(spec=PodEventMapper)
    mapper.map_pod_event.return_value = [PodRunningEvent(execution_id="exec1", pod_name="busy", metadata=_METADATA)]
    scheduler = AsyncMock(spec=ExecutionScheduler)
    pm = make_pod_monitor(tracer, event_mapper=mapper, scheduler=scheduler)

    pod = make_pod(name="busy", phase="Running", labels={"language": "python"})
    pod.metadata.creation_timestamp = datetime.now(timezone.utc)
    await pm._process_pod_event(PodEvent(event_type=WatchEventType.MODIFIED, pod=pod))

    [attributes] = span_attributes(span_exporter, "pod_monitor.event")
    assert "pod.lifetime_seconds" not in attributes
    scheduler.finish.assert_not_awaited()


@pytest.mark.parametrize(
    ("error", "error_type"),
    [
        (ApiException(status=410), ErrorType.RESOURCE_VERSION_EXPIRED),
        (ApiException(status=500), ErrorType.API_ERROR),
        (RuntimeError("boom"), ErrorType.UNEXPECTED),
    ],
)
async def test_watch_cycle_reports_the_error_that_ended_it(
    tracer: trace.Tracer,
    span_exporter: InMemorySpanExporter,
    error: Exception,
    error_type: ErrorType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pm = make_pod_monitor(tracer)
    pm._last_resource_version = "rv-before"
    monkeypatch.setattr(pm, "watch_pod_events", AsyncMock(side_effect=error))

    await pm.watch_cycle()

    assert span_attributes(span_exporter, "pod_monitor.watch") == [{"pod_monitor.error_type": error_type}]
    expired = error_type == ErrorType.RESOURCE_VERSION_EXPIRED
    assert pm._last_resource_version == (None if expired else "rv-before")


async def test_watch_cycle_reports_no_error_when_the_watch_ends_normally(
    tracer: trace.Tracer, span_exporter: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch
) -> None:
    pm = make_pod_monitor(tracer)
    monkeypatch.setattr(pm, "watch_pod_events", AsyncMock())

    await pm.watch_cycle()

    assert span_attributes(span_exporter, "pod_monitor.watch") == [{}]
