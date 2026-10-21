import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import structlog
from opentelemetry import trace
from tenacity import AsyncRetrying, RetryCallState, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

from app.db import NotificationRepository
from app.db.docs import NotificationDocument
from app.domain.enums import NotificationSeverity, NotificationStatus
from app.domain.events import (
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    NotificationCreatedEvent,
)
from app.domain.notification import (
    NotificationChanges,
    NotificationNotFoundError,
    NotificationThrottledError,
    NotificationValidationError,
)
from app.domain.sse import DomainNotificationSSEPayload
from app.events import PRODUCE_ERRORS, UnifiedProducer
from app.services.sse import SSERedisBus
from app.settings import Settings

# Constants
ENTITY_EXECUTION_TAG = "entity:execution"
DELIVERY_RETRY_WAIT = wait_exponential(max=30)

# Type aliases
type NotificationContext = dict[str, object]


@dataclass
class NotificationListResult:
    notifications: list[NotificationDocument]
    total: int
    unread_count: int


# --8<-- [start:ThrottleCache]
@dataclass
class ThrottleCache:
    """Manages notification throttling with time windows."""

    _entries: dict[str, list[datetime]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def check_throttle(
        self,
        user_id: str,
        severity: NotificationSeverity,
        window_hours: int,
        max_per_hour: int,
    ) -> bool:
        """Check if notification should be throttled."""
        key = f"{user_id}:{severity}"
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=window_hours)

        async with self._lock:
            if key not in self._entries:
                self._entries[key] = []

            # Clean old entries
            self._entries[key] = [ts for ts in self._entries[key] if ts > window_start]

            # Check limit
            if len(self._entries[key]) >= max_per_hour:
                return True

            # Add new entry
            self._entries[key].append(now)
            return False

    async def clear(self) -> None:
        """Clear all throttle entries."""
        async with self._lock:
            self._entries.clear()


# --8<-- [end:ThrottleCache]


class NotificationService:
    def __init__(
        self,
        notification_repository: NotificationRepository,
        producer: UnifiedProducer,
        sse_bus: SSERedisBus,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
        tracer: trace.Tracer,
        retry_wait: wait_base = DELIVERY_RETRY_WAIT,
    ) -> None:
        self.repository = notification_repository
        self._retry_wait = retry_wait
        self._producer = producer
        self._tracer = tracer
        self.settings = settings
        self.sse_bus = sse_bus
        self.logger = logger
        self._throttle_cache = ThrottleCache()

    async def create_notification(
        self,
        user_id: str,
        subject: str,
        body: str,
        tags: list[str],
        action_url: str,
        severity: NotificationSeverity = NotificationSeverity.MEDIUM,
        metadata: NotificationContext | None = None,
    ) -> NotificationDocument:
        if not tags:
            raise NotificationValidationError("tags must be a non-empty list")
        self.logger.info("Creating notification", user_id=user_id, severity=str(severity), tags=tags)

        # Check throttling
        if self.settings.ENVIRONMENT != "test" and await self._throttle_cache.check_throttle(
            user_id,
            severity,
            window_hours=self.settings.NOTIF_THROTTLE_WINDOW_HOURS,
            max_per_hour=self.settings.NOTIF_THROTTLE_MAX_PER_HOUR,
        ):
            self.logger.warning(
                "Notification rate limit exceeded",
                user_id=user_id,
                max_per_window=self.settings.NOTIF_THROTTLE_MAX_PER_HOUR,
                window_hours=self.settings.NOTIF_THROTTLE_WINDOW_HOURS,
            )
            self._tracer.start_span("notification.throttled", attributes={"notification.category": "general"}).end()
            raise NotificationThrottledError(
                user_id,
                self.settings.NOTIF_THROTTLE_MAX_PER_HOUR,
                self.settings.NOTIF_THROTTLE_WINDOW_HOURS,
            )

        # Create notification
        notification = NotificationDocument(
            user_id=user_id,
            subject=subject,
            body=body,
            action_url=action_url,
            severity=severity,
            tags=tags,
            metadata=metadata or {},
        )
        await self.repository.create_notification(notification)
        await self._deliver_notification(notification)

        await self._publish_notification_created_event(notification)

        return notification

    async def _publish_notification_created_event(self, notification: NotificationDocument) -> None:
        """Publish NotificationCreatedEvent after the notification is persisted."""
        try:
            event = NotificationCreatedEvent(
                notification_id=notification.notification_id,
                user_id=notification.user_id,
                subject=notification.subject,
                body=notification.body,
                severity=notification.severity,
                tags=list(notification.tags or []),
                metadata=EventMetadata(
                    service_name=self.settings.SERVICE_NAME,
                    service_version=self.settings.SERVICE_VERSION,
                    user_id=notification.user_id,
                ),
            )
            await self._producer.produce(event_to_produce=event, key=notification.user_id)
        except PRODUCE_ERRORS as e:
            self.logger.error(
                "Failed to publish notification created event",
                notification_id=notification.notification_id,
                error=str(e),
            )

    async def handle_execution_timeout(self, event: ExecutionTimeoutEvent) -> None:
        """Handle execution timeout event."""
        user_id = event.metadata.user_id

        title = f"Execution Timeout: {event.execution_id}"
        body = f"Your execution timed out after {event.timeout_seconds}s."
        await self.create_notification(
            user_id=user_id,
            subject=title,
            body=body,
            severity=NotificationSeverity.HIGH,
            tags=["execution", "timeout", ENTITY_EXECUTION_TAG, f"exec:{event.execution_id}"],
            action_url=f"/api/v1/executions/{event.execution_id}/result",
            metadata=event.model_dump(),
        )

    async def handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event."""
        user_id = event.metadata.user_id

        title = f"Execution Completed: {event.execution_id}"
        duration = event.resource_usage.execution_time_wall_seconds
        body = f"Your execution completed successfully. Duration: {duration:.2f}s."
        await self.create_notification(
            user_id=user_id,
            subject=title,
            body=body,
            severity=NotificationSeverity.MEDIUM,
            tags=["execution", "completed", ENTITY_EXECUTION_TAG, f"exec:{event.execution_id}"],
            action_url=f"/api/v1/executions/{event.execution_id}/result",
            metadata=event.model_dump(),
        )

    async def handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed event."""
        user_id = event.metadata.user_id

        event_data = event.model_dump()

        # Truncate stdout/stderr for notification context
        event_data["stdout"] = event_data["stdout"][:200]
        event_data["stderr"] = event_data["stderr"][:200]

        title = f"Execution Failed: {event.execution_id}"
        body = f"Your execution failed: {event.error_type} (exit code {event.exit_code})."
        await self.create_notification(
            user_id=user_id,
            subject=title,
            body=body,
            severity=NotificationSeverity.HIGH,
            tags=["execution", "failed", ENTITY_EXECUTION_TAG, f"exec:{event.execution_id}"],
            action_url=f"/api/v1/executions/{event.execution_id}/result",
            metadata=event_data,
        )

    async def mark_as_read(self, user_id: str, notification_id: str) -> None:
        """Mark notification as read."""
        success = await self.repository.mark_as_read(notification_id, user_id)
        if not success:
            raise NotificationNotFoundError(notification_id)

    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications."""
        return await self.repository.get_unread_count(user_id)

    async def list_notifications(
        self,
        user_id: str,
        status: NotificationStatus | None = None,
        limit: int = 20,
        offset: int = 0,
        include_tags: list[str] | None = None,
        exclude_tags: list[str] | None = None,
        tag_prefix: str | None = None,
    ) -> NotificationListResult:
        """List notifications with pagination."""
        # Get notifications
        notifications = await self.repository.list_notifications(
            user_id=user_id,
            status=status,
            skip=offset,
            limit=limit,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            tag_prefix=tag_prefix,
        )

        # Get counts
        total, unread_count = await asyncio.gather(
            self.repository.count_notifications(
                user_id=user_id,
                status=status,
                include_tags=include_tags,
                exclude_tags=exclude_tags,
                tag_prefix=tag_prefix,
            ),
            self.get_unread_count(user_id),
        )

        return NotificationListResult(notifications=notifications, total=total, unread_count=unread_count)

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        return await self.repository.mark_all_as_read(user_id)

    async def delete_notification(self, user_id: str, notification_id: str) -> None:
        """Delete a notification."""
        deleted = await self.repository.delete_notification(str(notification_id), user_id)
        if not deleted:
            raise NotificationNotFoundError(notification_id)

    async def _publish_notification_sse(self, notification: NotificationDocument) -> None:
        """Publish an in-app notification to the SSE bus for realtime delivery."""
        payload = DomainNotificationSSEPayload(
            notification_id=notification.notification_id,
            severity=notification.severity,
            status=notification.status,
            tags=list(notification.tags or []),
            subject=notification.subject,
            body=notification.body,
            action_url=notification.action_url,
            created_at=notification.created_at,
        )
        await self.sse_bus.publish_notification(notification.user_id, payload)

    def _log_delivery_retry(self, state: RetryCallState) -> None:
        """Log a failed delivery attempt and count the retry; the retried call's first argument is the notification."""
        notification: NotificationDocument = state.args[0]
        self.logger.warning(
            "Delivery attempt failed",
            notification_id=str(notification.notification_id),
            attempt=state.attempt_number,
            max_attempts=notification.max_retries,
            error=str(state.outcome.exception() if state.outcome else None),
        )
        attributes = {"notification.category": notification.tags[0] if notification.tags else "unknown"}
        self._tracer.start_span("notification.retry", attributes=attributes).end()

    async def _deliver_notification(self, notification: NotificationDocument) -> bool:
        """Push the notification to the user's open notification streams, retrying a failed publish.

        Returns True only when the notification reaches DELIVERED status.
        """
        claimed = await self.repository.try_claim_pending(notification.notification_id)
        if not claimed:
            return False

        self.logger.info(
            "Delivering notification",
            notification_id=str(notification.notification_id),
            user_id=notification.user_id,
            severity=notification.severity,
            tags=list(notification.tags or []),
        )

        start_time = asyncio.get_running_loop().time()
        attributes = {
            "notification.category": notification.tags[0] if notification.tags else "unknown",
            "notification.severity": notification.severity,
        }

        retrying = AsyncRetrying(
            stop=stop_after_attempt(notification.max_retries),
            wait=self._retry_wait,
            before_sleep=self._log_delivery_retry,
            reraise=True,
        )

        with self._tracer.start_as_current_span("notification.deliver", attributes=attributes) as span:
            try:
                await retrying(self._publish_notification_sse, notification)
                delivery_time = asyncio.get_running_loop().time() - start_time
                span.set_attributes(
                    {"notification.result": "delivered", "notification.delivery_seconds": delivery_time}
                )
                await self.repository.update_notification(
                    notification.notification_id,
                    notification.user_id,
                    NotificationChanges(status=NotificationStatus.DELIVERED, delivered_at=datetime.now(UTC)),
                )
                self.logger.info(
                    "Delivered notification",
                    notification_id=str(notification.notification_id),
                    delivery_time_ms=int(delivery_time * 1000),
                )
                return True
            except Exception as last_error:
                span.set_attributes({"notification.result": "failed", "notification.error": type(last_error).__name__})
                await self.repository.update_notification(
                    notification.notification_id,
                    notification.user_id,
                    NotificationChanges(
                        status=NotificationStatus.FAILED,
                        failed_at=datetime.now(UTC),
                        error_message=f"Delivery failed: {last_error}",
                        retry_count=notification.max_retries,
                    ),
                )
                self.logger.error(
                    "All delivery attempts exhausted",
                    notification_id=str(notification.notification_id),
                    exc_info=last_error,
                )
                return False
