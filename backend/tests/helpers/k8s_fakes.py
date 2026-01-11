"""Lightweight K8s pod/watch stubs for unit tests.

These provide only the attributes PodEventMapper/PodMonitor touch, keeping
tests fast and self-contained without importing heavy Kubernetes models.
"""

from __future__ import annotations

from typing import Any, Iterable


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


class FakeApi:
    def __init__(self, logs: str) -> None:
        self._logs = logs

    def read_namespaced_pod_log(self, name: str, namespace: str, tail_lines: int = 10000) -> str:  # noqa: ARG002
        return self._logs


class StopEvent:
    """Fake stop event for FakeWatch - holds resource_version."""

    def __init__(self, resource_version: str) -> None:
        self.resource_version = resource_version


class FakeWatchStream:
    """Fake watch stream object returned by FakeWatch.stream().

    The real kubernetes watch stream has a _stop_event attribute that
    holds the resource_version for use by _update_resource_version.
    """

    def __init__(self, events: list[dict[str, Any]], resource_version: str) -> None:
        self._events = events
        self._stop_event = StopEvent(resource_version)
        self._index = 0

    def __iter__(self) -> "FakeWatchStream":
        return self

    def __next__(self) -> dict[str, Any]:
        if self._index >= len(self._events):
            raise StopIteration
        event = self._events[self._index]
        self._index += 1
        return event


class FakeWatch:
    """Fake kubernetes Watch for testing."""

    def __init__(self, events: list[dict[str, Any]], resource_version: str) -> None:
        self._events = events
        self._rv = resource_version

    def stream(
        self, func: Any, **kwargs: Any  # noqa: ARG002
    ) -> FakeWatchStream:
        return FakeWatchStream(self._events, self._rv)

    def stop(self) -> None:
        return None


def make_watch(events: list[dict[str, Any]], resource_version: str = "rv2") -> FakeWatch:
    return FakeWatch(events, resource_version)


class FakeV1Api:
    """Fake CoreV1Api for testing PodMonitor."""

    def __init__(self, logs: str = "{}", pods: list[Pod] | None = None) -> None:
        self._logs = logs
        self._pods = pods or []

    def read_namespaced_pod_log(self, name: str, namespace: str, tail_lines: int = 10000) -> str:  # noqa: ARG002
        return self._logs

    def get_api_resources(self) -> None:
        """Stub for connectivity check."""
        return None

    def list_namespaced_pod(self, namespace: str, label_selector: str) -> Any:  # noqa: ARG002
        """Return configured pods for reconciliation tests."""

        class PodList:
            def __init__(self, items: list[Pod]) -> None:
                self.items = items

        return PodList(list(self._pods))


def make_k8s_clients(
    logs: str = "{}",
    events: list[dict[str, Any]] | None = None,
    resource_version: str = "rv1",
    pods: list[Pod] | None = None,
) -> tuple[FakeV1Api, FakeWatch]:
    """Create fake K8s clients for testing.

    Returns (v1_api, watch) tuple for pure DI into PodMonitor.
    """
    v1 = FakeV1Api(logs=logs, pods=pods)
    watch = make_watch(events or [], resource_version)
    return v1, watch

