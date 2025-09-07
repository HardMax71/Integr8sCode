import asyncio
import time
from enum import Enum
from typing import Any, Dict, Set

from app.core.logging import logger
from app.core.metrics.context import get_connection_metrics
from app.services.sse.partitioned_event_router import PartitionedSSERouter


class ShutdownPhase(Enum):
    """Phases of SSE shutdown process"""
    READY = "ready"
    NOTIFYING = "notifying"  # Notify connections of impending shutdown
    DRAINING = "draining"  # Wait for connections to close gracefully
    CLOSING = "closing"  # Force close remaining connections
    COMPLETE = "complete"


class SSEShutdownManager:
    """
    Manages graceful shutdown of SSE connections.
    
    Works alongside PartitionedSSERouter to:
    - Track active SSE connections
    - Notify clients about shutdown
    - Coordinate graceful disconnection
    - Ensure clean resource cleanup
    
    The router handles Kafka consumer shutdown while this
    manager handles SSE client connection lifecycle.
    """

    def __init__(
            self,
            drain_timeout: float = 30.0,
            notification_timeout: float = 5.0,
            force_close_timeout: float = 10.0
    ):
        self.drain_timeout = drain_timeout
        self.notification_timeout = notification_timeout
        self.force_close_timeout = force_close_timeout
        self.metrics = get_connection_metrics()

        self._phase = ShutdownPhase.READY
        self._shutdown_initiated = False
        self._shutdown_complete = False
        self._shutdown_start_time: float | None = None

        # Track active connections by execution
        self._active_connections: Dict[str, Set[str]] = {}  # execution_id -> connection_ids
        self._connection_callbacks: Dict[str, asyncio.Event] = {}  # connection_id -> shutdown event
        self._draining_connections: Set[str] = set()

        # Router reference (set during initialization)
        self._router: PartitionedSSERouter | None = None

        # Synchronization
        self._lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._drain_complete_event = asyncio.Event()

        logger.info(
            f"SSEShutdownManager initialized: "
            f"drain_timeout={drain_timeout}s, "
            f"notification_timeout={notification_timeout}s"
        )

    def set_router(self, router: "PartitionedSSERouter") -> None:
        """Set the router reference for shutdown coordination."""
        self._router = router

    async def register_connection(
            self,
            execution_id: str,
            connection_id: str
    ) -> asyncio.Event | None:
        """
        Register a new SSE connection.

        Returns:
            Shutdown event for the connection to monitor, or None if rejected
        """
        async with self._lock:
            if self._shutdown_initiated:
                logger.warning(
                    f"Rejecting new SSE connection during shutdown: "
                    f"execution_id={execution_id}, connection_id={connection_id}"
                )
                return None

            if execution_id not in self._active_connections:
                self._active_connections[execution_id] = set()

            self._active_connections[execution_id].add(connection_id)

            # Create shutdown event for this connection
            shutdown_event = asyncio.Event()
            self._connection_callbacks[connection_id] = shutdown_event

            logger.debug(f"Registered SSE connection: {connection_id}")
            self.metrics.increment_sse_connections("executions")

            return shutdown_event

    async def unregister_connection(self, execution_id: str, connection_id: str) -> None:
        """Unregister an SSE connection"""
        async with self._lock:
            if execution_id in self._active_connections:
                self._active_connections[execution_id].discard(connection_id)
                if not self._active_connections[execution_id]:
                    del self._active_connections[execution_id]

            self._connection_callbacks.pop(connection_id, None)
            self._draining_connections.discard(connection_id)

            logger.debug(f"Unregistered SSE connection: {connection_id}")
            self.metrics.decrement_sse_connections("executions")

            # Check if all connections are drained
            if self._shutdown_initiated and not self._active_connections:
                self._drain_complete_event.set()

    async def initiate_shutdown(self) -> None:
        """Initiate graceful shutdown of all SSE connections"""
        async with self._lock:
            if self._shutdown_initiated:
                logger.warning("SSE shutdown already initiated")
                return

            self._shutdown_initiated = True
            self._shutdown_start_time = time.time()
            self._phase = ShutdownPhase.DRAINING

            total_connections = sum(len(conns) for conns in self._active_connections.values())
            logger.info(f"Initiating SSE shutdown with {total_connections} active connections")

            self.metrics.update_sse_draining_connections(total_connections)

        # Start shutdown process
        self._shutdown_event.set()

        # Execute shutdown phases
        try:
            await self._execute_shutdown()
        except Exception as e:
            logger.error(f"Error during SSE shutdown: {e}")
            raise
        finally:
            self._shutdown_complete = True
            self._phase = ShutdownPhase.COMPLETE

    async def _execute_shutdown(self) -> None:
        """Execute the shutdown process in phases"""

        # Phase 1: Stop accepting new connections (already done by setting _shutdown_initiated)
        phase_start = time.time()
        logger.info("Phase 1: Stopped accepting new SSE connections")

        # Phase 2: Notify connections about shutdown
        await self._notify_connections()
        self.metrics.update_sse_shutdown_duration(time.time() - phase_start, "notify")

        # Phase 3: Drain connections gracefully
        phase_start = time.time()
        await self._drain_connections()
        self.metrics.update_sse_shutdown_duration(time.time() - phase_start, "drain")

        # Phase 4: Force close remaining connections
        phase_start = time.time()
        await self._force_close_connections()
        self.metrics.update_sse_shutdown_duration(time.time() - phase_start, "force_close")

        # Total shutdown duration
        if self._shutdown_start_time is not None:
            total_duration = time.time() - self._shutdown_start_time
            self.metrics.update_sse_shutdown_duration(total_duration, "total")
            logger.info(f"SSE shutdown complete in {total_duration:.2f}s")
        else:
            logger.info("SSE shutdown complete")

    async def _notify_connections(self) -> None:
        """Notify all active connections about shutdown"""
        self._phase = ShutdownPhase.NOTIFYING

        async with self._lock:
            active_count = sum(len(conns) for conns in self._active_connections.values())
            connection_events = list(self._connection_callbacks.values())
            self._draining_connections = set(self._connection_callbacks.keys())

        logger.info(f"Phase 2: Notifying {active_count} connections about shutdown")
        self.metrics.update_sse_draining_connections(active_count)

        # Trigger shutdown events for all connections
        # The connections will see this and send shutdown message to clients
        for event in connection_events:
            event.set()

        # Give connections time to send shutdown messages
        await asyncio.sleep(self.notification_timeout)

        logger.info("Shutdown notification phase complete")

    async def _drain_connections(self) -> None:
        """Wait for connections to close gracefully"""
        self._phase = ShutdownPhase.DRAINING

        async with self._lock:
            remaining = sum(len(conns) for conns in self._active_connections.values())

        logger.info(f"Phase 3: Draining {remaining} connections (timeout: {self.drain_timeout}s)")
        self.metrics.update_sse_draining_connections(remaining)

        start_time = time.time()
        check_interval = 0.5
        last_count = remaining

        while remaining > 0 and (time.time() - start_time) < self.drain_timeout:
            # Wait for connections to close
            try:
                await asyncio.wait_for(
                    self._drain_complete_event.wait(),
                    timeout=check_interval
                )
                break  # All connections drained
            except asyncio.TimeoutError:
                pass

            # Update metrics
            async with self._lock:
                remaining = sum(len(conns) for conns in self._active_connections.values())

            if remaining < last_count:
                logger.info(f"Connections remaining: {remaining}")
                self.metrics.update_sse_draining_connections(remaining)
                last_count = remaining

        if remaining == 0:
            logger.info("All connections drained gracefully")
        else:
            logger.warning(f"{remaining} connections still active after drain timeout")

    async def _force_close_connections(self) -> None:
        """Force close any remaining connections"""
        self._phase = ShutdownPhase.CLOSING

        async with self._lock:
            remaining_count = sum(len(conns) for conns in self._active_connections.values())

            if remaining_count == 0:
                logger.info("Phase 4: No connections to force close")
                return

            logger.warning(f"Phase 4: Force closing {remaining_count} connections")
            self.metrics.update_sse_draining_connections(remaining_count)

            # Clear all tracking - connections will be forcibly terminated
            self._active_connections.clear()
            self._connection_callbacks.clear()
            self._draining_connections.clear()

        # If we have a router, tell it to stop accepting new subscriptions
        if self._router:
            await self._router.stop()

        self.metrics.update_sse_draining_connections(0)
        logger.info("Force close phase complete")

    def is_shutting_down(self) -> bool:
        """Check if shutdown is in progress"""
        return self._shutdown_initiated

    def get_shutdown_status(self) -> Dict[str, Any]:
        """Get current shutdown status"""
        status: Dict[str, Any] = {
            "phase": self._phase.value,
            "initiated": self._shutdown_initiated,
            "complete": self._shutdown_complete,
            "active_connections": sum(len(conns) for conns in self._active_connections.values()),
            "draining_connections": len(self._draining_connections),
        }

        if self._shutdown_start_time:
            status["duration"] = time.time() - self._shutdown_start_time

        return status

    async def wait_for_shutdown(self, timeout: float | None = None) -> bool:
        """
        Wait for shutdown to complete.

        Returns:
            True if shutdown completed, False if timeout
        """
        if not self._shutdown_initiated:
            return True

        try:
            await asyncio.wait_for(
                self._wait_for_complete(),
                timeout=timeout
            )
            return True
        except asyncio.TimeoutError:
            return False

    async def _wait_for_complete(self) -> None:
        """Wait for shutdown to complete"""
        while not self._shutdown_complete:
            await asyncio.sleep(0.1)


def create_sse_shutdown_manager(
        drain_timeout: float = 30.0,
        notification_timeout: float = 5.0,
        force_close_timeout: float = 10.0
) -> SSEShutdownManager:
    """Factory function to create an SSE shutdown manager.
    
    Args:
        drain_timeout: Time to wait for connections to close gracefully
        notification_timeout: Time to wait for shutdown notifications to be sent
        force_close_timeout: Time before force closing connections
        
    Returns:
        A new SSE shutdown manager instance
    """
    return SSEShutdownManager(
        drain_timeout=drain_timeout,
        notification_timeout=notification_timeout,
        force_close_timeout=force_close_timeout
    )
