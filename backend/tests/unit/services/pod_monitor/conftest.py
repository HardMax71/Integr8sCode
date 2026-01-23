from __future__ import annotations

from typing import Any, Iterable


# ===== Pod data model stubs =====
# These create test data, not "fakes" - they're test data factories


class Meta:
    def __init__(
        self,
        name: str,
        namespace: str = "integr8scode",
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
        resource_version: str | None = None,
    ) -> None:
        self.name = name
        self.namespace = namespace
        self.labels = labels or {}
        self.annotations = annotations or {}
        self.resource_version = resource_version


class Spec:
    def __init__(self, active_deadline_seconds: int | None = None, node_name: str | None = None) -> None:
        self.active_deadline_seconds = active_deadline_seconds
        self.node_name = node_name


class Terminated:
    def __init__(self, exit_code: int, reason: str | None = None, message: str | None = None) -> None:
        self.exit_code = exit_code
        self.reason = reason
        self.message = message


class Waiting:
    def __init__(self, reason: str, message: str | None = None) -> None:
        self.reason = reason
        self.message = message


class State:
    def __init__(
        self,
        terminated: Terminated | None = None,
        waiting: Waiting | None = None,
        running: Any | None = None,
    ) -> None:
        self.terminated = terminated
        self.waiting = waiting
        self.running = running


class ContainerStatus:
    def __init__(self, state: State | None, name: str = "c", ready: bool = True, restart_count: int = 0) -> None:
        self.state = state
        self.name = name
        self.ready = ready
        self.restart_count = restart_count


class Status:
    def __init__(
        self,
        phase: str | None,
        reason: str | None = None,
        message: str | None = None,
        cs: Iterable[ContainerStatus] | None = None,
        conditions: list[Any] | None = None,
    ) -> None:
        self.phase = phase
        self.reason = reason
        self.message = message
        self.container_statuses = list(cs or [])
        self.conditions = conditions


class Pod:
    def __init__(
        self,
        name: str,
        phase: str,
        cs: Iterable[ContainerStatus] | None = None,
        reason: str | None = None,
        msg: str | None = None,
        adl: int | None = None,
        namespace: str = "integr8scode",
        labels: dict[str, str] | None = None,
        annotations: dict[str, str] | None = None,
        resource_version: str | None = None,
    ) -> None:
        self.metadata = Meta(
            name,
            namespace=namespace,
            labels=labels,
            annotations=annotations,
            resource_version=resource_version,
        )
        self.status = Status(phase, reason, msg, cs)
        self.spec = Spec(adl)


# ===== Factory functions =====


def make_pod(
    *,
    name: str,
    phase: str,
    labels: dict[str, str] | None = None,
    annotations: dict[str, str] | None = None,
    term_exit: int | None = None,
    waiting_reason: str | None = None,
    waiting_message: str | None = None,
    namespace: str = "integr8scode",
    active_deadline_seconds: int | None = None,
    node_name: str | None = None,
    resource_version: str | None = None,
) -> Pod:
    """Create a test Pod with sensible defaults."""
    cs: list[ContainerStatus] = []
    if waiting_reason is not None:
        cs.append(ContainerStatus(State(waiting=Waiting(waiting_reason, waiting_message))))
    if term_exit is not None:
        cs.append(ContainerStatus(State(terminated=Terminated(term_exit))))
    pod = Pod(
        name=name,
        phase=phase,
        cs=cs,
        namespace=namespace,
        labels=labels,
        annotations=annotations,
        resource_version=resource_version,
    )
    pod.spec.node_name = node_name
    pod.spec.active_deadline_seconds = active_deadline_seconds
    return pod


# ===== Watch stream helpers =====


class StopEvent:
    """Stop event for watch stream - holds resource_version."""

    def __init__(self, resource_version: str) -> None:
        self.resource_version = resource_version


class MockWatchStream:
    """Mock watch stream that yields events from a list.

    The real kubernetes watch stream has a _stop_event attribute that
    holds the resource_version for use by _update_resource_version.
    """

    def __init__(self, events: list[dict[str, Any]], resource_version: str) -> None:
        self._events = events
        self._stop_event = StopEvent(resource_version)
        self._index = 0

    def __iter__(self) -> "MockWatchStream":
        return self

    def __next__(self) -> dict[str, Any]:
        if self._index >= len(self._events):
            raise StopIteration
        event = self._events[self._index]
        self._index += 1
        return event


def make_mock_watch(events: list[dict[str, Any]], resource_version: str = "rv2") -> Any:
    """Create a mock Watch that returns the given events.

    Usage:
        mock_watch = make_mock_watch([{"type": "MODIFIED", "object": pod}])
        mock_watch.stream.return_value = MockWatchStream(events, "rv2")
    """
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.stream.return_value = MockWatchStream(events, resource_version)
    mock.stop.return_value = None
    return mock


def make_mock_v1_api(logs: str = "{}", pods: list[Pod] | None = None) -> Any:
    """Create a mock CoreV1Api with configurable responses.

    Usage:
        mock_api = make_mock_v1_api(logs='{"stdout":"ok","stderr":"","exit_code":0}')
    """
    from unittest.mock import MagicMock

    mock = MagicMock()
    mock.read_namespaced_pod_log.return_value = logs
    mock.get_api_resources.return_value = None

    class PodList:
        def __init__(self, items: list[Pod]) -> None:
            self.items = items

    mock.list_namespaced_pod.return_value = PodList(list(pods or []))
    return mock
