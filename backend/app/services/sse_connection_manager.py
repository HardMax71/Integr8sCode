"""SSE Connection Manager for handling Server-Sent Events connections."""
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import HTTPException

from app.config import get_settings
from app.core.logging import logger
from app.core.metrics import SSE_ACTIVE_CONNECTIONS, SSE_CONNECTION_DURATION
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.sse_shutdown_manager import SSEShutdownManager


class SSEConnectionManager:
    """Manages SSE connections and Kafka consumers for execution events."""

    def __init__(
        self,
        schema_registry_manager: SchemaRegistryManager | None = None,
        shutdown_manager: SSEShutdownManager | None = None
    ) -> None:
        """Initialize the SSE connection manager."""
        self.active_connections: Dict[str, Dict[str, Any]] = {}
        self._connection_id_counter: int = 0
        self._async_lock: asyncio.Lock = asyncio.Lock()
        self.settings = get_settings()
        self.max_connections_per_user: int = 5
        self._shutdown_manager = shutdown_manager
        self._consumers: Dict[str, UnifiedConsumer] = {}
        self._schema_registry_manager = schema_registry_manager

    async def add_connection(
        self,
        execution_id: str,
        user_id: str,
        connection_id: str
    ) -> None:
        """Add a new SSE connection.
        
        Args:
            execution_id: ID of the execution to track
            user_id: ID of the user making the connection
            connection_id: Unique connection identifier
            
        Raises:
            HTTPException: If user exceeds max connections
        """
        async with self._async_lock:
            if execution_id not in self.active_connections:
                self.active_connections[execution_id] = {}

            user_connections = sum(
                1 for conn in self.active_connections[execution_id].values()
                if conn.get("user_id") == user_id
            )

            if user_connections >= self.max_connections_per_user:
                raise HTTPException(
                    status_code=429,
                    detail=f"Maximum {self.max_connections_per_user} connections per user exceeded"
                )

            self.active_connections[execution_id][connection_id] = {
                "user_id": user_id,
                "connected_at": datetime.now(timezone.utc),
                "last_heartbeat": datetime.now(timezone.utc)
            }

            SSE_ACTIVE_CONNECTIONS.labels(
                endpoint="executions"
            ).inc()

            logger.info(
                f"SSE connection established: execution_id={execution_id}, "
                f"user_id={user_id}, connection_id={connection_id}"
            )

    async def remove_connection(
        self,
        execution_id: str,
        connection_id: str
    ) -> None:
        """Remove an SSE connection.
        
        Args:
            execution_id: ID of the execution
            connection_id: Connection identifier to remove
        """
        async with self._async_lock:
            if execution_id in self.active_connections:
                if connection_id in self.active_connections[execution_id]:
                    conn_info = self.active_connections[execution_id][connection_id]

                    duration = (datetime.now(timezone.utc) - conn_info["connected_at"]).total_seconds()
                    SSE_CONNECTION_DURATION.labels(
                        endpoint="executions"
                    ).observe(duration)

                    del self.active_connections[execution_id][connection_id]

                    if not self.active_connections[execution_id]:
                        del self.active_connections[execution_id]

                        if execution_id in self._consumers:
                            consumer = self._consumers[execution_id]
                            await consumer.stop()
                            del self._consumers[execution_id]
                            logger.info(f"Stopped Kafka consumer for execution_id={execution_id}")

                SSE_ACTIVE_CONNECTIONS.labels(
                    endpoint="executions"
                ).dec()

                logger.info(
                    f"SSE connection closed: execution_id={execution_id}, "
                    f"connection_id={connection_id}, duration={duration:.2f}s"
                )

    async def get_or_create_consumer(self, execution_id: str) -> UnifiedConsumer:
        """Get or create a Kafka consumer for an execution.
        
        Args:
            execution_id: ID of the execution
            
        Returns:
            UnifiedConsumer instance
        """
        if execution_id not in self._consumers:
            config = ConsumerConfig(
                group_id=f"sse-{execution_id}",
                topics=[
                    "execution-events",
                    "execution-results",
                    "pod-events",
                    "pod-status-updates"
                ],
                enable_auto_commit=True,
                auto_offset_reset='earliest',
                max_poll_interval_ms=300000,
            )
            consumer = UnifiedConsumer(config, self._schema_registry_manager)

            await consumer.start()
            self._consumers[execution_id] = consumer
            logger.info(f"Created Kafka consumer for execution_id={execution_id}")

        return self._consumers[execution_id]

    def get_connection_count(self, execution_id: Optional[str] = None) -> int:
        """Get the number of active connections.
        
        Args:
            execution_id: Optional execution ID to filter by
            
        Returns:
            Number of active connections
        """
        if execution_id:
            return len(self.active_connections.get(execution_id, {}))
        return sum(len(conns) for conns in self.active_connections.values())

    def get_connection_id(self) -> str:
        """Generate a unique connection ID.
        
        Returns:
            Unique connection identifier
        """
        self._connection_id_counter += 1
        return f"sse_{self._connection_id_counter}_{datetime.now(timezone.utc).timestamp()}"

    def get_active_connections_info(self) -> Dict[str, Any]:
        """Get information about all active connections.
        
        Returns:
            Dictionary with connection statistics
        """
        total_connections = sum(
            len(connections) for connections in self.active_connections.values()
        )

        return {
            "total_connections": total_connections,
            "active_executions": len(self.active_connections),
            "active_consumers": len(self._consumers),
            "max_connections_per_user": self.max_connections_per_user
        }


def create_sse_connection_manager(
    schema_registry_manager: SchemaRegistryManager | None = None,
    shutdown_manager: SSEShutdownManager | None = None
) -> SSEConnectionManager:
    """Factory function to create an SSE connection manager.
    
    Args:
        schema_registry_manager: Optional schema registry manager
        shutdown_manager: Optional SSE shutdown manager
        
    Returns:
        A new SSE connection manager instance
    """
    return SSEConnectionManager(
        schema_registry_manager=schema_registry_manager,
        shutdown_manager=shutdown_manager
    )
