"""Notification Service - stateless event handler.

Handles notification creation and delivery. Receives events,
processes them, and delivers notifications. No lifecycle management.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx

from app.core.metrics import NotificationMetrics
from app.core.tracing.utils import add_span_attributes
from app.db.repositories.notification_repository import NotificationRepository
from app.domain.enums.notification import (
    NotificationChannel,
    NotificationSeverity,
    NotificationStatus,
)
from app.domain.enums.user import UserRole
from app.domain.events.typed import (
    DomainEvent,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.domain.notification import (
    DomainNotification,
    DomainNotificationCreate,
    DomainNotificationListResult,
    DomainNotificationSubscription,
    DomainNotificationUpdate,
    DomainSubscriptionUpdate,
    NotificationNotFoundError,
    NotificationThrottledError,
    NotificationValidationError,
)
from app.schemas_pydantic.sse import RedisNotificationMessage
from app.services.event_bus import EventBus
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings

ENTITY_EXECUTION_TAG = "entity:execution"


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

            self._entries[key] = [ts for ts in self._entries[key] if ts > window_start]

            if len(self._entries[key]) >= max_per_hour:
                return True

            self._entries[key].append(now)
            return False

    async def clear(self) -> None:
        """Clear all throttle entries."""
        async with self._lock:
            self._entries.clear()


@dataclass(frozen=True)
class SystemConfig:
    severity: NotificationSeverity
    throttle_exempt: bool


class NotificationService:
    """Stateless notification service - pure event handler.

    No lifecycle methods (start/stop) - receives ready-to-use dependencies from DI.
    Worker entrypoint handles the consume loop.
    """

    def __init__(
            self,
            notification_repository: NotificationRepository,
            event_bus: EventBus,
            sse_bus: SSERedisBus,
            settings: Settings,
            logger: logging.Logger,
            notification_metrics: NotificationMetrics,
    ) -> None:
        self._repository = notification_repository
        self._event_bus = event_bus
        self._sse_bus = sse_bus
        self._settings = settings
        self._logger = logger
        self._metrics = notification_metrics
        self._throttle_cache = ThrottleCache()

        self._channel_handlers: dict[NotificationChannel, object] = {
            NotificationChannel.IN_APP: self._send_in_app,
            NotificationChannel.WEBHOOK: self._send_webhook,
            NotificationChannel.SLACK: self._send_slack,
        }

        self._logger.info("NotificationService initialized")

    async def handle_execution_event(self, event: DomainEvent) -> None:
        """Handle execution result events.

        Called by worker entrypoint for each event.
        """
        try:
            if isinstance(event, ExecutionCompletedEvent):
                await self._handle_execution_completed(event)
            elif isinstance(event, ExecutionFailedEvent):
                await self._handle_execution_failed(event)
            elif isinstance(event, ExecutionTimeoutEvent):
                await self._handle_execution_timeout(event)
            else:
                self._logger.warning(f"Unhandled execution event type: {event.event_type}")
        except Exception as e:
            self._logger.error(f"Error handling execution event: {e}", exc_info=True)

    async def _handle_execution_completed(self, event: ExecutionCompletedEvent) -> None:
        """Handle execution completed event."""
        user_id = event.metadata.user_id
        if not user_id:
            self._logger.error("No user_id in event metadata")
            return

        title = f"Execution Completed: {event.execution_id}"
        duration = event.resource_usage.execution_time_wall_seconds if event.resource_usage else 0.0
        body = f"Your execution completed successfully. Duration: {duration:.2f}s."
        await self.create_notification(
            user_id=user_id,
            subject=title,
            body=body,
            severity=NotificationSeverity.MEDIUM,
            tags=["execution", "completed", ENTITY_EXECUTION_TAG, f"exec:{event.execution_id}"],
            metadata=event.model_dump(
                exclude={"metadata", "event_type", "event_version", "timestamp", "aggregate_id", "topic"}
            ),
        )

    async def _handle_execution_failed(self, event: ExecutionFailedEvent) -> None:
        """Handle execution failed event."""
        user_id = event.metadata.user_id
        if not user_id:
            self._logger.error("No user_id in event metadata")
            return

        event_data = event.model_dump(
            exclude={"metadata", "event_type", "event_version", "timestamp", "aggregate_id", "topic"}
        )
        event_data["stdout"] = event_data["stdout"][:200]
        event_data["stderr"] = event_data["stderr"][:200]

        title = f"Execution Failed: {event.execution_id}"
        body = f"Your execution failed: {event.error_message}"
        await self.create_notification(
            user_id=user_id,
            subject=title,
            body=body,
            severity=NotificationSeverity.HIGH,
            tags=["execution", "failed", ENTITY_EXECUTION_TAG, f"exec:{event.execution_id}"],
            metadata=event_data,
        )

    async def _handle_execution_timeout(self, event: ExecutionTimeoutEvent) -> None:
        """Handle execution timeout event."""
        user_id = event.metadata.user_id
        if not user_id:
            self._logger.error("No user_id in event metadata")
            return

        title = f"Execution Timeout: {event.execution_id}"
        body = f"Your execution timed out after {event.timeout_seconds}s."
        await self.create_notification(
            user_id=user_id,
            subject=title,
            body=body,
            severity=NotificationSeverity.HIGH,
            tags=["execution", "timeout", ENTITY_EXECUTION_TAG, f"exec:{event.execution_id}"],
            metadata=event.model_dump(
                exclude={"metadata", "event_type", "event_version", "timestamp", "aggregate_id", "topic"}
            ),
        )

    async def create_notification(
            self,
            user_id: str,
            subject: str,
            body: str,
            tags: list[str],
            severity: NotificationSeverity = NotificationSeverity.MEDIUM,
            channel: NotificationChannel = NotificationChannel.IN_APP,
            scheduled_for: datetime | None = None,
            action_url: str | None = None,
            metadata: dict[str, object] | None = None,
    ) -> DomainNotification:
        """Create a new notification."""
        if not tags:
            raise NotificationValidationError("tags must be a non-empty list")

        self._logger.info(
            f"Creating notification for user {user_id}",
            extra={
                "user_id": user_id,
                "channel": channel,
                "severity": str(severity),
                "tags": list(tags),
                "scheduled": scheduled_for is not None,
            },
        )

        if await self._throttle_cache.check_throttle(
                user_id,
                severity,
                window_hours=self._settings.NOTIF_THROTTLE_WINDOW_HOURS,
                max_per_hour=self._settings.NOTIF_THROTTLE_MAX_PER_HOUR,
        ):
            error_msg = (
                f"Notification rate limit exceeded for user {user_id}. "
                f"Max {self._settings.NOTIF_THROTTLE_MAX_PER_HOUR} "
                f"per {self._settings.NOTIF_THROTTLE_WINDOW_HOURS} hour(s)"
            )
            self._logger.warning(error_msg)
            raise NotificationThrottledError(
                user_id,
                self._settings.NOTIF_THROTTLE_MAX_PER_HOUR,
                self._settings.NOTIF_THROTTLE_WINDOW_HOURS,
            )

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

        notification = await self._repository.create_notification(create_data)

        await self._event_bus.publish(
            "notifications.created",
            {
                "notification_id": str(notification.notification_id),
                "user_id": user_id,
                "severity": str(severity),
                "tags": notification.tags,
            },
        )

        await self._deliver_notification(notification)

        return notification

    async def create_system_notification(
            self,
            title: str,
            message: str,
            severity: NotificationSeverity = NotificationSeverity.MEDIUM,
            tags: list[str] | None = None,
            metadata: dict[str, object] | None = None,
            target_users: list[str] | None = None,
            target_roles: list[UserRole] | None = None,
    ) -> dict[str, int]:
        """Create system notifications with streamlined control flow."""
        cfg = SystemConfig(
            severity=severity,
            throttle_exempt=(severity in (NotificationSeverity.HIGH, NotificationSeverity.URGENT)),
        )
        base_context: dict[str, object] = {"message": message, **(metadata or {})}
        users = await self._resolve_targets(target_users, target_roles)

        if not users:
            return {"total_users": 0, "created": 0, "failed": 0, "throttled": 0}

        sem = asyncio.Semaphore(20)

        async def worker(uid: str) -> str:
            async with sem:
                return await self._create_system_for_user(uid, cfg, title, base_context, tags or ["system"])

        results = (
            [await worker(u) for u in users]
            if len(users) <= 20
            else await asyncio.gather(*(worker(u) for u in users))
        )

        created = sum(1 for r in results if r == "created")
        throttled = sum(1 for r in results if r == "throttled")
        failed = sum(1 for r in results if r == "failed")

        self._logger.info(
            "System notification completed",
            extra={
                "severity": cfg.severity,
                "title": title,
                "total_users": len(users),
                "created": created,
                "failed": failed,
                "throttled": throttled,
            },
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
            return await self._repository.get_users_by_roles(target_roles)
        return await self._repository.get_active_users(days=30)

    async def _create_system_for_user(
            self,
            user_id: str,
            cfg: SystemConfig,
            title: str,
            base_context: dict[str, object],
            tags: list[str],
    ) -> str:
        try:
            if not cfg.throttle_exempt:
                throttled = await self._throttle_cache.check_throttle(
                    user_id,
                    cfg.severity,
                    window_hours=self._settings.NOTIF_THROTTLE_WINDOW_HOURS,
                    max_per_hour=self._settings.NOTIF_THROTTLE_MAX_PER_HOUR,
                )
                if throttled:
                    return "throttled"

            await self.create_notification(
                user_id=user_id,
                subject=title,
                body=str(base_context.get("message", "Alert")),
                severity=cfg.severity,
                tags=tags,
                channel=NotificationChannel.IN_APP,
                metadata=base_context,
            )
            return "created"
        except Exception as e:
            self._logger.error(
                "Failed to create system notification for user",
                extra={"user_id": user_id, "error": str(e)},
            )
            return "failed"

    async def _send_in_app(
            self,
            notification: DomainNotification,
            subscription: DomainNotificationSubscription,
    ) -> None:
        """Send in-app notification via SSE bus."""
        await self._publish_notification_sse(notification)

    async def _send_webhook(
            self,
            notification: DomainNotification,
            subscription: DomainNotificationSubscription,
    ) -> None:
        """Send webhook notification."""
        webhook_url = notification.webhook_url or subscription.webhook_url
        if not webhook_url:
            raise ValueError(f"No webhook URL configured for user {notification.user_id}")

        payload = {
            "notification_id": str(notification.notification_id),
            "severity": str(notification.severity),
            "tags": list(notification.tags or []),
            "subject": notification.subject,
            "body": notification.body,
            "timestamp": notification.created_at.timestamp(),
        }

        if notification.action_url:
            payload["action_url"] = notification.action_url

        headers = notification.webhook_headers or {}
        headers["Content-Type"] = "application/json"

        add_span_attributes(
            **{
                "notification.id": str(notification.notification_id),
                "notification.channel": "webhook",
                "notification.webhook_url": webhook_url,
            }
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(webhook_url, json=payload, headers=headers, timeout=30.0)
            response.raise_for_status()

    async def _send_slack(
            self,
            notification: DomainNotification,
            subscription: DomainNotificationSubscription,
    ) -> None:
        """Send Slack notification."""
        if not subscription.slack_webhook:
            raise ValueError(f"No Slack webhook URL configured for user {notification.user_id}")

        slack_message: dict[str, object] = {
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

        if notification.action_url:
            attachments = slack_message.get("attachments", [])
            if attachments and isinstance(attachments, list):
                attachments[0]["actions"] = [
                    {"type": "button", "text": "View Details", "url": notification.action_url}
                ]

        add_span_attributes(
            **{
                "notification.id": str(notification.notification_id),
                "notification.channel": "slack",
            }
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(subscription.slack_webhook, json=slack_message, timeout=30.0)
            response.raise_for_status()

    def _get_slack_color(self, priority: NotificationSeverity) -> str:
        """Get Slack color based on severity."""
        return {
            NotificationSeverity.LOW: "#36a64f",
            NotificationSeverity.MEDIUM: "#ff9900",
            NotificationSeverity.HIGH: "#ff0000",
            NotificationSeverity.URGENT: "#990000",
        }.get(priority, "#808080")

    async def process_pending_notifications(self, batch_size: int = 10) -> int:
        """Process pending notifications.

        Should be called periodically from worker entrypoint.
        Returns number of notifications processed.
        """
        notifications = await self._repository.find_pending_notifications(batch_size=batch_size)
        count = 0

        for notification in notifications:
            await self._deliver_notification(notification)
            count += 1

        return count

    async def cleanup_old_notifications(self, days: int = 30) -> int:
        """Cleanup old notifications.

        Should be called periodically from worker entrypoint.
        Returns number of notifications deleted.
        """
        return await self._repository.cleanup_old_notifications(days)

    async def _should_skip_notification(
            self,
            notification: DomainNotification,
            subscription: DomainNotificationSubscription,
    ) -> str | None:
        """Check if notification should be skipped based on subscription filters."""
        if not subscription.enabled:
            return f"User {notification.user_id} has {notification.channel} disabled"

        if subscription.severities and notification.severity not in subscription.severities:
            return f"Notification severity '{notification.severity}' filtered by user preferences"

        if subscription.include_tags and not any(
                tag in subscription.include_tags for tag in (notification.tags or [])
        ):
            return f"Notification tags {notification.tags} not in include list"

        if subscription.exclude_tags and any(
                tag in subscription.exclude_tags for tag in (notification.tags or [])
        ):
            return f"Notification tags {notification.tags} excluded by preferences"

        return None

    async def _deliver_notification(self, notification: DomainNotification) -> None:
        """Deliver notification through configured channel."""
        claimed = await self._repository.try_claim_pending(notification.notification_id)
        if not claimed:
            return

        self._logger.info(
            f"Delivering notification {notification.notification_id}",
            extra={
                "notification_id": str(notification.notification_id),
                "user_id": notification.user_id,
                "channel": notification.channel,
                "severity": notification.severity,
                "tags": list(notification.tags or []),
            },
        )

        subscription = await self._repository.get_subscription(notification.user_id, notification.channel)

        skip_reason = await self._should_skip_notification(notification, subscription)
        if skip_reason:
            self._logger.info(skip_reason)
            await self._repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(status=NotificationStatus.SKIPPED, error_message=skip_reason),
            )
            return

        start_time = asyncio.get_running_loop().time()
        try:
            handler = self._channel_handlers.get(notification.channel)
            if handler is None:
                raise ValueError(f"No handler configured for channel: {notification.channel}")

            await handler(notification, subscription)  # type: ignore
            delivery_time = asyncio.get_running_loop().time() - start_time

            await self._repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(status=NotificationStatus.DELIVERED, delivered_at=datetime.now(UTC)),
            )

            self._logger.info(
                f"Successfully delivered notification {notification.notification_id}",
                extra={
                    "notification_id": str(notification.notification_id),
                    "channel": notification.channel,
                    "delivery_time_ms": int(delivery_time * 1000),
                },
            )

            self._metrics.record_notification_sent(
                notification.severity, channel=notification.channel, severity=notification.severity
            )
            self._metrics.record_notification_delivery_time(delivery_time, notification.severity)

        except Exception as e:
            self._logger.error(
                f"Failed to deliver notification {notification.notification_id}: {str(e)}",
                exc_info=True,
            )

            new_retry_count = notification.retry_count + 1
            error_message = f"Delivery failed via {notification.channel}: {str(e)}"
            failed_at = datetime.now(UTC)

            notif_status = NotificationStatus.PENDING \
                if new_retry_count < notification.max_retries else NotificationStatus.FAILED
            await self._repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(
                    status=notif_status,
                    failed_at=failed_at,
                    error_message=error_message,
                    retry_count=new_retry_count,
                ),
            )

    async def _publish_notification_sse(self, notification: DomainNotification) -> None:
        """Publish an in-app notification to the SSE bus."""
        message = RedisNotificationMessage(
            notification_id=notification.notification_id,
            severity=notification.severity,
            status=notification.status,
            tags=list(notification.tags or []),
            subject=notification.subject,
            body=notification.body,
            action_url=notification.action_url or "",
            created_at=notification.created_at,
        )
        await self._sse_bus.publish_notification(notification.user_id, message)

    async def mark_as_read(self, user_id: str, notification_id: str) -> bool:
        """Mark notification as read."""
        success = await self._repository.mark_as_read(notification_id, user_id)

        if success:
            await self._event_bus.publish(
                "notifications.read",
                {
                    "notification_id": str(notification_id),
                    "user_id": user_id,
                    "read_at": datetime.now(UTC).isoformat(),
                },
            )
        else:
            raise NotificationNotFoundError(notification_id)

        return True

    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications."""
        return await self._repository.get_unread_count(user_id)

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
        notifications = await self._repository.list_notifications(
            user_id=user_id,
            status=status,
            skip=offset,
            limit=limit,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
            tag_prefix=tag_prefix,
        )

        total, unread_count = await asyncio.gather(
            self._repository.count_notifications(
                user_id=user_id,
                status=status,
                include_tags=include_tags,
                exclude_tags=exclude_tags,
                tag_prefix=tag_prefix,
            ),
            self.get_unread_count(user_id),
        )

        return DomainNotificationListResult(
            notifications=notifications,
            total=total,
            unread_count=unread_count,
        )

    async def update_subscription(
            self,
            user_id: str,
            channel: NotificationChannel,
            enabled: bool,
            webhook_url: str | None = None,
            slack_webhook: str | None = None,
            severities: list[NotificationSeverity] | None = None,
            include_tags: list[str] | None = None,
            exclude_tags: list[str] | None = None,
    ) -> DomainNotificationSubscription:
        """Update notification subscription preferences."""
        if channel == NotificationChannel.WEBHOOK and enabled:
            if not webhook_url:
                raise NotificationValidationError("webhook_url is required when enabling WEBHOOK")
            if not (webhook_url.startswith("http://") or webhook_url.startswith("https://")):
                raise NotificationValidationError("webhook_url must start with http:// or https://")
        if channel == NotificationChannel.SLACK and enabled:
            if not slack_webhook:
                raise NotificationValidationError("slack_webhook is required when enabling SLACK")
            if not slack_webhook.startswith("https://hooks.slack.com/"):
                raise NotificationValidationError("slack_webhook must be a valid Slack webhook URL")

        update_data = DomainSubscriptionUpdate(
            enabled=enabled,
            webhook_url=webhook_url,
            slack_webhook=slack_webhook,
            severities=severities,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
        )

        return await self._repository.upsert_subscription(user_id, channel, update_data)

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        count = await self._repository.mark_all_as_read(user_id)

        if count > 0:
            await self._event_bus.publish(
                "notifications.all_read",
                {"user_id": user_id, "count": count, "read_at": datetime.now(UTC).isoformat()},
            )

        return count

    async def get_subscriptions(self, user_id: str) -> dict[NotificationChannel, DomainNotificationSubscription]:
        """Get all notification subscriptions for a user."""
        return await self._repository.get_all_subscriptions(user_id)

    async def delete_notification(self, user_id: str, notification_id: str) -> bool:
        """Delete a notification."""
        deleted = await self._repository.delete_notification(str(notification_id), user_id)
        if not deleted:
            raise NotificationNotFoundError(notification_id)
        return deleted
