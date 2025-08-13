from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from app.core.logging import logger
from app.core.metrics import SSE_MESSAGES_SENT
from app.db.mongodb import DatabaseManager
from app.events.core.consumer import UnifiedConsumer
from app.schemas_avro.event_schemas import BaseEvent, EventType
from app.schemas_pydantic.sse import SSEHealthResponse
from app.services.sse_connection_manager import get_sse_connection_manager
from app.services.sse_shutdown_manager import SSEShutdownManager

type SSEEvent = dict[str, Any]
type EventData = dict[str, Any]
type DisconnectCheck = Callable[[], Awaitable[bool]]
type MessageProcessor = Callable[[str | None, dict, Any], Awaitable[None]]


class SSERepository:
    """Repository for handling SSE operations and event streaming."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        self.connection_manager = get_sse_connection_manager()

    async def create_kafka_event_stream(
            self,
            execution_id: str,
            user_id: str,
            connection_id: str,
            shutdown_manager: SSEShutdownManager
    ) -> AsyncGenerator[SSEEvent, None]:
        """Create a Kafka event stream for execution monitoring."""
        heartbeat_task: asyncio.Task[None] | None = None
        try:
            await self.connection_manager.add_connection(execution_id, user_id, connection_id)
            consumer = await self.connection_manager.get_or_create_consumer(execution_id)

            heartbeat_task = asyncio.create_task(
                self._heartbeat_generator(execution_id, shutdown_manager, interval=10)
            )

            yield self._format_event("connected", {
                "execution_id": execution_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "connection_id": connection_id
            })

            initial_status = await self._fetch_execution_status(execution_id)
            if initial_status:
                yield self._format_event("status", initial_status)
                self._record_metric("executions", "status")

            async for event in self._consume_kafka_events(consumer, execution_id, shutdown_manager):
                yield event

        finally:
            if heartbeat_task and not heartbeat_task.done():
                heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat_task

            await self.connection_manager.remove_connection(execution_id, connection_id)
            logger.info(f"SSE connection closed: execution_id={execution_id}")

    async def create_notification_stream(
            self,
            user_id: str,
            request_disconnected_check: DisconnectCheck
    ) -> AsyncGenerator[SSEEvent, None]:
        """Create a notification stream for a user."""
        yield self._format_event("connected", {
            "message": "Connected to notification stream",
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        while not await request_disconnected_check():
            await asyncio.sleep(10)
            yield self._format_event("heartbeat", {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
                "message": "Notification stream active"
            })

    async def create_execution_event_stream(
            self,
            execution_id: str,
            user_id: str,
            request_disconnected_check: DisconnectCheck
    ) -> AsyncGenerator[SSEEvent, None]:
        """Create an execution event stream using database polling."""
        yield self._format_event("connected", {
            "message": "Connected to execution stream",
            "execution_id": execution_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })

        db = self.db_manager.db
        if not db:
            yield self._format_event("error", {
                "error": "Database not available",
                "execution_id": execution_id,
                "timestamp": datetime.now(timezone.utc).isoformat()
            })
            return

        previous_status: str | None = None
        terminal_states = {"completed", "error", "failed"}

        for poll_count in range(120):  # Max 2 minutes
            if await request_disconnected_check():
                break

            execution = await db.executions.find_one({
                "execution_id": execution_id,
                "user_id": user_id
            })

            if not execution:
                yield self._format_event("error", {
                    "error": "Execution not found",
                    "execution_id": execution_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })
                break

            current_status = execution.get("status")

            if current_status != previous_status:
                event_data = {
                    "execution_id": execution_id,
                    "status": current_status,
                    "output": execution.get("output", ""),
                    "errors": execution.get("errors", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }

                yield self._format_event("status", event_data)
                previous_status = current_status

                if current_status in terminal_states:
                    yield self._format_event("complete", event_data)
                    break

            if poll_count % 15 == 0:
                yield self._format_event("heartbeat", {
                    "execution_id": execution_id,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

            await asyncio.sleep(1)

    async def get_health_status(
            self,
            shutdown_manager: SSEShutdownManager
    ) -> SSEHealthResponse:
        """Get SSE service health status."""
        connection_info = self.connection_manager.get_active_connections_info()

        return SSEHealthResponse(
            status="draining" if shutdown_manager.is_shutting_down() else "healthy",
            kafka_enabled=True,
            active_connections=connection_info["total_connections"],
            active_executions=connection_info["active_executions"],
            active_consumers=connection_info["active_consumers"],
            max_connections_per_user=connection_info["max_connections_per_user"],
            shutdown=shutdown_manager.get_shutdown_status(),
            timestamp=datetime.now(timezone.utc)
        )

    async def _heartbeat_generator(
            self,
            execution_id: str,
            shutdown_manager: SSEShutdownManager,
            interval: int = 10
    ) -> None:
        """Generate periodic heartbeats."""
        while not shutdown_manager.is_shutting_down():
            await asyncio.sleep(interval)

    async def _fetch_execution_status(
            self,
            execution_id: str
    ) -> EventData | None:
        """Fetch current execution status from database."""
        db = self.db_manager.db
        if not db:
            return None

        execution = await db.executions.find_one({"execution_id": execution_id})

        if execution and "status" in execution:
            return {
                "execution_id": execution_id,
                "status": execution["status"],
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        return None

    async def _consume_kafka_events(
            self,
            consumer: UnifiedConsumer,
            execution_id: str,
            shutdown_manager: SSEShutdownManager
    ) -> AsyncGenerator[SSEEvent, None]:
        """Consume events from Kafka for a specific execution."""
        event_queue: asyncio.Queue[EventData] = asyncio.Queue(maxsize=100)
        terminal_events = {
            str(EventType.EXECUTION_COMPLETED),
            str(EventType.EXECUTION_FAILED),
            str(EventType.EXECUTION_TIMEOUT)
        }

        async def message_handler(event: BaseEvent | dict[str, Any], record: Any) -> Any:
            # Handle both BaseEvent and dict formats
            if isinstance(event, dict):
                value = event
            else:
                value = event.to_dict() if hasattr(event, 'to_dict') else {}

            aggregate_id = value.get('aggregate_id')
            exec_id = value.get('execution_id')

            if aggregate_id == execution_id or exec_id == execution_id:
                await event_queue.put(value)

        # Register handler for all event types
        consumer.register_handler("*", message_handler)

        if not consumer._running:
            await consumer.start()

        try:
            while not shutdown_manager.is_shutting_down():
                try:
                    event_data = await asyncio.wait_for(event_queue.get(), timeout=1.0)
                    event_type = event_data.get('event_type', 'unknown')

                    yield self._format_event(event_type, {
                        "event_id": event_data.get('event_id'),
                        "timestamp": event_data.get('timestamp'),
                        "type": event_type,
                        "execution_id": execution_id,
                        "status": event_data.get('status'),
                        "payload": event_data.get('payload', {})
                    })

                    self._record_metric("executions", event_type)

                    if event_type in terminal_events:
                        logger.info(f"Terminal event for execution_id={execution_id}: {event_type}")
                        await asyncio.sleep(2)
                        return

                except asyncio.TimeoutError:
                    continue

        finally:
            # Note: Handler cleanup would be needed here if we wanted to unregister
            # but since the consumer is typically reused, we leave it registered

            if shutdown_manager.is_shutting_down():
                yield self._format_event("shutdown", {
                    "message": "Server is shutting down",
                    "timestamp": datetime.now(timezone.utc).isoformat()
                })

    def _format_event(self, event_type: str, data: EventData) -> SSEEvent:
        """Format data as an SSE event."""
        return {
            "event": event_type,
            "data": json.dumps(data)
        }

    def _record_metric(self, endpoint: str, event_type: str) -> None:
        """Record SSE message metric."""
        SSE_MESSAGES_SENT.labels(
            endpoint=endpoint,
            event_type=event_type
        ).inc()
