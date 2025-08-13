"""SSE Connection Draining Manager for graceful shutdown"""

import asyncio
import json
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Set

from app.core.logging import logger
from app.core.metrics import SSE_DRAINING_CONNECTIONS, SSE_MESSAGES_SENT, SSE_SHUTDOWN_DURATION


class ShutdownPhase(Enum):
    """Phases of SSE shutdown process"""
    READY = "ready"
    DRAINING = "draining"
    NOTIFYING = "notifying"
    CLOSING = "closing"
    COMPLETE = "complete"


class SSEShutdownManager:
    """
    Manages graceful shutdown of SSE connections.

    Features:
    - Phased shutdown process
    - Connection notification before closing
    - Configurable grace periods
    - Progress tracking and metrics
    - Force close after timeout
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

        self._phase = ShutdownPhase.READY
        self._shutdown_initiated = False
        self._shutdown_complete = False
        self._shutdown_start_time: Optional[float] = None

        # Connection tracking
        self._active_connections: Dict[str, Set[str]] = {}  # execution_id -> connection_ids
        self._connection_generators: Dict[str, Any] = {}  # connection_id -> generator
        self._draining_connections: Set[str] = set()
        self._notified_connections: Set[str] = set()

        # Synchronization
        self._lock = asyncio.Lock()
        self._shutdown_event = asyncio.Event()
        self._drain_complete_event = asyncio.Event()

        logger.info(
            f"SSEShutdownManager initialized: "
            f"drain_timeout={drain_timeout}s, "
            f"notification_timeout={notification_timeout}s, "
            f"force_close_timeout={force_close_timeout}s"
        )

    async def register_connection(
        self,
        execution_id: str,
        connection_id: str,
        generator: Any
    ) -> bool:
        """
        Register a new SSE connection.

        Returns:
            False if shutdown is in progress and new connections should be rejected
        """
        async with self._lock:
            if self._shutdown_initiated:
                logger.warning(
                    f"Rejecting new SSE connection during shutdown: "
                    f"execution_id={execution_id}, connection_id={connection_id}"
                )
                return False

            if execution_id not in self._active_connections:
                self._active_connections[execution_id] = set()

            self._active_connections[execution_id].add(connection_id)
            self._connection_generators[connection_id] = generator

            logger.debug(f"Registered SSE connection: {connection_id}")
            return True

    async def unregister_connection(self, execution_id: str, connection_id: str) -> None:
        """Unregister an SSE connection"""
        async with self._lock:
            if execution_id in self._active_connections:
                self._active_connections[execution_id].discard(connection_id)
                if not self._active_connections[execution_id]:
                    del self._active_connections[execution_id]

            self._connection_generators.pop(connection_id, None)
            self._draining_connections.discard(connection_id)
            self._notified_connections.discard(connection_id)

            logger.debug(f"Unregistered SSE connection: {connection_id}")

            # Check if all connections are drained
            if self._shutdown_initiated and not self._connection_generators:
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

            SSE_DRAINING_CONNECTIONS.labels(phase="total").set(total_connections)

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
        SSE_SHUTDOWN_DURATION.labels(phase="notify").set(time.time() - phase_start)

        # Phase 3: Drain connections gracefully
        phase_start = time.time()
        await self._drain_connections()
        SSE_SHUTDOWN_DURATION.labels(phase="drain").set(time.time() - phase_start)

        # Phase 4: Force close remaining connections
        phase_start = time.time()
        await self._force_close_connections()
        SSE_SHUTDOWN_DURATION.labels(phase="force_close").set(time.time() - phase_start)

        # Total shutdown duration
        if self._shutdown_start_time is not None:
            total_duration = time.time() - self._shutdown_start_time
            SSE_SHUTDOWN_DURATION.labels(phase="total").set(total_duration)
            logger.info(f"SSE shutdown complete in {total_duration:.2f}s")
        else:
            logger.info("SSE shutdown complete")

    async def _notify_connections(self) -> None:
        """Send shutdown notification to all active connections"""
        self._phase = ShutdownPhase.NOTIFYING

        async with self._lock:
            all_connections = list(self._connection_generators.keys())
            self._draining_connections = set(all_connections)

        logger.info(f"Phase 2: Notifying {len(all_connections)} connections about shutdown")
        SSE_DRAINING_CONNECTIONS.labels(phase="notifying").set(len(all_connections))

        # Send shutdown notification event
        shutdown_event = {
            "event": "shutdown",
            "data": json.dumps({
                "message": "Server is shutting down",
                "grace_period": self.drain_timeout,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
        }

        # Notify all connections concurrently
        tasks = []
        for conn_id in all_connections:
            generator = self._connection_generators.get(conn_id)
            if generator:
                task = asyncio.create_task(self._send_shutdown_event(conn_id, generator, shutdown_event))
                tasks.append(task)

        if tasks:
            # Wait for notifications with timeout
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=self.notification_timeout
                )
            except asyncio.TimeoutError:
                logger.warning(f"Shutdown notification timeout after {self.notification_timeout}s")

        notified_count = len(self._notified_connections)
        logger.info(f"Notified {notified_count}/{len(all_connections)} connections")

    async def _send_shutdown_event(self, connection_id: str, generator: Any, event: Dict[str, Any]) -> None:
        """Send shutdown event to a specific connection"""
        try:
            # Try to send the event through the generator's queue if available
            if hasattr(generator, 'send'):
                await generator.send(event)
            elif hasattr(generator, 'queue') and hasattr(generator.queue, 'put'):
                await generator.queue.put(event)

            self._notified_connections.add(connection_id)
            SSE_MESSAGES_SENT.labels(endpoint="executions", event_type="shutdown").inc()

        except Exception as e:
            logger.warning(f"Failed to notify connection {connection_id}: {e}")

    async def _drain_connections(self) -> None:
        """Wait for connections to close gracefully"""
        self._phase = ShutdownPhase.DRAINING

        remaining = len(self._connection_generators)
        logger.info(f"Phase 3: Draining {remaining} connections (timeout: {self.drain_timeout}s)")
        SSE_DRAINING_CONNECTIONS.labels(phase="draining").set(remaining)

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
                remaining = len(self._connection_generators)

            if remaining < last_count:
                logger.info(f"Connections remaining: {remaining}")
                SSE_DRAINING_CONNECTIONS.labels(phase="draining").set(remaining)
                last_count = remaining

        if remaining == 0:
            logger.info("All connections drained gracefully")
        else:
            logger.warning(f"{remaining} connections still active after drain timeout")

    async def _force_close_connections(self) -> None:
        """Force close any remaining connections"""
        self._phase = ShutdownPhase.CLOSING

        async with self._lock:
            remaining_connections = list(self._connection_generators.keys())

        if not remaining_connections:
            logger.info("Phase 4: No connections to force close")
            return

        logger.warning(f"Phase 4: Force closing {len(remaining_connections)} connections")
        SSE_DRAINING_CONNECTIONS.labels(phase="force_closing").set(len(remaining_connections))

        # Cancel all remaining generators
        for conn_id in remaining_connections:
            try:
                generator = self._connection_generators.get(conn_id)
                if generator and hasattr(generator, 'aclose'):
                    await generator.aclose()
                elif generator and hasattr(generator, 'cancel'):
                    generator.cancel()

                # Clean up tracking
                await self._cleanup_connection(conn_id)

            except Exception as e:
                logger.error(f"Error force closing connection {conn_id}: {e}")

        # Final cleanup
        async with self._lock:
            self._active_connections.clear()
            self._connection_generators.clear()
            self._draining_connections.clear()

        SSE_DRAINING_CONNECTIONS.labels(phase="force_closing").set(0)

    async def _cleanup_connection(self, connection_id: str) -> None:
        """Clean up connection tracking"""
        # Find and remove from active connections
        for exec_id, conn_ids in list(self._active_connections.items()):
            if connection_id in conn_ids:
                await self.unregister_connection(exec_id, connection_id)
                break

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
            "notified_connections": len(self._notified_connections)
        }

        if self._shutdown_start_time:
            status["duration"] = time.time() - self._shutdown_start_time

        return status

    async def wait_for_shutdown(self, timeout: Optional[float] = None) -> bool:
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


class SSEShutdownManagerSingleton:
    """Singleton wrapper for SSEShutdownManager"""
    _instance: Optional[SSEShutdownManager] = None

    @classmethod
    def get_instance(cls) -> SSEShutdownManager:
        if cls._instance is None:
            cls._instance = SSEShutdownManager()
        return cls._instance

    @classmethod
    async def reset_instance(cls) -> None:
        if cls._instance and cls._instance.is_shutting_down():
            await cls._instance.wait_for_shutdown()
        cls._instance = None


def get_sse_shutdown_manager() -> SSEShutdownManager:
    """Get SSE shutdown manager instance"""
    return SSEShutdownManagerSingleton.get_instance()


async def reset_sse_shutdown_manager() -> None:
    """Reset SSE shutdown manager (for testing)"""
    await SSEShutdownManagerSingleton.reset_instance()
