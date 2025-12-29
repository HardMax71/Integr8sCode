import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import auto
from typing import Awaitable, Callable

import httpx

from app.core.metrics.context import get_notification_metrics
from app.core.tracing.utils import add_span_attributes
from app.core.utils import StringEnum
from app.db.repositories.notification_repository import NotificationRepository
from app.domain.enums.events import EventType
from app.domain.enums.kafka import GroupId
from app.domain.enums.notification import (
    NotificationChannel,
    NotificationSeverity,
    NotificationStatus,
)
from app.domain.enums.user import UserRole
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
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.mappings import get_topic_for_event
from app.schemas_pydantic.sse import RedisNotificationMessage
from app.services.event_bus import EventBusManager
from app.services.kafka_event_service import KafkaEventService
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings, get_settings

# Constants
ENTITY_EXECUTION_TAG = "entity:execution"

# Type aliases
type EventPayload = dict[str, object]
type NotificationContext = dict[str, object]
type ChannelHandler = Callable[[DomainNotification, DomainNotificationSubscription], Awaitable[None]]
type SystemNotificationStats = dict[str, int]
type SlackMessage = dict[str, object]


class ServiceState(StringEnum):
    """Service lifecycle states."""

    IDLE = auto()
    INITIALIZING = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()


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


@dataclass(frozen=True)
class SystemConfig:
    severity: NotificationSeverity
    throttle_exempt: bool


class NotificationService:
    def __init__(
        self,
        notification_repository: NotificationRepository,
        event_service: KafkaEventService,
        event_bus_manager: EventBusManager,
        schema_registry_manager: SchemaRegistryManager,
        sse_bus: SSERedisBus,
        settings: Settings,
        logger: logging.Logger,
    ) -> None:
        self.repository = notification_repository
        self.event_service = event_service
        self.event_bus_manager = event_bus_manager
        self.metrics = get_notification_metrics()
        self.settings = settings
        self.schema_registry_manager = schema_registry_manager
        self.sse_bus = sse_bus
        self.logger = logger

        # State
        self._state = ServiceState.IDLE
        self._throttle_cache = ThrottleCache()

        # Tasks
        self._tasks: set[asyncio.Task[None]] = set()

        self._consumer: UnifiedConsumer | None = None
        self._dispatcher: EventDispatcher | None = None
        self._consumer_task: asyncio.Task[None] | None = None

        self.logger.info(
            "NotificationService initialized",
            extra={
                "repository": type(notification_repository).__name__,
                "event_service": type(event_service).__name__,
                "schema_registry": type(schema_registry_manager).__name__,
            },
        )

        # Channel handlers mapping
        self._channel_handlers: dict[NotificationChannel, ChannelHandler] = {
            NotificationChannel.IN_APP: self._send_in_app,
            NotificationChannel.WEBHOOK: self._send_webhook,
            NotificationChannel.SLACK: self._send_slack,
        }

    @property
    def state(self) -> ServiceState:
        return self._state

    def initialize(self) -> None:
        if self._state != ServiceState.IDLE:
            self.logger.warning(f"Cannot initialize in state: {self._state}")
            return

        self._state = ServiceState.INITIALIZING

        # Start processors
        self._state = ServiceState.RUNNING
        self._start_background_tasks()

        self.logger.info("Notification service initialized (without Kafka consumer)")

    async def shutdown(self) -> None:
        """Shutdown notification service."""
        if self._state == ServiceState.STOPPED:
            return

        self.logger.info("Shutting down notification service...")
        self._state = ServiceState.STOPPING

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for cancellation
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Stop consumer
        if self._consumer:
            await self._consumer.stop()

        # Clear cache
        await self._throttle_cache.clear()

        self._state = ServiceState.STOPPED
        self.logger.info("Notification service stopped")

    def _start_background_tasks(self) -> None:
        """Start background processing tasks."""
        tasks = [
            asyncio.create_task(self._process_pending_notifications()),
            asyncio.create_task(self._cleanup_old_notifications()),
        ]

        for task in tasks:
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events for notifications."""
        # Configure consumer for notification-relevant events
        consumer_config = ConsumerConfig(
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=f"{GroupId.NOTIFICATION_SERVICE}.{get_settings().KAFKA_GROUP_SUFFIX}",
            max_poll_records=10,
            enable_auto_commit=True,
            auto_offset_reset="latest",  # Only process new events
        )

        execution_results_topic = get_topic_for_event(EventType.EXECUTION_COMPLETED)

        # Log topics for debugging
        self.logger.info(f"Notification service will subscribe to topics: {execution_results_topic}")

        # Create dispatcher and register handlers for specific event types
        self._dispatcher = EventDispatcher()
        # Use a single handler for execution result events (simpler and less brittle)
        self._dispatcher.register_handler(EventType.EXECUTION_COMPLETED, self._handle_execution_event)
        self._dispatcher.register_handler(EventType.EXECUTION_FAILED, self._handle_execution_event)
        self._dispatcher.register_handler(EventType.EXECUTION_TIMEOUT, self._handle_execution_event)

        # Create consumer with dispatcher
        self._consumer = UnifiedConsumer(consumer_config, event_dispatcher=self._dispatcher)

        # Start consumer
        await self._consumer.start([execution_results_topic])

        # Start consumer task
        self._consumer_task = asyncio.create_task(self._run_consumer())
        self._tasks.add(self._consumer_task)
        self._consumer_task.add_done_callback(self._tasks.discard)

        self.logger.info("Notification service subscribed to execution events")

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
        metadata: NotificationContext | None = None,
    ) -> DomainNotification:
        if not tags:
            raise NotificationValidationError("tags must be a non-empty list")
        self.logger.info(
            f"Creating notification for user {user_id}",
            extra={
                "user_id": user_id,
                "channel": channel,
                "severity": str(severity),
                "tags": list(tags),
                "scheduled": scheduled_for is not None,
            },
        )

        # Check throttling
        if await self._throttle_cache.check_throttle(
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

        # Publish event
        event_bus = await self.event_bus_manager.get_event_bus()
        await event_bus.publish(
            "notifications.created",
            {
                "notification_id": str(notification.notification_id),
                "user_id": user_id,
                "severity": str(severity),
                "tags": notification.tags,
            },
        )

        asyncio.create_task(self._deliver_notification(notification))

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
            extra={
                "severity": str(cfg.severity),
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
        if target_users:
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
                severity=cfg.severity,
                tags=tags,
                channel=NotificationChannel.IN_APP,
                metadata=base_context,
            )
            return "created"
        except Exception as e:
            self.logger.error("Failed to create system notification for user", extra={"user_id": user_id, "error": str(e)})
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

        self.logger.debug(
            f"Sending webhook notification to {webhook_url}",
            extra={
                "notification_id": str(notification.notification_id),
                "payload_size": len(str(payload)),
                "webhook_url": webhook_url,
            },
        )

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
            self.logger.debug(
                "Webhook delivered successfully",
                extra={
                    "notification_id": str(notification.notification_id),
                    "status_code": response.status_code,
                    "response_time_ms": int(response.elapsed.total_seconds() * 1000),
                },
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
            extra={
                "notification_id": str(notification.notification_id),
                "has_action": notification.action_url is not None,
                "priority_color": self._get_slack_color(notification.severity),
            },
        )

        add_span_attributes(
            **{
                "notification.id": str(notification.notification_id),
                "notification.channel": "slack",
            }
        )
        async with httpx.AsyncClient() as client:
            response = await client.post(subscription.slack_webhook, json=slack_message, timeout=30.0)
            response.raise_for_status()
            self.logger.debug(
                "Slack notification delivered successfully",
                extra={"notification_id": str(notification.notification_id), "status_code": response.status_code},
            )

    def _get_slack_color(self, priority: NotificationSeverity) -> str:
        """Get Slack color based on severity."""
        return {
            NotificationSeverity.LOW: "#36a64f",  # Green
            NotificationSeverity.MEDIUM: "#ff9900",  # Orange
            NotificationSeverity.HIGH: "#ff0000",  # Red
            NotificationSeverity.URGENT: "#990000",  # Dark Red
        }.get(priority, "#808080")  # Default gray

    async def _process_pending_notifications(self) -> None:
        """Process pending notifications in background."""
        while self._state == ServiceState.RUNNING:
            try:
                # Find pending notifications
                notifications = await self.repository.find_pending_notifications(
                    batch_size=self.settings.NOTIF_PENDING_BATCH_SIZE
                )

                # Process each notification
                for notification in notifications:
                    if self._state != ServiceState.RUNNING:
                        break
                    await self._deliver_notification(notification)

                # Sleep between batches
                await asyncio.sleep(5)

            except Exception as e:
                self.logger.error(f"Error processing pending notifications: {e}")
                await asyncio.sleep(10)

    async def _cleanup_old_notifications(self) -> None:
        """Cleanup old notifications periodically."""
        while self._state == ServiceState.RUNNING:
            try:
                # Run cleanup once per day
                await asyncio.sleep(86400)  # 24 hours

                if self._state != ServiceState.RUNNING:
                    break

                # Delete old notifications
                deleted_count = await self.repository.cleanup_old_notifications(self.settings.NOTIF_OLD_DAYS)

                self.logger.info(f"Cleaned up {deleted_count} old notifications")

            except Exception as e:
                self.logger.error(f"Error cleaning up old notifications: {e}")

    async def _run_consumer(self) -> None:
        """Run the event consumer loop."""
        while self._state == ServiceState.RUNNING:
            try:
                # Consumer handles polling internally
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                self.logger.info("Notification consumer task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Error in notification consumer loop: {e}")
                await asyncio.sleep(5)

    async def _handle_execution_timeout_typed(self, event: ExecutionTimeoutEvent) -> None:
        """Handle typed execution timeout event."""
        user_id = event.metadata.user_id
        if not user_id:
            self.logger.error("No user_id in event metadata")
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

    async def _handle_execution_completed_typed(self, event: ExecutionCompletedEvent) -> None:
        """Handle typed execution completed event."""
        user_id = event.metadata.user_id
        if not user_id:
            self.logger.error("No user_id in event metadata")
            return

        title = f"Execution Completed: {event.execution_id}"
        body = (
            f"Your execution completed successfully. Duration: {event.resource_usage.execution_time_wall_seconds:.2f}s."
        )
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

    async def _handle_execution_event(self, event: BaseEvent) -> None:
        """Unified handler for execution result events."""
        try:
            if isinstance(event, ExecutionCompletedEvent):
                await self._handle_execution_completed_typed(event)
            elif isinstance(event, ExecutionFailedEvent):
                await self._handle_execution_failed_typed(event)
            elif isinstance(event, ExecutionTimeoutEvent):
                await self._handle_execution_timeout_typed(event)
            else:
                self.logger.warning(f"Unhandled execution event type: {event.event_type}")
        except Exception as e:
            self.logger.error(f"Error handling execution event: {e}", exc_info=True)

    async def _handle_execution_failed_typed(self, event: ExecutionFailedEvent) -> None:
        """Handle typed execution failed event."""
        user_id = event.metadata.user_id
        if not user_id:
            self.logger.error("No user_id in event metadata")
            return

        # Use model_dump to get all event data
        event_data = event.model_dump(
            exclude={"metadata", "event_type", "event_version", "timestamp", "aggregate_id", "topic"}
        )

        # Truncate stdout/stderr for notification context
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

    async def mark_as_read(self, user_id: str, notification_id: str) -> bool:
        """Mark notification as read."""
        success = await self.repository.mark_as_read(notification_id, user_id)

        event_bus = await self.event_bus_manager.get_event_bus()
        if success:
            await event_bus.publish(
                "notifications.read",
                {"notification_id": str(notification_id), "user_id": user_id, "read_at": datetime.now(UTC).isoformat()},
            )
        else:
            raise NotificationNotFoundError(notification_id)

        return True

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
            self.repository.count_notifications(user_id, {"status": status}), self.get_unread_count(user_id)
        )

        return DomainNotificationListResult(notifications=notifications, total=total, unread_count=unread_count)

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
        # Validate channel-specific requirements
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

        # Build update data
        update_data = DomainSubscriptionUpdate(
            enabled=enabled,
            webhook_url=webhook_url,
            slack_webhook=slack_webhook,
            severities=severities,
            include_tags=include_tags,
            exclude_tags=exclude_tags,
        )

        return await self.repository.upsert_subscription(user_id, channel, update_data)

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        count = await self.repository.mark_all_as_read(user_id)

        event_bus = await self.event_bus_manager.get_event_bus()
        if count > 0:
            await event_bus.publish(
                "notifications.all_read", {"user_id": user_id, "count": count, "read_at": datetime.now(UTC).isoformat()}
            )

        return count

    async def get_subscriptions(self, user_id: str) -> dict[NotificationChannel, DomainNotificationSubscription]:
        """Get all notification subscriptions for a user."""
        return await self.repository.get_all_subscriptions(user_id)

    async def delete_notification(self, user_id: str, notification_id: str) -> bool:
        """Delete a notification."""
        deleted = await self.repository.delete_notification(str(notification_id), user_id)
        if not deleted:
            raise NotificationNotFoundError(notification_id)
        return deleted

    async def _publish_notification_sse(self, notification: DomainNotification) -> None:
        """Publish an in-app notification to the SSE bus for realtime delivery."""
        message = RedisNotificationMessage(
            notification_id=notification.notification_id,
            severity=notification.severity,
            status=notification.status,
            tags=list(notification.tags or []),
            subject=notification.subject,
            body=notification.body,
            action_url=notification.action_url or "",
            created_at=notification.created_at.isoformat(),
        )
        await self.sse_bus.publish_notification(notification.user_id, message)

    async def _should_skip_notification(
        self, notification: DomainNotification, subscription: DomainNotificationSubscription | None
    ) -> str | None:
        """Check if notification should be skipped based on subscription filters.

        Returns skip reason if should skip, None otherwise.
        """
        if not subscription or not subscription.enabled:
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

    async def _deliver_notification(self, notification: DomainNotification) -> None:
        """Deliver notification through configured channel using safe state transitions."""
        # Attempt to claim this notification for sending
        claimed = await self.repository.try_claim_pending(notification.notification_id)
        if not claimed:
            return

        self.logger.info(
            f"Delivering notification {notification.notification_id}",
            extra={
                "notification_id": str(notification.notification_id),
                "user_id": notification.user_id,
                "channel": str(notification.channel),
                "severity": str(notification.severity),
                "tags": list(notification.tags or []),
            },
        )

        # Check user subscription for the channel
        subscription = await self.repository.get_subscription(notification.user_id, notification.channel)

        # Check if notification should be skipped
        skip_reason = await self._should_skip_notification(notification, subscription)
        if skip_reason:
            self.logger.info(skip_reason)
            await self.repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(status=NotificationStatus.SKIPPED, error_message=skip_reason),
            )
            return

        # At this point, subscription is guaranteed to be non-None (checked in _should_skip_notification)
        assert subscription is not None

        # Send through channel
        start_time = asyncio.get_event_loop().time()
        try:
            handler = self._channel_handlers.get(notification.channel)
            if handler is None:
                raise ValueError(
                    f"No handler configured for notification channel: {notification.channel}. "
                    f"Available channels: {list(self._channel_handlers.keys())}"
                )

            self.logger.debug(f"Using handler {handler.__name__} for channel {notification.channel}")
            await handler(notification, subscription)
            delivery_time = asyncio.get_event_loop().time() - start_time

            # Mark delivered
            await self.repository.update_notification(
                notification.notification_id,
                notification.user_id,
                DomainNotificationUpdate(status=NotificationStatus.DELIVERED, delivered_at=datetime.now(UTC)),
            )

            self.logger.info(
                f"Successfully delivered notification {notification.notification_id}",
                extra={
                    "notification_id": str(notification.notification_id),
                    "channel": str(notification.channel),
                    "delivery_time_ms": int(delivery_time * 1000),
                },
            )

            # Metrics (use tag string or severity)
            self.metrics.record_notification_sent(
                str(notification.severity), channel=str(notification.channel), severity=str(notification.severity)
            )
            self.metrics.record_notification_delivery_time(delivery_time, str(notification.severity))

        except Exception as e:
            error_details = {
                "notification_id": str(notification.notification_id),
                "channel": str(notification.channel),
                "error_type": type(e).__name__,
                "error_message": str(e),
                "retry_count": notification.retry_count,
                "max_retries": notification.max_retries,
            }

            self.logger.error(
                f"Failed to deliver notification {notification.notification_id}: {str(e)}",
                extra=error_details,
                exc_info=True,
            )

            new_retry_count = notification.retry_count + 1
            error_message = f"Delivery failed via {notification.channel}: {str(e)}"
            failed_at = datetime.now(UTC)

            # Schedule retry if under limit
            if new_retry_count < notification.max_retries:
                retry_time = datetime.now(UTC) + timedelta(minutes=self.settings.NOTIF_RETRY_DELAY_MINUTES)
                self.logger.info(
                    f"Scheduled retry {new_retry_count}/{notification.max_retries} "
                    f"for {notification.notification_id}",
                    extra={"retry_at": retry_time.isoformat()},
                )
                # Will be retried - keep as PENDING but with scheduled_for
                # Note: scheduled_for not in DomainNotificationUpdate, so we update status fields only
                await self.repository.update_notification(
                    notification.notification_id,
                    notification.user_id,
                    DomainNotificationUpdate(
                        status=NotificationStatus.PENDING,
                        failed_at=failed_at,
                        error_message=error_message,
                        retry_count=new_retry_count,
                    ),
                )
            else:
                await self.repository.update_notification(
                    notification.notification_id,
                    notification.user_id,
                    DomainNotificationUpdate(
                        status=NotificationStatus.FAILED,
                        failed_at=failed_at,
                        error_message=error_message,
                        retry_count=new_retry_count,
                    ),
                )
