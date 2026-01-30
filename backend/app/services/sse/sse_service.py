import asyncio
import logging
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from typing import Any

from app.core.metrics import ConnectionMetrics
from app.db.repositories.sse_repository import SSERepository
from app.domain.enums.events import EventType
from app.domain.enums.notification import NotificationChannel
from app.domain.enums.sse import SSEControlEvent, SSEHealthStatus
from app.domain.sse import SSEHealthDomain
from app.schemas_pydantic.execution import ExecutionResult
from app.schemas_pydantic.notification import NotificationResponse
from app.schemas_pydantic.sse import (
    RedisNotificationMessage,
    RedisSSEMessage,
    SSEExecutionEventData,
)
from app.services.sse.kafka_redis_bridge import SSEKafkaRedisBridge
from app.services.sse.redis_bus import SSERedisBus
from app.services.sse.sse_shutdown_manager import SSEShutdownManager
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
        router: SSEKafkaRedisBridge,
        sse_bus: SSERedisBus,
        shutdown_manager: SSEShutdownManager,
        settings: Settings,
        logger: logging.Logger,
        connection_metrics: ConnectionMetrics,
    ) -> None:
        self.repository = repository
        self.router = router
        self.sse_bus = sse_bus
        self.shutdown_manager = shutdown_manager
        self.settings = settings
        self.logger = logger
        self.metrics = connection_metrics
        self.heartbeat_interval = getattr(settings, "SSE_HEARTBEAT_INTERVAL", 30)

    async def create_execution_stream(self, execution_id: str, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        connection_id = f"sse_{execution_id}_{datetime.now(timezone.utc).timestamp()}"

        shutdown_event = await self.shutdown_manager.register_connection(execution_id, connection_id)
        if shutdown_event is None:
            yield self._format_sse_event(
                SSEExecutionEventData(
                    event_type=SSEControlEvent.ERROR,
                    execution_id=execution_id,
                    timestamp=datetime.now(timezone.utc),
                    error="Server is shutting down",
                )
            )
            return

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
                shutdown_event,
                include_heartbeat=False,
            ):
                yield event_data

        finally:
            if subscription is not None:
                await asyncio.shield(subscription.close())
            await asyncio.shield(self.shutdown_manager.unregister_connection(execution_id, connection_id))
            self.logger.info("SSE connection closed", extra={"execution_id": execution_id})

    async def _stream_events_redis(
        self,
        execution_id: str,
        subscription: Any,
        shutdown_event: asyncio.Event,
        include_heartbeat: bool = True,
    ) -> AsyncGenerator[dict[str, Any], None]:
        last_heartbeat = datetime.now(timezone.utc)
        while True:
            if shutdown_event.is_set():
                yield self._format_sse_event(
                    SSEExecutionEventData(
                        event_type=SSEControlEvent.SHUTDOWN,
                        execution_id=execution_id,
                        timestamp=datetime.now(timezone.utc),
                        message="Server is shutting down",
                        grace_period=30,
                    )
                )
                break

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

    async def create_notification_stream(self, user_id: str) -> AsyncGenerator[dict[str, Any], None]:
        subscription = None
        try:
            subscription = await self.sse_bus.open_notification_subscription(user_id)
            self.logger.info("Notification subscription opened", extra={"user_id": user_id})

            while not self.shutdown_manager.is_shutting_down():
                redis_msg = await subscription.get(RedisNotificationMessage)
                if not redis_msg:
                    continue

                notification = NotificationResponse(
                    notification_id=redis_msg.notification_id,
                    channel=NotificationChannel.IN_APP,
                    status=redis_msg.status,
                    subject=redis_msg.subject,
                    body=redis_msg.body,
                    action_url=redis_msg.action_url,
                    created_at=redis_msg.created_at,
                    read_at=None,
                    severity=redis_msg.severity,
                    tags=redis_msg.tags,
                )
                yield {"event": "notification", "data": notification.model_dump_json()}
        finally:
            if subscription is not None:
                await asyncio.shield(subscription.close())
            self.logger.info("Notification stream closed", extra={"user_id": user_id})

    async def get_health_status(self) -> SSEHealthDomain:
        router_stats = self.router.get_stats()
        return SSEHealthDomain(
            status=SSEHealthStatus.DRAINING if self.shutdown_manager.is_shutting_down() else SSEHealthStatus.HEALTHY,
            kafka_enabled=True,
            active_connections=router_stats["active_executions"],
            active_executions=router_stats["active_executions"],
            active_consumers=router_stats["num_consumers"],
            max_connections_per_user=5,
            shutdown=self.shutdown_manager.get_shutdown_status(),
            timestamp=datetime.now(timezone.utc),
        )

    def _format_sse_event(self, event: SSEExecutionEventData) -> dict[str, Any]:
        """Format typed SSE event for sse-starlette."""
        return {"data": event.model_dump_json(exclude_none=True)}
