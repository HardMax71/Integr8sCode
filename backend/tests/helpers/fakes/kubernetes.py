"""Minimal fake Kubernetes clients for DI container testing."""

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock


@dataclass
class FakeK8sApiClient:
    """Minimal fake for k8s ApiClient - satisfies DI container."""

    configuration: Any = None

    def close(self) -> None:
        pass


@dataclass
class FakeK8sCoreV1Api:
    """Minimal fake for k8s CoreV1Api - satisfies DI container."""

    api_client: FakeK8sApiClient = field(default_factory=FakeK8sApiClient)

    def read_namespaced_pod(self, name: str, namespace: str) -> Any:
        return MagicMock()

    def list_namespaced_pod(self, namespace: str, **kwargs: Any) -> Any:
        return MagicMock(items=[])

    def delete_namespaced_pod(self, name: str, namespace: str, **kwargs: Any) -> Any:
        return MagicMock()

    def read_namespaced_pod_log(self, name: str, namespace: str, **kwargs: Any) -> str:
        return ""


@dataclass
class FakeK8sAppsV1Api:
    """Minimal fake for k8s AppsV1Api - satisfies DI container."""

    api_client: FakeK8sApiClient = field(default_factory=FakeK8sApiClient)


@dataclass
class FakeK8sWatch:
    """Minimal fake for k8s Watch - satisfies DI container."""

    _events: list[dict[str, Any]] = field(default_factory=list)

    def stream(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        return iter(self._events)

    def stop(self) -> None:
        pass
