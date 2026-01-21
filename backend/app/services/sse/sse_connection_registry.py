import asyncio
import logging
from typing import Dict, Set

from app.core.metrics import ConnectionMetrics


class SSEConnectionRegistry:
    """
    Tracks active SSE connections.

    Simple registry for connection tracking and metrics.
    Shutdown is handled via task cancellation, not explicit shutdown orchestration.
    """

    def __init__(
        self,
        logger: logging.Logger,
        connection_metrics: ConnectionMetrics,
    ):
        self.logger = logger
        self.metrics = connection_metrics

        # Track active connections by execution
        self._active_connections: Dict[str, Set[str]] = {}  # execution_id -> connection_ids
        self._lock = asyncio.Lock()

        self.logger.info("SSEConnectionRegistry initialized")

    async def register_connection(self, execution_id: str, connection_id: str) -> None:
        """Register a new SSE connection."""
        async with self._lock:
            if execution_id not in self._active_connections:
                self._active_connections[execution_id] = set()

            self._active_connections[execution_id].add(connection_id)
            self.logger.debug("Registered SSE connection", extra={"connection_id": connection_id})
            self.metrics.increment_sse_connections("executions")

    async def unregister_connection(self, execution_id: str, connection_id: str) -> None:
        """Unregister an SSE connection."""
        async with self._lock:
            connections = self._active_connections.get(execution_id)
            if connections is None or connection_id not in connections:
                return

            connections.remove(connection_id)
            if not connections:
                del self._active_connections[execution_id]

            self.logger.debug("Unregistered SSE connection", extra={"connection_id": connection_id})
            self.metrics.decrement_sse_connections("executions")

    def get_connection_count(self) -> int:
        """Get total number of active connections."""
        return sum(len(conns) for conns in self._active_connections.values())

    def get_execution_count(self) -> int:
        """Get number of executions with active connections."""
        return len(self._active_connections)
