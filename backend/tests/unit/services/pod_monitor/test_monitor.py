"""Tests for stateless PodMonitor handler."""

import asyncio
import logging
import types
from typing import Any
from unittest.mock import MagicMock

import pytest
from kubernetes import client as k8s_client

from app.core.metrics import EventMetrics, KubernetesMetrics
from app.db.repositories.pod_state_repository import PodStateRepository
from app.domain.events.typed import DomainEvent, EventMetadata, ExecutionCompletedEvent
from app.domain.events.typed import ResourceUsageDomain
from app.events.core import UnifiedProducer
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.services.pod_monitor.monitor import (
    PodEvent,
    PodMonitor,
    ReconciliationResult,
    WatchEventType,
)

from tests.unit.services.pod_monitor.conftest import (
    make_mock_v1_api,
    make_pod,
)

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.pod_monitor")


class FakeUnifiedProducer(UnifiedProducer):
    """Fake producer that captures events without Kafka."""

    def __init__(self) -> None:
        self.produced_events: list[tuple[DomainEvent, str | None]] = []
        self._logger = _test_logger

    async def produce(
            self, event_to_produce: DomainEvent, key: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        self.produced_events.append((event_to_produce, key))


class FakePodStateRepository:
    """Fake pod state repository for testing."""

    def __init__(self) -> None:
        self._tracked: set[str] = set()
        self._resource_version: str | None = None

    async def track_pod(
            self, pod_name: str, execution_id: str, status: str,
            metadata: dict[str, object] | None = None, ttl_seconds: int = 7200,
    ) -> None:
        self._tracked.add(pod_name)

    async def untrack_pod(self, pod_name: str) -> bool:
        if pod_name in self._tracked:
            self._tracked.discard(pod_name)
            return True
        return False

    async def is_pod_tracked(self, pod_name: str) -> bool:
        return pod_name in self._tracked

    async def get_tracked_pod_names(self) -> set[str]:
        return self._tracked.copy()

    async def get_tracked_pods_count(self) -> int:
        return len(self._tracked)

    async def get_resource_version(self) -> str | None:
        return self._resource_version

    async def set_resource_version(self, version: str) -> None:
        self._resource_version = version


class SpyMapper:
    """Spy event mapper that tracks clear_cache calls."""

    def __init__(self) -> None:
        self.cleared = False

    def clear_cache(self) -> None:
        self.cleared = True

    def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:  # noqa: ARG002
        return []


def make_pod_monitor(
        event_metrics: EventMetrics,
        kubernetes_metrics: KubernetesMetrics,
        config: PodMonitorConfig | None = None,
        producer: UnifiedProducer | None = None,
        pod_state_repo: PodStateRepository | None = None,
        v1_client: k8s_client.CoreV1Api | None = None,
        event_mapper: PodEventMapper | None = None,
) -> PodMonitor:
    """Create PodMonitor with sensible test defaults."""
    cfg = config or PodMonitorConfig()
    prod = producer or FakeUnifiedProducer()
    repo = pod_state_repo or FakePodStateRepository()
    v1 = v1_client or make_mock_v1_api("{}")
    mapper = event_mapper or PodEventMapper(logger=_test_logger, k8s_api=make_mock_v1_api("{}"))
    return PodMonitor(
        config=cfg,
        producer=prod,
        pod_state_repo=repo,  # type: ignore[arg-type]
        v1_client=v1,
        event_mapper=mapper,
        logger=_test_logger,
        kubernetes_metrics=kubernetes_metrics,
    )


# ===== Tests =====


@pytest.mark.asyncio
async def test_handle_raw_event_tracks_pod(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that handle_raw_event tracks new pods."""
    fake_repo = FakePodStateRepository()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, pod_state_repo=fake_repo)  # type: ignore[arg-type]

    pod = make_pod(name="test-pod", phase="Running", labels={"execution-id": "e1"}, resource_version="v1")
    raw_event = {"type": "ADDED", "object": pod}

    await pm.handle_raw_event(raw_event)

    assert "test-pod" in fake_repo._tracked


@pytest.mark.asyncio
async def test_handle_raw_event_untracks_deleted_pod(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that handle_raw_event untracks deleted pods."""
    fake_repo = FakePodStateRepository()
    fake_repo._tracked.add("test-pod")
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, pod_state_repo=fake_repo)  # type: ignore[arg-type]

    pod = make_pod(name="test-pod", phase="Succeeded", labels={"execution-id": "e1"}, resource_version="v2")
    raw_event = {"type": "DELETED", "object": pod}

    await pm.handle_raw_event(raw_event)

    assert "test-pod" not in fake_repo._tracked


@pytest.mark.asyncio
async def test_handle_raw_event_updates_resource_version(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that handle_raw_event updates resource version."""
    fake_repo = FakePodStateRepository()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, pod_state_repo=fake_repo)  # type: ignore[arg-type]

    pod = make_pod(name="test-pod", phase="Running", labels={"execution-id": "e1"}, resource_version="v123")
    raw_event = {"type": "ADDED", "object": pod}

    await pm.handle_raw_event(raw_event)

    assert fake_repo._resource_version == "v123"


@pytest.mark.asyncio
async def test_handle_raw_event_invalid_event(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that handle_raw_event handles invalid events gracefully."""
    pm = make_pod_monitor(event_metrics, kubernetes_metrics)

    # Should not raise for empty event
    await pm.handle_raw_event({})

    # Should not raise for event without object
    await pm.handle_raw_event({"type": "ADDED"})


@pytest.mark.asyncio
async def test_handle_raw_event_ignored_phase(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that handle_raw_event ignores configured phases."""
    cfg = PodMonitorConfig()
    cfg.ignored_pod_phases = ["Unknown"]
    fake_repo = FakePodStateRepository()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, pod_state_repo=fake_repo)  # type: ignore[arg-type]

    pod = make_pod(name="ignored-pod", phase="Unknown", labels={"execution-id": "e1"}, resource_version="v1")
    raw_event = {"type": "ADDED", "object": pod}

    await pm.handle_raw_event(raw_event)

    # Pod should not be tracked due to ignored phase
    assert "ignored-pod" not in fake_repo._tracked


@pytest.mark.asyncio
async def test_reconcile_state_finds_missing_pods(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that reconcile_state identifies missing pods."""
    cfg = PodMonitorConfig()
    cfg.namespace = "test"
    cfg.label_selector = "app=test"

    pod1 = make_pod(name="pod1", phase="Running", resource_version="v1")
    pod2 = make_pod(name="pod2", phase="Running", resource_version="v1")

    mock_v1 = MagicMock()
    mock_v1.list_namespaced_pod.return_value = MagicMock(items=[pod1, pod2])

    fake_repo = FakePodStateRepository()
    fake_repo._tracked.add("pod2")
    fake_repo._tracked.add("pod3")  # Extra pod not in K8s

    pm = make_pod_monitor(
        event_metrics, kubernetes_metrics, config=cfg, pod_state_repo=fake_repo, v1_client=mock_v1  # type: ignore[arg-type]
    )

    result = await pm.reconcile_state()

    assert result.success is True
    assert result.missing_pods == {"pod1"}
    assert result.extra_pods == {"pod3"}


@pytest.mark.asyncio
async def test_reconcile_state_handles_api_error(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that reconcile_state handles API errors gracefully."""
    cfg = PodMonitorConfig()

    mock_v1 = MagicMock()
    mock_v1.list_namespaced_pod.side_effect = RuntimeError("API error")

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, config=cfg, v1_client=mock_v1)

    result = await pm.reconcile_state()

    assert result.success is False
    assert result.error is not None
    assert "API error" in result.error


@pytest.mark.asyncio
async def test_publish_event(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that events are published correctly."""
    fake_producer = FakeUnifiedProducer()
    pm = make_pod_monitor(event_metrics, kubernetes_metrics, producer=fake_producer)

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
async def test_process_pod_event_publishes_mapped_events(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that _process_pod_event publishes events from mapper."""
    fake_producer = FakeUnifiedProducer()
    fake_repo = FakePodStateRepository()

    class MockMapper:
        def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:  # noqa: ARG002
            return [
                ExecutionCompletedEvent(
                    execution_id="e1",
                    aggregate_id="e1",
                    exit_code=0,
                    resource_usage=ResourceUsageDomain(),
                    metadata=EventMetadata(service_name="test", service_version="1.0"),
                )
            ]

        def clear_cache(self) -> None:
            pass

    pm = make_pod_monitor(
        event_metrics,
        kubernetes_metrics,
        producer=fake_producer,
        pod_state_repo=fake_repo,  # type: ignore[arg-type]
        event_mapper=MockMapper(),  # type: ignore[arg-type]
    )

    pod = make_pod(name="test-pod", phase="Running", labels={"execution-id": "e1"})
    event = PodEvent(event_type=WatchEventType.ADDED, pod=pod, resource_version="v1")

    await pm._process_pod_event(event)

    assert len(fake_producer.produced_events) == 1
    assert "test-pod" in fake_repo._tracked


@pytest.mark.asyncio
async def test_process_pod_event_handles_mapper_error(event_metrics: EventMetrics, kubernetes_metrics: KubernetesMetrics) -> None:
    """Test that _process_pod_event handles mapper errors gracefully."""

    class FailMapper:
        def map_pod_event(self, pod: Any, event_type: WatchEventType) -> list[Any]:
            raise RuntimeError("Mapping failed")

        def clear_cache(self) -> None:
            pass

    pm = make_pod_monitor(event_metrics, kubernetes_metrics, event_mapper=FailMapper())  # type: ignore[arg-type]

    pod = make_pod(name="fail-pod", phase="Pending")
    event = PodEvent(event_type=WatchEventType.ADDED, pod=pod, resource_version=None)

    # Should not raise - errors are caught and logged
    await pm._process_pod_event(event)
