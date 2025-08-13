import asyncio
from typing import Any, Dict, List, Optional

from app.core.logging import logger
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.consumer_group_names import GroupId
from app.schemas_avro.event_schemas import (
    BaseEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionRequestedEvent,
    ExecutionStartedEvent,
    ExecutionTimeoutEvent,
    KafkaTopic,
    PodCreatedEvent,
    PodRunningEvent,
    PodScheduledEvent,
    PodTerminatedEvent,
    ResultStoredEvent,
)
from app.websocket.connection_manager import get_connection_manager


class WebSocketEventHandler:

    def __init__(self) -> None:
        self.consumer: Optional[UnifiedConsumer] = None
        self._running = False
        self._tasks: List[asyncio.Task] = []

    async def start(self) -> None:
        """Start consuming events from Kafka"""
        logger.info("Starting WebSocket event handler...")

        # Configure consumer
        consumer_config = ConsumerConfig(
            group_id=GroupId.WEBSOCKET_GATEWAY,
            topics=[
                str(KafkaTopic.EXECUTION_EVENTS),
                str(KafkaTopic.EXECUTION_RESULTS),
                str(KafkaTopic.POD_EVENTS),
                str(KafkaTopic.POD_STATUS_UPDATES),
                str(KafkaTopic.RESULT_EVENTS),
            ],
        )

        self.consumer = UnifiedConsumer(consumer_config)
        self.consumer.register_handler("*", self._handle_event)

        await self.consumer.start()
        self._running = True

        # Start periodic tasks
        cleanup_task = asyncio.create_task(self._periodic_cleanup())
        self._tasks.append(cleanup_task)

        logger.info("WebSocket event handler started")

    async def stop(self) -> None:
        logger.info("Stopping WebSocket event handler...")

        self._running = False

        # Cancel tasks
        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        if self.consumer:
            await self.consumer.stop()

        logger.info("WebSocket event handler stopped")

    async def _handle_event(self, event: BaseEvent | dict[str, Any], record: Any) -> None:
        """Handle incoming Kafka events."""
        try:
            # Only process BaseEvent instances
            if not isinstance(event, BaseEvent):
                return

            # Extract execution ID
            execution_id = self._extract_execution_id(event)
            if not execution_id:
                return

            # Create WebSocket message
            message = self._create_websocket_message(event)

            # Broadcast to subscribers
            sent_count = await get_connection_manager().broadcast_to_execution(
                execution_id,
                message
            )

            if sent_count > 0:
                logger.debug(
                    "Broadcasted event to WebSocket clients",
                    extra={
                        "event_type": event.event_type,
                        "execution_id": execution_id,
                        "sent_count": sent_count,
                    }
                )

        except Exception as e:
            logger.error(
                f"Error handling event for WebSocket broadcast: {e}",
                exc_info=True
            )

    def _extract_execution_id(self, event: BaseEvent) -> str | None:
        """Extract execution ID from event."""
        # All execution/pod/result events have execution_id field
        execution_id = getattr(event, "execution_id", None)
        return str(execution_id) if execution_id else None

    def _create_websocket_message(self, event: BaseEvent) -> Dict[str, Any]:
        """Create WebSocket message from Kafka event"""
        # Base message structure
        message = {
            "type": str(event.event_type),
            "timestamp": event.timestamp.isoformat(),
            "event_id": str(event.event_id),
            "data": {},
        }

        # Add event-specific data
        if isinstance(event, ExecutionRequestedEvent):
            message["data"] = {
                "execution_id": str(event.execution_id),
                "language": event.language,
                "language_version": event.language_version,
                "priority": event.priority,
            }

        elif isinstance(event, ExecutionStartedEvent):
            message["data"] = {
                "execution_id": str(event.execution_id),
                "pod_name": event.pod_name,
                "node_name": event.node_name,
            }

        elif isinstance(event, (ExecutionCompletedEvent, ExecutionFailedEvent)):
            message["data"] = {
                "execution_id": str(event.execution_id),
                "exit_code": event.exit_code if isinstance(event, ExecutionCompletedEvent) else None,
                "execution_time_ms": event.runtime_ms if isinstance(event, ExecutionCompletedEvent) else None,
                "error_message": event.error if isinstance(event, ExecutionFailedEvent) else None,
                "error_type": str(event.error_type) if isinstance(event, ExecutionFailedEvent) else None,
            }

        elif isinstance(event, ExecutionTimeoutEvent):
            message["data"] = {
                "execution_id": str(event.execution_id),
                "timeout_seconds": event.timeout_seconds,
            }

        elif isinstance(event, PodCreatedEvent):
            message["data"] = {
                "pod_name": event.pod_name,
                "namespace": event.namespace,
                # PodCreatedEvent only has pod_name and namespace
            }

        elif isinstance(event, PodScheduledEvent):
            message["data"] = {
                "pod_name": event.pod_name,
                "node_name": event.node_name,
                # PodScheduledEvent only has pod_name and node_name
            }

        elif isinstance(event, PodRunningEvent):
            message["data"] = {
                "pod_name": event.pod_name,
                # PodRunningEvent only has container_statuses
                "container_count": len(event.container_statuses),
            }

        elif isinstance(event, PodTerminatedEvent):
            message["data"] = {
                "pod_name": event.pod_name,
                "exit_code": event.exit_code,
                "reason": event.reason,
            }

        elif isinstance(event, ResultStoredEvent):
            message["data"] = {
                "execution_id": str(event.execution_id),
                "storage_key": event.storage_key,
                "size_bytes": event.size_bytes,
                "storage_type": str(event.storage_type),
            }

        # All BaseEvents have metadata
        message["metadata"] = {
            "service_name": event.metadata.service_name,
            "service_version": event.metadata.service_version,
            "correlation_id": str(event.metadata.correlation_id),
        }

        return message

    async def _periodic_cleanup(self) -> None:
        """Periodically cleanup stale connections"""
        while self._running:
            try:
                # Wait 5 minutes between cleanups
                await asyncio.sleep(300)

                # Cleanup stale connections (no ping in 5 minutes)
                cleaned = await get_connection_manager().cleanup_stale_connections(300)

                if cleaned > 0:
                    logger.info(f"Cleaned up {cleaned} stale WebSocket connections")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic cleanup: {e}")

    async def health_check(self) -> Dict[str, Any]:
        """Check health of WebSocket event handler"""
        try:
            # Get connection manager stats
            connection_manager = get_connection_manager()
            active_connections = connection_manager.get_connection_count()

            return {
                "healthy": True,
                "running": self._running,
                "active_connections": active_connections,
                "consumer_status": await self.consumer.get_status() if self.consumer else None
            }
        except Exception as e:
            logger.error(f"WebSocket event handler health check failed: {e}")
            return {
                "healthy": False,
                "error": str(e)
            }


class WebSocketEventHandlerSingleton:
    _instance: Optional[WebSocketEventHandler] = None

    @classmethod
    def get_instance(cls) -> WebSocketEventHandler:
        if cls._instance is None:
            cls._instance = WebSocketEventHandler()
        return cls._instance


def get_websocket_event_handler() -> WebSocketEventHandler:
    return WebSocketEventHandlerSingleton.get_instance()
