import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Awaitable, Callable
from urllib.parse import urlparse

import backoff
import httpx
import structlog
from opentelemetry import trace

from app.core.metrics import NotificationMetrics
from app.db.repositories import NotificationRepository
from app.domain.enums import NotificationChannel, NotificationSeverity, NotificationStatus, UserRole
from app.domain.events import (
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    NotificationCreatedEvent,
)
from app.domain.notification import (
    DomainNotification,
    DomainNotificationCreate,
    DomainNotificationListResult,
    DomainNotificationSubscription,
    DomainNotificationUpdate,
    DomainSubscriptionListResult,
    DomainSubscriptionUpdate,
    NotificationNotFoundError,
    NotificationThrottledError,
    NotificationValidationError,
)
from app.domain.sse import DomainNotificationSSEPayload
from app.services.kafka_event_service import KafkaEventService
from app.services.sse import SSERedisBus
from app.settings import Settings

# Constants
ENTITY_EXECUTION_TAG = "entity:execution"

# Type aliases
type EventPayload = dict[str, object]
type NotificationContext = dict[str, object]
type ChannelHandler = Callable[[DomainNotification, DomainNotificationSubscription], Awaitable[None]]
type SystemNotificationStats = dict[str, int]
type SlackMessage = dict[str, object]


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
        event_service: KafkaEventService,
        sse_bus: SSERedisBus,
        settings: Settings,
        logger: structlog.stdlib.BoundLogger,
        notification_metrics: NotificationMetrics,
    ) -> None:
        self.repository = notification_repository
        self.event_service = event_service
        self.metrics = notification_metrics
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
    ) -> DomainNotification:
        if not tags:
            raise NotificationValidationError("tags must be a non-empty list")
        if scheduled_for is not None:
            if scheduled_for < datetime.now(UTC):
                raise NotificationValidationError("scheduled_for must be in the future")
            max_days = self.settings.NOTIF_MAX_SCHEDULE_DAYS
            max_schedule = datetime.now(UTC) + timedelta(days=max_days)
            if scheduled_for > max_schedule:
                raise NotificationValidationError(
                    f"scheduled_for cannot exceed {max_days} days from now"
                )
        self.logger.info(
            f"Creating notification for user {user_id}",
            user_id=user_id,
            channel=channel,
            severity=str(severity),
            tags=tags,
            scheduled=scheduled_for is not None,
        )

        # Check throttling
        if not self.settings.TESTING and await self._throttle_cache.check_throttle(
            user_id,
            severity,
            window_hours=self.settings.NOTIF_THROTTLE_WINDOW_HOURS,
            max_per_hour=self.settings.NOTIF_THROTTLE_MAX_PER_HOUR,
        ):
            error_msg = (
                f"Notification rate limit exceeded for user {user_id}. "
                f"Max {self.settings.NOTIF_THROTTLE_MAX_PER_HOUR} "
                f"per {self.settings.NOTIF_THROTTLE_WINDOW_HOURS} hour(s)"
            )
            self.logger.warning(error_msg)
            self.metrics.record_notification_throttled("general")
            raise NotificationThrottledError(
                user_id,
                self.settings.NOTIF_THROTTLE_MAX_PER_HOUR,
                self.settings.NOTIF_THROTTLE_WINDOW_HOURS,
            )

        # Create notification
        create_data = DomainNotificationCreate(
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

        # Save to database
        notification = await self.repository.create_notification(create_data)

        # Deliver immediately if not scheduled; scheduled notifications are
        # picked up by the NotificationScheduler worker.
        if scheduled_for is None:
            await self._deliver_notification(notification)

        await self._publish_notification_created_event(notification)

        return notification

    async def _publish_notification_created_event(self, notification: DomainNotification) -> None:
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
            await self.event_service.publish_event(event, key=notification.user_id)
        except Exception as e:
            self.logger.error(f"Failed to publish notification created event: {e}")

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

        sem = asyncio.Semaphore(20)

        async def worker(uid: str) -> str:
            async with sem:
                return await self._create_system_for_user(uid, cfg, title, base_context, tags or ["system"])

        results = (
            [await worker(u) for u in users] if len(users) <= 20 else await asyncio.gather(*(worker(u) for u in users))
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
            self.logger.error(
                "Failed to create system notification for user", user_id=user_id, error=str(e)
            )
            return "failed"

    async def _send_in_app(
        self, notification: DomainNotification, subscription: DomainNotificationSubscription
    ) -> None:
        """Send in-app notification via SSE bus (fan-out to connected clients)."""
        await self._publish_notification_sse(notification)

    async def _send_webhook(
        self, notification: DomainNotification, subscription: DomainNotificationSubscription
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

        trace.get_current_span().set_attributes({
            "notification.id": str(notification.notification_id),
            "notification.channel": "webhook",
            "notification.webhook_host": safe_host,
        })
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, headers=headers, timeout=30.0)
            response.raise_for_status()
            self.logger.debug(
                "Webhook delivered successfully",
                notification_id=str(notification.notification_id),
                status_code=response.status_code,
                response_time_ms=int(response.elapsed.total_seconds() * 1000),
            )

    async def _send_slack(self, notification: DomainNotification, subscription: DomainNotificationSubscription) -> None:
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

        trace.get_current_span().set_attributes({
            "notification.id": str(notification.notification_id),
            "notification.channel": "slack",
        })
        async with httpx.AsyncClient() as client:
            response = await client.post(subscription.slack_webhook, json=slack_message, timeout=30.0)
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
        duration = event.resource_usage.execution_time_wall_seconds if event.resource_usage else 0.0
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
        body = f"Your execution failed: {event.message}"
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
    ) -> DomainNotificationListResult:
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

        return DomainNotificationListResult(notifications=notifications, total=total, unread_count=unread_count)

    async def update_subscription(
        self,
        user_id: str,
        channel: NotificationChannel,
        update_data: DomainSubscriptionUpdate,
    ) -> DomainNotificationSubscription:
        """Update notification subscription preferences."""
        # Validate channel-specific requirements
        if channel == NotificationChannel.WEBHOOK and update_data.enabled:
            if not update_data.webhook_url:
                raise NotificationValidationError("webhook_url is required when enabling WEBHOOK")
        if channel == NotificationChannel.SLACK and update_data.enabled:
            if not update_data.slack_webhook:
                raise NotificationValidationError("slack_webhook is required when enabling SLACK")

        result = await self.repository.upsert_subscription(user_id, channel, update_data)
        self.metrics.record_subscription_change(channel, update_data.enabled)
        return result

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        return await self.repository.mark_all_as_read(user_id)

    async def get_subscriptions(self, user_id: str) -> DomainSubscriptionListResult:
        """Get all notification subscriptions for a user."""
        subs = await self.repository.get_all_subscriptions(user_id)
        return DomainSubscriptionListResult(subscriptions=subs)

    async def delete_notification(self, user_id: str, notification_id: str) -> None:
        """Delete a notification."""
        deleted = await self.repository.delete_notification(str(notification_id), user_id)
        if not deleted:
            raise NotificationNotFoundError(notification_id)

    async def _publish_notification_sse(self, notification: DomainNotification) -> None:
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
        self, notification: DomainNotification, subscription: DomainNotificationSubscription
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

    async def _deliver_notification(self, notification: DomainNotification) -> bool:
        """Deliver notification through configured channel with inline retry.

        Returns True only when the notification reaches DELIVERED status.
        """
        claimed = await self.repository.try_claim_pending(notification.notification_id)
        if not claimed:
            return False

        self.logger.info(
            f"Delivering notification {notification.notification_id}",
            notification_id=str(notification.notification_id),
            user_id=notification.user_id,
            channel=notification.channel,
            severity=notification.severity,
            tags=list(notification.tags or []),
        )

        subscription = await self.repository.get_subscription(notification.user_id, notification.channel)

        skip_reason = await self._should_skip_notification(notification, subscription)
        if skip_reason:
            self.logger.info(skip_reason)
            await self.repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(status=NotificationStatus.SKIPPED, error_message=skip_reason),
            )
            return False

        handler = self._channel_handlers.get(notification.channel)
        if handler is None:
            await self.repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(
                    status=NotificationStatus.FAILED,
                    failed_at=datetime.now(UTC),
                    error_message=f"No handler for channel: {notification.channel}",
                ),
            )
            return False

        start_time = asyncio.get_running_loop().time()

        @backoff.on_exception(
            backoff.expo,
            Exception,
            max_tries=notification.max_retries,
            max_value=30,
            jitter=None,
            on_backoff=lambda details: self.logger.warning(
                f"Delivery attempt {details['tries']}/{notification.max_retries} failed "
                f"for {notification.notification_id}: {details['exception']}",
            ),
        )
        async def _attempt() -> None:
            await handler(notification, subscription)

        try:
            await _attempt()
            delivery_time = asyncio.get_running_loop().time() - start_time
            await self.repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(status=NotificationStatus.DELIVERED, delivered_at=datetime.now(UTC)),
            )
            self.logger.info(
                f"Delivered notification {notification.notification_id}",
                notification_id=str(notification.notification_id),
                channel=notification.channel,
                delivery_time_ms=int(delivery_time * 1000),
            )
            notification_type = notification.tags[0] if notification.tags else "unknown"
            self.metrics.record_notification_sent(
                notification_type, channel=notification.channel, severity=notification.severity
            )
            self.metrics.record_notification_delivery_time(
                delivery_time, notification_type, channel=notification.channel
            )
            return True
        except Exception as last_error:
            await self.repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(
                    status=NotificationStatus.FAILED,
                    failed_at=datetime.now(UTC),
                    error_message=f"Delivery failed via {notification.channel}: {last_error}",
                    retry_count=notification.max_retries,
                ),
            )
            notification_type = notification.tags[0] if notification.tags else "unknown"
            self.metrics.record_notification_failed(notification_type, str(last_error), channel=notification.channel)
            self.logger.error(
                f"All delivery attempts exhausted for {notification.notification_id}: {last_error}",
                exc_info=last_error,
            )
            return False
