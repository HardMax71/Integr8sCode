import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any, Dict

from app.core.metrics import ConnectionMetrics
from app.db.repositories.sse_repository import SSERepository
from app.domain.enums.events import EventType
from app.domain.enums.sse import SSEControlEvent, SSENotificationEvent
from app.domain.sse import ShutdownStatus, SSEHealthDomain
from app.schemas_pydantic.execution import ExecutionResult
from app.schemas_pydantic.sse import (
    RedisNotificationMessage,
    RedisSSEMessage,
    SSEExecutionEventData,
    SSENotificationEventData,
)
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_connection_registry import SSEConnectionRegistry
from app.settings import Settings


class SSEService:
    # Terminal event types that should close the SSE stream
    TERMINAL_EVENT_TYPES: set[EventType] = {
        EventType.RESULT_STORED,
        EventType.EXECUTION_FAILED,
        EventType.EXECUTION_TIMEOUT,
        EventType.RESULT_FAILED,
    }

    def __init__(
            self,
            repository: SSERepository,
            sse_bus: SSERedisBus,
            connection_registry: SSEConnectionRegistry,
            settings: Settings,
            logger: logging.Logger,
            connection_metrics: ConnectionMetrics,
    ) -> None:
        self.repository = repository
        self.sse_bus = sse_bus
        self.connection_registry = connection_registry
        self.settings = settings
        self.logger = logger
        self.metrics = connection_metrics
        self.heartbeat_interval = settings.SSE_HEARTBEAT_INTERVAL

    async def create_execution_stream(self, execution_id: str, user_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        connection_id = f"sse_{execution_id}_{datetime.now(timezone.utc).timestamp()}"

        await self.connection_registry.register_connection(execution_id, connection_id)

        subscription = None
        try:
            # Start opening subscription concurrently, then yield handshake
            sub_task = asyncio.create_task(self.sse_bus.open_subscription(execution_id))
            yield self._format_sse_event(
                SSEExecutionEventData(
                    event_type=SSEControlEvent.CONNECTED,
                    execution_id=execution_id,
                    timestamp=datetime.now(timezone.utc),
                    connection_id=connection_id,
                )
            )

            # Complete Redis subscription after handshake
            self.logger.info("Opening Redis subscription for execution", extra={"execution_id": execution_id})
            subscription = await sub_task
            self.logger.info("Redis subscription opened for execution", extra={"execution_id": execution_id})

            # Signal that subscription is ready - safe to publish events now
            yield self._format_sse_event(
                SSEExecutionEventData(
                    event_type=SSEControlEvent.SUBSCRIBED,
                    execution_id=execution_id,
                    timestamp=datetime.now(timezone.utc),
                    message="Redis subscription established",
                )
            )

            initial_status = await self.repository.get_execution_status(execution_id)
            if initial_status:
                yield self._format_sse_event(
                    SSEExecutionEventData(
                        event_type=SSEControlEvent.STATUS,
                        execution_id=initial_status.execution_id,
                        timestamp=initial_status.timestamp,
                        status=initial_status.status,
                    )
                )
                self.metrics.record_sse_message_sent("executions", "status")

            async for event_data in self._stream_events_redis(
                    execution_id,
                    subscription,
                    include_heartbeat=False,
            ):
                yield event_data

        finally:
            if subscription is not None:
                await asyncio.shield(subscription.close())
            await asyncio.shield(self.connection_registry.unregister_connection(execution_id, connection_id))
            self.logger.info("SSE connection closed", extra={"execution_id": execution_id})

    async def _stream_events_redis(
            self,
            execution_id: str,
            subscription: Any,
            include_heartbeat: bool = True,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream events from Redis subscription until terminal event or cancellation."""
        last_heartbeat = datetime.now(timezone.utc)
        while True:
            now = datetime.now(timezone.utc)
            if include_heartbeat and (now - last_heartbeat).total_seconds() >= self.heartbeat_interval:
                yield self._format_sse_event(
                    SSEExecutionEventData(
                        event_type=SSEControlEvent.HEARTBEAT,
                        execution_id=execution_id,
                        timestamp=now,
                        message="SSE connection active",
                    )
                )
                last_heartbeat = now

            msg: RedisSSEMessage | None = await subscription.get(RedisSSEMessage)
            if not msg:
                continue

            self.logger.info(
                "Received Redis message for execution",
                extra={"execution_id": execution_id, "event_type": str(msg.event_type)},
            )
            try:
                sse_event = await self._build_sse_event_from_redis(execution_id, msg)
                yield self._format_sse_event(sse_event)

                # End on terminal event types
                if msg.event_type in self.TERMINAL_EVENT_TYPES:
                    self.logger.info(
                        "Terminal event for execution",
                        extra={"execution_id": execution_id, "event_type": str(msg.event_type)},
                    )
                    break
            except Exception as e:
                self.logger.warning(
                    "Failed to process SSE message",
                    extra={"execution_id": execution_id, "event_type": str(msg.event_type), "error": str(e)},
                )
                continue

    async def _build_sse_event_from_redis(self, execution_id: str, msg: RedisSSEMessage) -> SSEExecutionEventData:
        """Build typed SSE event from Redis message."""
        result: ExecutionResult | None = None
        if msg.event_type == EventType.RESULT_STORED:
            exec_domain = await self.repository.get_execution(execution_id)
            if exec_domain:
                result = ExecutionResult.model_validate(exec_domain)

        return SSEExecutionEventData.model_validate(
            {
                **msg.data,
                "event_type": msg.event_type,
                "execution_id": execution_id,
                "result": result,
            }
        )

    async def create_notification_stream(self, user_id: str) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream notifications until cancelled."""
        subscription = None

        try:
            # Start opening subscription concurrently, then yield handshake
            sub_task = asyncio.create_task(self.sse_bus.open_notification_subscription(user_id))
            yield self._format_notification_event(
                SSENotificationEventData(
                    event_type=SSENotificationEvent.CONNECTED,
                    user_id=user_id,
                    timestamp=datetime.now(timezone.utc),
                    message="Connected to notification stream",
                )
            )

            # Complete Redis subscription after handshake
            subscription = await sub_task

            # Signal that subscription is ready - safe to publish notifications now
            yield self._format_notification_event(
                SSENotificationEventData(
                    event_type=SSENotificationEvent.SUBSCRIBED,
                    user_id=user_id,
                    timestamp=datetime.now(timezone.utc),
                    message="Redis subscription established",
                )
            )

            last_heartbeat = datetime.now(timezone.utc)
            while True:
                # Heartbeat
                now = datetime.now(timezone.utc)
                if (now - last_heartbeat).total_seconds() >= self.heartbeat_interval:
                    yield self._format_notification_event(
                        SSENotificationEventData(
                            event_type=SSENotificationEvent.HEARTBEAT,
                            user_id=user_id,
                            timestamp=now,
                            message="Notification stream active",
                        )
                    )
                    last_heartbeat = now

                # Forward notification messages as SSE data
                redis_msg = await subscription.get(RedisNotificationMessage)
                if redis_msg:
                    yield self._format_notification_event(
                        SSENotificationEventData(
                            event_type=SSENotificationEvent.NOTIFICATION,
                            notification_id=redis_msg.notification_id,
                            severity=redis_msg.severity,
                            status=redis_msg.status,
                            tags=redis_msg.tags,
                            subject=redis_msg.subject,
                            body=redis_msg.body,
                            action_url=redis_msg.action_url,
                            created_at=redis_msg.created_at,
                        )
                    )
        finally:
            if subscription is not None:
                await asyncio.shield(subscription.close())

    async def get_health_status(self) -> SSEHealthDomain:
        """Get SSE service health status."""
        active_connections = self.connection_registry.get_connection_count()
        return SSEHealthDomain(
            status="healthy",
            kafka_enabled=True,
            active_connections=active_connections,
            active_executions=self.connection_registry.get_execution_count(),
            active_consumers=0,  # Consumers run in separate SSE bridge worker
            max_connections_per_user=5,
            shutdown=ShutdownStatus(
                phase="ready",
                initiated=False,
                complete=False,
                active_connections=active_connections,
                draining_connections=0,
            ),
            timestamp=datetime.now(timezone.utc),
        )

    def _format_sse_event(self, event: SSEExecutionEventData) -> Dict[str, Any]:
        """Format typed SSE event for sse-starlette."""
        return {"data": event.model_dump_json(exclude_none=True)}

    def _format_notification_event(self, event: SSENotificationEventData) -> Dict[str, Any]:
        """Format typed notification SSE event for sse-starlette."""
        return {"data": event.model_dump_json(exclude_none=True)}
