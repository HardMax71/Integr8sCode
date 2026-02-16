from __future__ import annotations

from typing import NoReturn
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.core.metrics import (
    ConnectionMetrics,
    CoordinatorMetrics,
    DatabaseMetrics,
    DLQMetrics,
    EventMetrics,
    ExecutionMetrics,
    KubernetesMetrics,
    NotificationMetrics,
    RateLimitMetrics,
    ReplayMetrics,
    SecurityMetrics,
)
from app.settings import Settings
from kubernetes_asyncio.client import (
    V1ContainerState,
    V1ContainerStateTerminated,
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1ObjectMeta,
    V1Pod,
    V1PodCondition,
    V1PodSpec,
    V1PodStatus,
)

# ===== Kubernetes test factories =====


def make_container_status(
    *,
    terminated_exit_code: int | None = None,
    terminated_reason: str | None = None,
    terminated_message: str | None = None,
    waiting_reason: str | None = None,
    waiting_message: str | None = None,
    name: str = "main",
) -> V1ContainerStatus:
    """Create a V1ContainerStatus with the specified state."""
    state = V1ContainerState()
    if terminated_exit_code is not None:
        state.terminated = V1ContainerStateTerminated(
            exit_code=terminated_exit_code,
            reason=terminated_reason,
            message=terminated_message,
        )
    if waiting_reason is not None:
        state.waiting = V1ContainerStateWaiting(reason=waiting_reason, message=waiting_message)
    return V1ContainerStatus(
        name=name,
        ready=False,
        restart_count=0,
        image="test:latest",
        image_id="",
        state=state,
    )


def make_pod(
    *,
    name: str,
    phase: str,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
    container_statuses: list[V1ContainerStatus] | None = None,
    term_exit: int | None = None,
    waiting_reason: str | None = None,
    waiting_message: str | None = None,
    namespace: str = "integr8scode",
    active_deadline_seconds: int | None = None,
    node_name: str | None = None,
    resource_version: str | None = None,
    reason: str | None = None,
    message: str | None = None,
    conditions: list[V1PodCondition] | None = None,
) -> V1Pod:
    """Create a test V1Pod with sensible defaults."""
    cs: list[V1ContainerStatus] = list(container_statuses) if container_statuses else []

    if waiting_reason is not None:
        cs.append(make_container_status(waiting_reason=waiting_reason, waiting_message=waiting_message))

    if term_exit is not None:
        cs.append(make_container_status(terminated_exit_code=term_exit))

    return V1Pod(
        metadata=V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels=labels or {},
            annotations=annotations or {},
            resource_version=resource_version,
        ),
        spec=V1PodSpec(
            containers=[],
            active_deadline_seconds=active_deadline_seconds,
            node_name=node_name,
        ),
        status=V1PodStatus(
            phase=phase,
            reason=reason,
            message=message,
            container_statuses=cs if cs else None,
            conditions=conditions,
        ),
    )


# ===== K8s Watch stream helpers =====


class MockWatchStream:
    """Mock watch stream that yields events from a list."""

    def __init__(self, events: list[dict[str, V1Pod | str]], resource_version: str) -> None:
        self._events = events
        self.resource_version = resource_version
        self._index = 0

    def __aiter__(self) -> MockWatchStream:
        return self

    async def __anext__(self) -> dict[str, V1Pod | str]:
        if self._index >= len(self._events):
            raise StopAsyncIteration
        event = self._events[self._index]
        self._index += 1
        return event


def make_mock_watch(
    events: list[dict[str, V1Pod | str]], resource_version: str = "rv2"
) -> MagicMock:
    """Create a mock Watch that returns the given events."""
    stream = MockWatchStream(events, resource_version)
    mock = MagicMock()
    mock.stream.return_value = stream
    mock.stop.return_value = None
    mock.close = AsyncMock()
    mock.resource_version = resource_version
    return mock


def make_mock_v1_api(
    logs: str = "{}", pods: list[V1Pod] | None = None, list_resource_version: str = "list-rv1",
) -> MagicMock:
    """Create a mock CoreV1Api with configurable responses."""

    class PodList:
        def __init__(self, items: list[V1Pod], resource_version: str) -> None:
            self.items = items
            self.metadata = V1ObjectMeta(resource_version=resource_version)

    mock = MagicMock()
    mock.read_namespaced_pod_log = AsyncMock(return_value=logs)
    mock.get_api_resources = AsyncMock(return_value=None)
    mock.list_namespaced_pod = AsyncMock(return_value=PodList(list(pods or []), list_resource_version))
    return mock


# ===== K8s fixtures =====


@pytest.fixture
def mock_pod() -> V1Pod:
    """Basic mock pod for tests."""
    return make_pod(name="test-pod", phase="Running", labels={"execution-id": "test-exec-1"})


@pytest.fixture
def mock_v1_api() -> MagicMock:
    """Mock CoreV1Api for tests."""
    return make_mock_v1_api()


@pytest.fixture
def mock_watch() -> MagicMock:
    """Mock Watch for tests."""
    return make_mock_watch([])


# ===== Metrics fixtures =====


@pytest.fixture
def connection_metrics(test_settings: Settings) -> ConnectionMetrics:
    return ConnectionMetrics(test_settings)


@pytest.fixture
def coordinator_metrics(test_settings: Settings) -> CoordinatorMetrics:
    return CoordinatorMetrics(test_settings)


@pytest.fixture
def database_metrics(test_settings: Settings) -> DatabaseMetrics:
    return DatabaseMetrics(test_settings)


@pytest.fixture
def dlq_metrics(test_settings: Settings) -> DLQMetrics:
    return DLQMetrics(test_settings)


@pytest.fixture
def event_metrics(test_settings: Settings) -> EventMetrics:
    return EventMetrics(test_settings)


@pytest.fixture
def execution_metrics(test_settings: Settings) -> ExecutionMetrics:
    return ExecutionMetrics(test_settings)


@pytest.fixture
def kubernetes_metrics(test_settings: Settings) -> KubernetesMetrics:
    return KubernetesMetrics(test_settings)


@pytest.fixture
def notification_metrics(test_settings: Settings) -> NotificationMetrics:
    return NotificationMetrics(test_settings)


@pytest.fixture
def rate_limit_metrics(test_settings: Settings) -> RateLimitMetrics:
    return RateLimitMetrics(test_settings)


@pytest.fixture
def replay_metrics(test_settings: Settings) -> ReplayMetrics:
    return ReplayMetrics(test_settings)


@pytest.fixture
def security_metrics(test_settings: Settings) -> SecurityMetrics:
    return SecurityMetrics(test_settings)


# ===== Guard fixtures =====


@pytest.fixture
def db() -> NoReturn:
    raise RuntimeError("Unit tests should not access DB - use mocks or move to integration/")


@pytest.fixture
def redis_client() -> NoReturn:
    raise RuntimeError("Unit tests should not access Redis - use mocks or move to integration/")


@pytest.fixture
def client() -> NoReturn:
    raise RuntimeError("Unit tests should not use HTTP client - use mocks or move to integration/")


@pytest.fixture
def app() -> NoReturn:
    raise RuntimeError("Unit tests should not use full app - use mocks or move to integration/")
