import asyncio
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx2
import structlog
from opentelemetry import trace
from tenacity import AsyncRetrying, RetryCallState, stop_after_attempt, wait_exponential
from tenacity.wait import wait_base

from app.db import NotificationRepository
from app.db.docs import NotificationDocument, NotificationSubscriptionDocument
from app.domain.enums import NotificationChannel, NotificationSeverity, NotificationStatus, UserRole
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
    SubscriptionChanges,
)
from app.domain.sse import DomainNotificationSSEPayload
from app.events import PRODUCE_ERRORS, UnifiedProducer
from app.services.sse import SSERedisBus
from app.settings import Settings

# Constants
ENTITY_EXECUTION_TAG = "entity:execution"
DELIVERY_RETRY_WAIT = wait_exponential(max=30)

# Type aliases
type EventPayload = dict[str, object]
type NotificationContext = dict[str, object]
type ChannelHandler = Callable[[NotificationDocument, NotificationSubscriptionDocument], Awaitable[None]]
type SystemNotificationStats = dict[str, int]
type SlackMessage = dict[str, object]


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


@dataclass(frozen=True)
class SystemConfig:
    severity: NotificationSeverity
    throttle_exempt: bool


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

        # --8<-- [start:channel_handlers]
        # Channel handlers mapping
        self._channel_handlers: dict[NotificationChannel, ChannelHandler] = {
            NotificationChannel.IN_APP: self._send_in_app,
            NotificationChannel.WEBHOOK: self._send_webhook,
            NotificationChannel.SLACK: self._send_slack,
        }
        # --8<-- [end:channel_handlers]

    async def create_notification(
        self,
        user_id: str,
        subject: str,
        body: str,
        tags: list[str],
        action_url: str,
        severity: NotificationSeverity = NotificationSeverity.MEDIUM,
        channel: NotificationChannel = NotificationChannel.IN_APP,
        scheduled_for: datetime | None = None,
        metadata: NotificationContext | None = None,
    ) -> NotificationDocument:
        if not tags:
            raise NotificationValidationError("tags must be a non-empty list")
        if scheduled_for is not None:
            if scheduled_for < datetime.now(UTC):
                raise NotificationValidationError("scheduled_for must be in the future")
            max_days = self.settings.NOTIF_MAX_SCHEDULE_DAYS
            max_schedule = datetime.now(UTC) + timedelta(days=max_days)
            if scheduled_for > max_schedule:
                raise NotificationValidationError(f"scheduled_for cannot exceed {max_days} days from now")
        self.logger.info(
            "Creating notification",
            user_id=user_id,
            channel=channel,
            severity=str(severity),
            tags=tags,
            scheduled=scheduled_for is not None,
        )

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
            channel=channel,
            subject=subject,
            body=body,
            action_url=action_url,
            severity=severity,
            tags=tags,
            scheduled_for=scheduled_for,
            metadata=metadata or {},
        )
        await self.repository.create_notification(notification)

        # Deliver immediately if not scheduled; scheduled notifications are
        # picked up by the NotificationScheduler worker.
        if scheduled_for is None:
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
                channels=[notification.channel],
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

    async def create_system_notification(
        self,
        title: str,
        message: str,
        severity: NotificationSeverity = NotificationSeverity.MEDIUM,
        tags: list[str] | None = None,
        metadata: dict[str, object] | None = None,
        target_users: list[str] | None = None,
        target_roles: list[UserRole] | None = None,
    ) -> SystemNotificationStats:
        """Create system notifications with streamlined control flow.

        Returns stats with totals and created/failed/throttled counts.
        """
        cfg = SystemConfig(
            severity=severity, throttle_exempt=(severity in (NotificationSeverity.HIGH, NotificationSeverity.URGENT))
        )
        base_context: NotificationContext = {"message": message, **(metadata or {})}
        users = await self._resolve_targets(target_users, target_roles)

        if not users:
            return {"total_users": 0, "created": 0, "failed": 0, "throttled": 0}

        results: list[str] = []
        for batch in itertools.batched(users, 20, strict=False):
            results += await asyncio.gather(
                *(self._create_system_for_user(uid, cfg, title, base_context, tags or ["system"]) for uid in batch)
            )

        created = sum(1 for r in results if r == "created")
        throttled = sum(1 for r in results if r == "throttled")
        failed = sum(1 for r in results if r == "failed")

        self.logger.info(
            "System notification completed",
            severity=cfg.severity,
            title=title,
            total_users=len(users),
            created=created,
            failed=failed,
            throttled=throttled,
        )

        return {"total_users": len(users), "created": created, "failed": failed, "throttled": throttled}

    async def _resolve_targets(
        self,
        target_users: list[str] | None,
        target_roles: list[UserRole] | None,
    ) -> list[str]:
        if target_users is not None:
            return target_users
        if target_roles:
            return await self.repository.get_users_by_roles(target_roles)
        return await self.repository.get_active_users(days=30)

    async def _create_system_for_user(
        self,
        user_id: str,
        cfg: SystemConfig,
        title: str,
        base_context: NotificationContext,
        tags: list[str],
    ) -> str:
        try:
            if not cfg.throttle_exempt:
                throttled = await self._throttle_cache.check_throttle(
                    user_id,
                    cfg.severity,
                    window_hours=self.settings.NOTIF_THROTTLE_WINDOW_HOURS,
                    max_per_hour=self.settings.NOTIF_THROTTLE_MAX_PER_HOUR,
                )
                if throttled:
                    self._tracer.start_span(
                        "notification.throttled", attributes={"notification.category": "system"}
                    ).end()
                    return "throttled"

            await self.create_notification(
                user_id=user_id,
                subject=title,
                body=str(base_context.get("message", "Alert")),
                tags=tags,
                action_url="/api/v1/notifications",
                severity=cfg.severity,
                channel=NotificationChannel.IN_APP,
                metadata=base_context,
            )
            return "created"
        except Exception as e:
            self.logger.error("Failed to create system notification for user", user_id=user_id, error=str(e))
            return "failed"

    async def _send_in_app(
        self, notification: NotificationDocument, subscription: NotificationSubscriptionDocument
    ) -> None:
        """Send in-app notification via SSE bus (fan-out to connected clients)."""
        await self._publish_notification_sse(notification)

    async def _send_webhook(
        self, notification: NotificationDocument, subscription: NotificationSubscriptionDocument
    ) -> None:
        """Send webhook notification."""
        webhook_url = notification.webhook_url or subscription.webhook_url
        if not webhook_url:
            raise ValueError(
                f"No webhook URL configured for user {notification.user_id} on channel {notification.channel}. "
                f"Configure in notification settings."
            )

        payload = {
            "notification_id": str(notification.notification_id),
            "severity": notification.severity,
            "tags": list(notification.tags or []),
            "subject": notification.subject,
            "body": notification.body,
            "timestamp": notification.created_at.timestamp(),
        }

        if notification.action_url:
            payload["action_url"] = notification.action_url

        headers = notification.webhook_headers or {}
        headers["Content-Type"] = "application/json"

        safe_host = urlparse(webhook_url).netloc

        self.logger.debug(
            "Sending webhook notification",
            notification_id=str(notification.notification_id),
            payload_size=len(str(payload)),
            webhook_host=safe_host,
        )

        trace.get_current_span().set_attributes(
            {
                "notification.id": str(notification.notification_id),
                "notification.channel": "webhook",
                "notification.webhook_host": safe_host,
            }
        )
        async with httpx2.AsyncClient(timeout=30.0) as client:
            response = await client.post(webhook_url, json=payload, headers=headers)
            response.raise_for_status()
        self.logger.debug(
            "Webhook delivered successfully",
            notification_id=str(notification.notification_id),
            status_code=response.status_code,
            response_time_ms=int(response.elapsed.total_seconds() * 1000),
        )

    async def _send_slack(
        self, notification: NotificationDocument, subscription: NotificationSubscriptionDocument
    ) -> None:
        """Send Slack notification."""
        if not subscription.slack_webhook:
            raise ValueError(
                f"No Slack webhook URL configured for user {notification.user_id}. "
                f"Please configure Slack integration in notification settings."
            )

        # Format message for Slack
        slack_message: SlackMessage = {
            "text": notification.subject,
            "attachments": [
                {
                    "color": self._get_slack_color(notification.severity),
                    "text": notification.body,
                    "footer": "Integr8sCode Notifications",
                    "ts": int(notification.created_at.timestamp()),
                }
            ],
        }

        # Add action button if URL provided
        if notification.action_url:
            attachments = slack_message.get("attachments", [])
            if attachments and isinstance(attachments, list):
                attachments[0]["actions"] = [{"type": "button", "text": "View Details", "url": notification.action_url}]

        self.logger.debug(
            "Sending Slack notification",
            notification_id=str(notification.notification_id),
            has_action=bool(notification.action_url),
            priority_color=self._get_slack_color(notification.severity),
        )

        trace.get_current_span().set_attributes(
            {
                "notification.id": str(notification.notification_id),
                "notification.channel": "slack",
            }
        )
        async with httpx2.AsyncClient(timeout=30.0) as client:
            response = await client.post(subscription.slack_webhook, json=slack_message)
            response.raise_for_status()
        self.logger.debug(
            "Slack notification delivered successfully",
            notification_id=str(notification.notification_id),
            status_code=response.status_code,
        )

    def _get_slack_color(self, priority: NotificationSeverity) -> str:
        """Get Slack color based on severity."""
        return {
            NotificationSeverity.LOW: "#36a64f",  # Green
            NotificationSeverity.MEDIUM: "#ff9900",  # Orange
            NotificationSeverity.HIGH: "#ff0000",  # Red
            NotificationSeverity.URGENT: "#990000",  # Dark Red
        }.get(priority, "#808080")  # Default gray

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

    async def update_subscription(
        self,
        user_id: str,
        channel: NotificationChannel,
        changes: SubscriptionChanges,
    ) -> NotificationSubscriptionDocument:
        """Update notification subscription preferences."""
        # Validate channel-specific requirements
        if channel == NotificationChannel.WEBHOOK and changes.get("enabled"):
            if not changes.get("webhook_url"):
                raise NotificationValidationError("webhook_url is required when enabling WEBHOOK")
        if channel == NotificationChannel.SLACK and changes.get("enabled"):
            if not changes.get("slack_webhook"):
                raise NotificationValidationError("slack_webhook is required when enabling SLACK")

        result = await self.repository.upsert_subscription(user_id, channel, changes)
        enabled = changes.get("enabled")
        action = "enabled" if enabled is True else "disabled" if enabled is False else "updated"
        attributes = {"notification.channel": channel, "notification.action": action}
        self._tracer.start_span("notification.subscription_change", attributes=attributes).end()
        return result

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        return await self.repository.mark_all_as_read(user_id)

    async def get_subscriptions(self, user_id: str) -> list[NotificationSubscriptionDocument]:
        """Get all notification subscriptions for a user."""
        return await self.repository.get_all_subscriptions(user_id)

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

    # --8<-- [start:should_skip_notification]
    async def _should_skip_notification(
        self, notification: NotificationDocument, subscription: NotificationSubscriptionDocument
    ) -> str | None:
        """Check if notification should be skipped based on subscription filters.

        Returns skip reason if should skip, None otherwise.
        """
        if not subscription.enabled:
            return f"User {notification.user_id} has {notification.channel} disabled; skipping delivery."

        if subscription.severities and notification.severity not in subscription.severities:
            return (
                f"Notification severity '{notification.severity}' filtered by user preferences "
                f"for {notification.channel}"
            )

        if subscription.include_tags and not any(tag in subscription.include_tags for tag in (notification.tags or [])):
            return f"Notification tags {notification.tags} not in include list for {notification.channel}"

        if subscription.exclude_tags and any(tag in subscription.exclude_tags for tag in (notification.tags or [])):
            return f"Notification tags {notification.tags} excluded by preferences for {notification.channel}"

        return None

    # --8<-- [end:should_skip_notification]

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
        attributes = {
            "notification.category": notification.tags[0] if notification.tags else "unknown",
            "notification.channel": notification.channel,
        }
        self._tracer.start_span("notification.retry", attributes=attributes).end()

    async def _deliver_notification(self, notification: NotificationDocument) -> bool:
        """Deliver notification through configured channel with inline retry.

        Returns True only when the notification reaches DELIVERED status.
        """
        claimed = await self.repository.try_claim_pending(notification.notification_id)
        if not claimed:
            return False

        self.logger.info(
            "Delivering notification",
            notification_id=str(notification.notification_id),
            user_id=notification.user_id,
            channel=notification.channel,
            severity=notification.severity,
            tags=list(notification.tags or []),
        )

        subscription = await self.repository.get_subscription(notification.user_id, notification.channel)

        skip_reason = await self._should_skip_notification(notification, subscription)
        if skip_reason:
            self.logger.info(
                "Skipping notification delivery",
                notification_id=str(notification.notification_id),
                reason=skip_reason,
            )
            await self.repository.update_notification(
                notification.notification_id,
                notification.user_id,
                NotificationChanges(status=NotificationStatus.SKIPPED, error_message=skip_reason),
            )
            return False

        handler = self._channel_handlers.get(notification.channel)
        if handler is None:
            await self.repository.update_notification(
                notification.notification_id,
                notification.user_id,
                NotificationChanges(
                    status=NotificationStatus.FAILED,
                    failed_at=datetime.now(UTC),
                    error_message=f"No handler for channel: {notification.channel}",
                ),
            )
            return False

        start_time = asyncio.get_running_loop().time()
        attributes = {
            "notification.category": notification.tags[0] if notification.tags else "unknown",
            "notification.channel": notification.channel,
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
                await retrying(handler, notification, subscription)
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
                    channel=notification.channel,
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
                        error_message=f"Delivery failed via {notification.channel}: {last_error}",
                        retry_count=notification.max_retries,
                    ),
                )
                self.logger.error(
                    "All delivery attempts exhausted",
                    notification_id=str(notification.notification_id),
                    exc_info=last_error,
                )
                return False
