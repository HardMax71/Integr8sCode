"""Protocol definitions for test fakes.

These protocols define the interfaces that test fakes must implement,
allowing proper type checking without using `# type: ignore` comments.
"""

from asyncio import Event
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SubscriptionProtocol(Protocol):
    """Protocol for SSE subscription interface."""

    async def get(self, model: type[Any], timeout: float = 0.5) -> Any | None:
        """Get the next message from the subscription."""
        ...

    async def push(self, msg: dict[str, Any]) -> None:
        """Push a message to the subscription (for testing)."""
        ...

    async def close(self) -> None:
        """Close the subscription."""
        ...


@runtime_checkable
class SSEBusProtocol(Protocol):
    """Protocol for SSE bus interface."""

    async def open_subscription(self, execution_id: str) -> SubscriptionProtocol:
        """Open a subscription for an execution."""
        ...

    async def open_notification_subscription(self, user_id: str) -> SubscriptionProtocol:
        """Open a notification subscription for a user."""
        ...


@runtime_checkable
class ExecutionRepositoryProtocol(Protocol):
    """Protocol for execution repository interface."""

    async def get_execution_status(self, execution_id: str) -> Any:
        """Get the status of an execution."""
        ...

    async def get_execution(self, execution_id: str) -> Any | None:
        """Get an execution by ID."""
        ...


@runtime_checkable
class ShutdownManagerProtocol(Protocol):
    """Protocol for SSE shutdown manager interface."""

    async def register_connection(
        self, execution_id: str, connection_id: str
    ) -> Event | None:
        """Register a new SSE connection."""
        ...

    async def unregister_connection(
        self, execution_id: str, connection_id: str
    ) -> None:
        """Unregister an SSE connection."""
        ...

    def is_shutting_down(self) -> bool:
        """Check if shutdown has been initiated."""
        ...

    def get_shutdown_status(self) -> Any:
        """Get the current shutdown status."""
        ...


@runtime_checkable
class RouterProtocol(Protocol):
    """Protocol for SSE router interface."""

    def get_stats(self) -> dict[str, int | bool]:
        """Get router statistics."""
        ...


@runtime_checkable
class RouterWithStopProtocol(Protocol):
    """Protocol for router with stop capability."""

    async def stop(self) -> None:
        """Stop the router."""
        ...


@runtime_checkable
class RouterWithCloseProtocol(Protocol):
    """Protocol for router with aclose capability."""

    async def aclose(self) -> None:
        """Close the router."""
        ...


@runtime_checkable
class SettingsProtocol(Protocol):
    """Protocol for settings interface used by SSE service."""

    SSE_HEARTBEAT_INTERVAL: int


@runtime_checkable
class ResourceAllocationRepositoryProtocol(Protocol):
    """Protocol for resource allocation repository interface."""

    async def count_active(self, language: str) -> int:
        """Count active allocations for a language."""
        ...

    async def create_allocation(self, create_data: Any) -> Any:
        """Create a new resource allocation."""
        ...

    async def release_allocation(self, allocation_id: str) -> None:
        """Release a resource allocation."""
        ...


@runtime_checkable
class ProducerProtocol(Protocol):
    """Protocol for event producer interface."""

    async def produce(self, event: Any, key: str | None = None) -> None:
        """Produce an event."""
        ...


@runtime_checkable
class EventDispatcherProtocol(Protocol):
    """Protocol for event dispatcher interface."""

    def register_handler(self, event_type: Any, handler: Any) -> None:
        """Register a handler for an event type."""
        ...


@runtime_checkable
class K8sApiProtocol(Protocol):
    """Protocol for Kubernetes API interface."""

    def read_namespaced_pod_log(
        self, name: str, namespace: str, tail_lines: int = 10000
    ) -> str:
        """Read logs from a pod."""
        ...
