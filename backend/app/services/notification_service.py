"""Event-driven notification service using modern Python 3.12+ patterns.

This service manages notifications across multiple channels (in-app, webhook, Slack)
with event-driven architecture and throttling support.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum, auto
from typing import Any, Protocol, cast

import httpx
from jinja2 import Template

from app.config import get_settings
from app.core.logging import logger
from app.core.metrics import NOTIFICATION_DELIVERY_TIME, NOTIFICATIONS_FAILED, NOTIFICATIONS_SENT
from app.db.repositories.notification_repository import NotificationRepository
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.consumer_group_names import GroupId
from app.events.schema.schema_registry import SchemaRegistryManager
from app.schemas_avro.event_schemas import (
    EventType,
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
    get_topic_for_event,
)
from app.schemas_pydantic.notification import (
    Notification,
    NotificationChannel,
    NotificationListResponse,
    NotificationPriority,
    NotificationResponse,
    NotificationStatus,
    NotificationSubscription,
    NotificationTemplate,
    NotificationType,
    TestNotificationRequest,
)
from app.services.kafka_event_service import KafkaEventService

# Type aliases
type UserId = str
type NotificationId = str
type EventPayload = dict[str, Any]
type NotificationContext = dict[str, Any]
type ChannelHandler = Any  # Complex callable type
type ThrottleKey = str

# Constants
THROTTLE_WINDOW_HOURS: int = 1
THROTTLE_MAX_PER_HOUR: int = 5
PENDING_BATCH_SIZE: int = 10
OLD_NOTIFICATION_DAYS: int = 30
RETRY_DELAY_MINUTES: int = 5


class ServiceState(StrEnum):
    """Service lifecycle states."""
    IDLE = auto()
    INITIALIZING = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()


class ProcessingMode(StrEnum):
    """Processing modes for notifications."""
    IMMEDIATE = auto()
    SCHEDULED = auto()
    BATCH = auto()


@dataclass(frozen=True, slots=True)
class NotificationDelivery:
    """Immutable notification delivery result."""
    notification_id: NotificationId
    channel: NotificationChannel
    success: bool
    delivery_time_seconds: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ThrottleEntry:
    """Immutable throttle tracking entry."""
    timestamp: datetime
    notification_type: NotificationType


@dataclass
class ThrottleCache:
    """Manages notification throttling with time windows."""
    _entries: dict[ThrottleKey, list[datetime]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def check_throttle(
            self,
            user_id: UserId,
            notification_type: NotificationType
    ) -> bool:
        """Check if notification should be throttled."""
        key = f"{user_id}:{notification_type}"
        now = datetime.now(UTC)
        window_start = now - timedelta(hours=THROTTLE_WINDOW_HOURS)

        async with self._lock:
            if key not in self._entries:
                self._entries[key] = []

            # Clean old entries
            self._entries[key] = [
                ts for ts in self._entries[key]
                if ts > window_start
            ]

            # Check limit
            if len(self._entries[key]) >= THROTTLE_MAX_PER_HOUR:
                return True

            # Add new entry
            self._entries[key].append(now)
            return False

    async def clear(self) -> None:
        """Clear all throttle entries."""
        async with self._lock:
            self._entries.clear()


class EventBus(Protocol):
    """Protocol for event bus interface."""

    async def publish(self, topic: str, event: Any) -> None:
        """Publish event to topic."""
        ...


class NotificationService:
    """Service for managing event-driven notifications with modern patterns."""

    def __init__(
            self,
            notification_repository: NotificationRepository,
            event_service: KafkaEventService,
            event_bus_manager: Any = None,
            schema_registry_manager: SchemaRegistryManager | None = None
    ) -> None:
        """Initialize the notification service."""
        self.repository = notification_repository
        self.event_service = event_service
        self.event_bus_manager = event_bus_manager
        self.event_bus: EventBus | None = None
        self.settings = get_settings()
        self.schema_registry_manager = schema_registry_manager

        # State
        self._state = ServiceState.IDLE
        self._throttle_cache = ThrottleCache()

        # Tasks
        self._tasks: set[asyncio.Task[None]] = set()

        # Event consumer
        self._consumer: UnifiedConsumer | None = None
        self._consumer_task: asyncio.Task[None] | None = None

        # Channel handlers mapping
        self._channel_handlers: dict[NotificationChannel, ChannelHandler] = {
            NotificationChannel.IN_APP: self._send_in_app,
            NotificationChannel.WEBHOOK: self._send_webhook,
            NotificationChannel.SLACK: self._send_slack
        }

    @property
    def state(self) -> ServiceState:
        """Get current service state."""
        return self._state

    async def initialize(self) -> None:
        """Initialize notification service."""
        if self._state != ServiceState.IDLE:
            logger.warning(f"Cannot initialize in state: {self._state}")
            return

        self._state = ServiceState.INITIALIZING

        try:
            # Get event bus if available
            if self.event_bus_manager:
                self.event_bus = await self.event_bus_manager.get_event_bus()

            # Create indexes
            await self.repository.create_indexes()

            # Load templates
            await self._load_default_templates()

            # Start processors
            self._state = ServiceState.RUNNING
            self._start_background_tasks()

            # Subscribe to events (currently a no-op)
            await self._subscribe_to_events()

            logger.info("Notification service initialized")

        except Exception as e:
            self._state = ServiceState.IDLE
            logger.error(f"Failed to initialize notification service: {e}")
            raise

    async def shutdown(self) -> None:
        """Shutdown notification service."""
        if self._state == ServiceState.STOPPED:
            return

        logger.info("Shutting down notification service...")
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
        logger.info("Notification service stopped")

    async def _load_default_templates(self) -> None:
        """Load default notification templates."""
        templates = [
            NotificationTemplate(
                notification_type=NotificationType.EXECUTION_COMPLETED,
                subject_template="Execution Completed: {{ execution_id }}",
                body_template="Your code execution {{ execution_id }} completed successfully in {{ duration }}s.",
                channels=[NotificationChannel.IN_APP, NotificationChannel.WEBHOOK]
            ),
            NotificationTemplate(
                notification_type=NotificationType.EXECUTION_FAILED,
                subject_template="Execution Failed: {{ execution_id }}",
                body_template="Your code execution {{ execution_id }} failed: {{ error }}",
                channels=[NotificationChannel.IN_APP, NotificationChannel.WEBHOOK, NotificationChannel.SLACK],
                priority=NotificationPriority.HIGH
            ),
            NotificationTemplate(
                notification_type=NotificationType.EXECUTION_TIMEOUT,
                subject_template="Execution Timeout: {{ execution_id }}",
                body_template="Your code execution {{ execution_id }} timed out after {{ timeout }}s.",
                channels=[NotificationChannel.IN_APP, NotificationChannel.WEBHOOK],
                priority=NotificationPriority.HIGH
            ),
            NotificationTemplate(
                notification_type=NotificationType.SYSTEM_UPDATE,
                subject_template="System Update: {{ update_type }}",
                body_template="{{ message }}",
                channels=[NotificationChannel.IN_APP],
                priority=NotificationPriority.MEDIUM
            ),
            NotificationTemplate(
                notification_type=NotificationType.SECURITY_ALERT,
                subject_template="Security Alert: {{ alert_type }}",
                body_template="{{ message }}",
                channels=[NotificationChannel.IN_APP, NotificationChannel.SLACK],
                priority=NotificationPriority.URGENT
            )
        ]

        for template in templates:
            await self.repository.upsert_template(template)

        logger.info(f"Loaded {len(templates)} default notification templates")

    def _start_background_tasks(self) -> None:
        """Start background processing tasks."""
        tasks = [
            asyncio.create_task(self._process_pending_notifications()),
            asyncio.create_task(self._process_scheduled_notifications()),
            asyncio.create_task(self._cleanup_old_notifications())
        ]

        for task in tasks:
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _subscribe_to_events(self) -> None:
        """Subscribe to relevant events for notifications."""
        # Configure consumer for notification-relevant events
        consumer_config = ConsumerConfig(
            group_id=GroupId.NOTIFICATION_SERVICE,
            topics=[
                str(get_topic_for_event(EventType.EXECUTION_COMPLETED)),
                str(get_topic_for_event(EventType.EXECUTION_FAILED)),
                str(get_topic_for_event(EventType.EXECUTION_TIMEOUT)),
            ],
            max_poll_records=10,
            enable_auto_commit=True,
            auto_offset_reset="latest"  # Only process new events
        )

        # Create consumer
        self._consumer = UnifiedConsumer(consumer_config, self.schema_registry_manager)

        # Register event handlers
        self._consumer.register_handler(
            str(EventType.EXECUTION_COMPLETED),
            self._handle_execution_completed_event
        )
        self._consumer.register_handler(
            str(EventType.EXECUTION_FAILED),
            self._handle_execution_failed_event
        )
        self._consumer.register_handler(
            str(EventType.EXECUTION_TIMEOUT),
            self._handle_execution_timeout_event
        )

        # Start consumer
        await self._consumer.start()

        # Start consumer task
        self._consumer_task = asyncio.create_task(self._run_consumer())
        self._tasks.add(self._consumer_task)
        self._consumer_task.add_done_callback(self._tasks.discard)

        logger.info("Notification service subscribed to execution events")

    async def create_notification(
            self,
            user_id: UserId,
            notification_type: NotificationType,
            context: NotificationContext,
            channel: NotificationChannel | None = None,
            scheduled_for: datetime | None = None,
            priority: NotificationPriority | None = None,
            correlation_id: str | None = None,
            related_entity_id: str | None = None,
            related_entity_type: str | None = None
    ) -> Notification:
        """Create a new notification."""
        # Check throttling
        if await self._throttle_cache.check_throttle(user_id, notification_type):
            logger.warning(f"Notification throttled for user {user_id}, type {notification_type}")
            raise ValueError("Notification rate limit exceeded")

        # Get template
        template = await self.repository.get_template(notification_type)
        if not template:
            logger.error(f"No template found for notification type: {notification_type}")
            raise ValueError(f"No template for notification type: {notification_type}")

        # Render notification content
        subject = Template(template.subject_template).render(**context)
        body = Template(template.body_template).render(**context)
        action_url = None
        if template.action_url_template:
            action_url = Template(template.action_url_template).render(**context)

        # Use provided channel or first from template
        notification_channel = channel or template.channels[0]

        # Create notification
        notification = Notification(
            user_id=user_id,
            notification_type=notification_type,
            channel=notification_channel,
            subject=subject,
            body=body,
            action_url=action_url,
            priority=priority or template.priority,
            scheduled_for=scheduled_for,
            status=NotificationStatus.PENDING,
            correlation_id=correlation_id,
            related_entity_id=related_entity_id,
            related_entity_type=related_entity_type,
            metadata=context,
            created_at=datetime.now(UTC)
        )

        # Save to database
        await self.repository.create_notification(notification)

        # Publish event
        if self.event_bus:
            await self.event_bus.publish(
                "notifications.created",
                {
                    "notification_id": str(notification.notification_id),
                    "user_id": user_id,
                    "type": notification_type
                }
            )

        # Process immediately if not scheduled
        if not scheduled_for:
            asyncio.create_task(self._deliver_notification(notification))

        return notification

    async def create_system_notification(
            self,
            title: str,
            message: str,
            notification_type: str = "warning",
            metadata: dict[str, Any] | None = None,
            target_users: list[UserId] | None = None,
            target_roles: list[str] | None = None
    ) -> dict[str, Any]:
        """Create system-wide notifications for all users or specific user groups.
        
        Args:
            title: Notification title/subject
            message: Notification message body
            notification_type: Type of notification (error, warning, success, info)
            metadata: Additional metadata for the notification
            target_users: Specific users to notify (if None, notifies based on roles)
            target_roles: User roles to notify (if None and target_users is None, notifies all active users)
            
        Returns:
            Dictionary with creation statistics
        """
        # Map string notification type to enum
        type_mapping = {
            "error": NotificationType.SECURITY_ALERT,
            "critical": NotificationType.SECURITY_ALERT,
            "warning": NotificationType.SYSTEM_UPDATE,
            "success": NotificationType.SYSTEM_UPDATE,
            "info": NotificationType.SYSTEM_UPDATE
        }
        
        notification_enum = type_mapping.get(notification_type, NotificationType.SYSTEM_UPDATE)
        
        # Prepare notification context
        context: NotificationContext = {
            "update_type": notification_type.title(),
            "alert_type": notification_type.title(),
            "message": message,
            "timestamp": datetime.now(UTC).isoformat(),
            **(metadata or {})
        }
        
        # Determine target users
        users_to_notify: list[UserId] = []
        
        if target_users:
            users_to_notify = target_users
        else:
            # Get users based on roles or all active users
            if target_roles:
                # Fetch users with specific roles
                users_to_notify = await self.repository.get_users_by_roles(target_roles)
            else:
                # Get all active users (users who have logged in within last 30 days)
                users_to_notify = await self.repository.get_active_users(days=30)
        
        # Create notifications for each user
        created_count = 0
        failed_count = 0
        throttled_count = 0
        
        for user_id in users_to_notify:
            try:
                # Skip throttle check for critical alerts
                if notification_type not in ["error", "critical"]:
                    if await self._throttle_cache.check_throttle(user_id, notification_enum):
                        throttled_count += 1
                        continue
                
                # Override the title in context for proper template rendering
                context["update_type"] = title if notification_enum == NotificationType.SYSTEM_UPDATE \
                    else notification_type.title()
                context["alert_type"] = title if notification_enum == NotificationType.SECURITY_ALERT \
                    else notification_type.title()

                await self.create_notification(
                    user_id=user_id,
                    notification_type=notification_enum,
                    context=context,
                    channel=NotificationChannel.IN_APP,
                    priority=NotificationPriority.HIGH if notification_type in ["error", "critical"]
                    else NotificationPriority.MEDIUM,
                    correlation_id=metadata.get("correlation_id") if metadata else None,
                    related_entity_id=metadata.get("alert_fingerprint") if metadata else None,
                    related_entity_type="alertmanager_alert" if metadata and "alert_fingerprint" in metadata else None
                )
                created_count += 1
                
            except Exception as e:
                logger.error(f"Failed to create system notification for user {user_id}: {e}")
                failed_count += 1
        
        logger.info(
            f"System notification created: {created_count} sent, {failed_count} failed, {throttled_count} throttled",
            extra={
                "notification_type": notification_type,
                "title": title,
                "target_users_count": len(users_to_notify),
                "created_count": created_count,
                "failed_count": failed_count,
                "throttled_count": throttled_count
            }
        )
        
        return {
            "total_users": len(users_to_notify),
            "created": created_count,
            "failed": failed_count,
            "throttled": throttled_count
        }

    async def _deliver_notification(self, notification: Notification) -> None:
        """Deliver notification through configured channel."""
        # Check user subscription for the channel
        subscription = await self.repository.get_subscription(
            notification.user_id,
            notification.channel
        )

        if not subscription or not subscription.enabled:
            logger.info(f"User {notification.user_id} not subscribed to {notification.channel}")
            notification.status = NotificationStatus.FAILED
            notification.error_message = "User not subscribed to this channel"
            await self.repository.update_notification(notification)
            return

        # Check notification type filter
        if (subscription.notification_types and
                notification.notification_type not in subscription.notification_types):
            logger.info(f"Notification type {notification.notification_type} filtered for user {notification.user_id}")
            notification.status = NotificationStatus.FAILED
            notification.error_message = "Notification type filtered by user preferences"
            await self.repository.update_notification(notification)
            return

        # Send through channel
        start_time = asyncio.get_event_loop().time()
        try:
            handler = self._channel_handlers.get(notification.channel)
            if handler:
                await handler(notification, subscription)
                delivery_time = asyncio.get_event_loop().time() - start_time

                # Update status
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.now(UTC)

                # Metrics
                NOTIFICATIONS_SENT.labels(
                    channel=str(notification.channel),
                    notification_type=str(notification.notification_type)
                ).inc()
                NOTIFICATION_DELIVERY_TIME.labels(channel=str(notification.channel)).observe(delivery_time)
            else:
                raise ValueError(f"No handler for channel {notification.channel}")

        except Exception as e:
            logger.error(
                f"Failed to deliver notification {notification.notification_id} via {notification.channel}: {e}")

            notification.status = NotificationStatus.FAILED
            notification.failed_at = datetime.now(UTC)
            notification.error_message = str(e)
            notification.retry_count = notification.retry_count + 1

            # Schedule retry if under limit
            if notification.retry_count < notification.max_retries:
                notification.scheduled_for = datetime.now(UTC) + timedelta(minutes=RETRY_DELAY_MINUTES)
                notification.status = NotificationStatus.PENDING

            # Metrics
            NOTIFICATIONS_FAILED.labels(
                channel=str(notification.channel),
                notification_type=str(notification.notification_type),
                error_type=type(e).__name__
            ).inc()

        await self.repository.update_notification(notification)

    async def _send_in_app(
            self,
            notification: Notification,
            subscription: NotificationSubscription
    ) -> None:
        """Send in-app notification."""
        # In-app notifications are already stored, just update status
        notification.status = NotificationStatus.DELIVERED
        await self.repository.update_notification(notification)

    async def _send_webhook(
            self,
            notification: Notification,
            subscription: NotificationSubscription
    ) -> None:
        """Send webhook notification."""
        webhook_url = notification.webhook_url or subscription.webhook_url
        if not webhook_url:
            raise ValueError("No webhook URL configured")

        payload = {
            "notification_id": str(notification.notification_id),
            "type": str(notification.notification_type),
            "subject": notification.subject,
            "body": notification.body,
            "priority": str(notification.priority),
            "timestamp": notification.created_at.isoformat()
        }

        if notification.action_url:
            payload["action_url"] = notification.action_url
        if notification.related_entity_id:
            payload["related_entity_id"] = notification.related_entity_id
            payload["related_entity_type"] = notification.related_entity_type or ""

        headers = notification.webhook_headers or {}
        headers["Content-Type"] = "application/json"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                webhook_url,
                json=payload,
                headers=headers,
                timeout=30.0
            )
            response.raise_for_status()
            notification.delivered_at = datetime.now(UTC)
            notification.status = NotificationStatus.DELIVERED

    async def _send_slack(
            self,
            notification: Notification,
            subscription: NotificationSubscription
    ) -> None:
        """Send Slack notification."""
        if not subscription.slack_webhook:
            raise ValueError("No Slack webhook URL configured")

        # Format message for Slack
        slack_message: dict[str, Any] = {
            "text": notification.subject,
            "attachments": [{
                "color": self._get_slack_color(notification.priority),
                "text": notification.body,
                "footer": "Integr8sCode Notifications",
                "ts": int(notification.created_at.timestamp())
            }]
        }

        # Add action button if URL provided
        if notification.action_url:
            attachments = slack_message.get("attachments", [])
            if attachments and isinstance(attachments, list):
                attachments[0]["actions"] = [{
                "type": "button",
                "text": "View Details",
                "url": notification.action_url
            }]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                subscription.slack_webhook,
                json=slack_message,
                timeout=30.0
            )
            response.raise_for_status()
            notification.delivered_at = datetime.now(UTC)
            notification.status = NotificationStatus.DELIVERED

    def _get_slack_color(self, priority: NotificationPriority) -> str:
        """Get Slack color based on priority."""
        return {
            NotificationPriority.LOW: "#36a64f",  # Green
            NotificationPriority.MEDIUM: "#ff9900",  # Orange
            NotificationPriority.HIGH: "#ff0000",  # Red
            NotificationPriority.URGENT: "#990000"  # Dark Red
        }.get(priority, "#808080")  # Default gray

    async def _process_pending_notifications(self) -> None:
        """Process pending notifications in background."""
        while self._state == ServiceState.RUNNING:
            try:
                # Find pending notifications
                notifications = await self.repository.find_pending_notifications(
                    batch_size=PENDING_BATCH_SIZE
                )

                # Process each notification
                for notification in notifications:
                    if self._state != ServiceState.RUNNING:
                        break
                    await self._deliver_notification(notification)

                # Sleep between batches
                await asyncio.sleep(5)

            except Exception as e:
                logger.error(f"Error processing pending notifications: {e}")
                await asyncio.sleep(10)

    async def _process_scheduled_notifications(self) -> None:
        """Process scheduled notifications."""
        while self._state == ServiceState.RUNNING:
            try:
                # Find due scheduled notifications
                notifications = await self.repository.find_scheduled_notifications(
                    batch_size=PENDING_BATCH_SIZE
                )

                # Process each notification
                for notification in notifications:
                    if self._state != ServiceState.RUNNING:
                        break
                    await self._deliver_notification(notification)

                # Sleep between checks
                await asyncio.sleep(30)

            except Exception as e:
                logger.error(f"Error processing scheduled notifications: {e}")
                await asyncio.sleep(60)

    async def _cleanup_old_notifications(self) -> None:
        """Cleanup old notifications periodically."""
        while self._state == ServiceState.RUNNING:
            try:
                # Run cleanup once per day
                await asyncio.sleep(86400)  # 24 hours

                if self._state != ServiceState.RUNNING:
                    break

                # Delete old notifications
                deleted_count = await self.repository.cleanup_old_notifications(OLD_NOTIFICATION_DAYS)

                logger.info(f"Cleaned up {deleted_count} old notifications")

            except Exception as e:
                logger.error(f"Error cleaning up old notifications: {e}")

    # Event handlers

    async def _run_consumer(self) -> None:
        """Run the event consumer loop."""
        while self._state == ServiceState.RUNNING:
            try:
                # Consumer handles polling internally
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                logger.info("Notification consumer task cancelled")
                break
            except Exception as e:
                logger.error(f"Error in notification consumer loop: {e}")
                await asyncio.sleep(5)

    async def _handle_execution_timeout_event(
            self,
            event: Any,
            record: Any
    ) -> None:
        """Handle execution timeout event from Kafka."""
        if not isinstance(event, ExecutionTimeoutEvent):
            logger.error(f"Expected ExecutionTimeoutEvent, got {type(event)}")
            return
        event = cast(ExecutionTimeoutEvent, event)
        try:
            user_id = event.metadata.user_id
            if not user_id:
                logger.error("No user_id in event metadata")
                return
            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.EXECUTION_TIMEOUT,
                context={
                    "execution_id": event.execution_id,
                    "timeout": getattr(event, "timeout", 300)
                },
                priority=NotificationPriority.HIGH,
                correlation_id=getattr(event, "correlation_id", None),
                related_entity_id=event.execution_id,
                related_entity_type="execution"
            )
        except Exception as e:
            logger.error(f"Error handling execution timeout event: {e}")

    async def _handle_execution_completed_event(
            self,
            event: Any,
            record: Any
    ) -> None:
        """Handle execution completed event from Kafka."""
        if not isinstance(event, ExecutionCompletedEvent):
            logger.error(f"Expected ExecutionCompletedEvent, got {type(event)}")
            return
        event = cast(ExecutionCompletedEvent, event)
        try:
            user_id = event.metadata.user_id
            if not user_id:
                logger.error("No user_id in event metadata")
                return
            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.EXECUTION_COMPLETED,
                context={
                    "execution_id": event.execution_id,
                    "duration": getattr(event, "duration", 0),
                    "output": str(getattr(event, "output", ""))[:100]  # Truncate output
                },
                correlation_id=getattr(event, "correlation_id", None),
                related_entity_id=event.execution_id,
                related_entity_type="execution"
            )
        except Exception as e:
            logger.error(f"Error handling execution completed event: {e}")

    async def _handle_execution_failed_event(
            self,
            event: Any,
            record: Any
    ) -> None:
        """Handle execution failed event from Kafka."""
        if not isinstance(event, ExecutionFailedEvent):
            logger.error(f"Expected ExecutionFailedEvent, got {type(event)}")
            return
        event = cast(ExecutionFailedEvent, event)
        try:
            user_id = event.metadata.user_id
            if not user_id:
                logger.error("No user_id in event metadata")
                return
            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.EXECUTION_FAILED,
                context={
                    "execution_id": event.execution_id,
                    "error": getattr(event, "error", "Unknown error")
                },
                priority=NotificationPriority.HIGH,
                correlation_id=getattr(event, "correlation_id", None),
                related_entity_id=event.execution_id,
                related_entity_type="execution"
            )
        except Exception as e:
            logger.error(f"Error handling execution failed event: {e}")

    # Public API methods

    async def mark_as_read(self, user_id: UserId, notification_id: NotificationId) -> bool:
        """Mark notification as read."""
        try:
            success = await self.repository.mark_as_read(str(notification_id), user_id)

            if success and self.event_bus:
                await self.event_bus.publish(
                    "notifications.read",
                    {
                        "notification_id": str(notification_id),
                        "user_id": user_id,
                        "read_at": datetime.now(UTC).isoformat()
                    }
                )

            return success

        except Exception as e:
            logger.error(f"Error marking notification as read: {e}")
            return False

    async def get_notifications(
            self,
            user_id: UserId,
            status: NotificationStatus | None = None,
            limit: int = 20,
            offset: int = 0
    ) -> list[NotificationResponse]:
        """Get notifications for a user."""
        notifications = await self.repository.list_notifications(
            user_id=user_id,
            status=status,
            skip=offset,
            limit=limit
        )

        return [
            NotificationResponse.model_validate(n.model_dump())
            for n in notifications
        ]

    async def get_unread_count(self, user_id: UserId) -> int:
        """Get count of unread notifications."""
        return await self.repository.get_unread_count(user_id)

    async def list_notifications(
            self,
            user_id: UserId,
            status: NotificationStatus | None = None,
            limit: int = 20,
            offset: int = 0
    ) -> NotificationListResponse:
        """List notifications with pagination."""
        # Get notifications
        notifications = await self.get_notifications(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset
        )

        # Get counts
        query: dict[str, object] | None = {"status": status} if status else None
        total, unread_count = await asyncio.gather(
            self.repository.count_notifications(user_id, query),
            self.get_unread_count(user_id)
        )

        return NotificationListResponse(
            notifications=notifications,
            total=total,
            unread_count=unread_count
        )

    async def update_subscription(
            self,
            user_id: UserId,
            channel: NotificationChannel,
            enabled: bool,
            webhook_url: str | None = None,
            slack_webhook: str | None = None,
            notification_types: list[NotificationType] | None = None
    ) -> NotificationSubscription:
        """Update notification subscription preferences."""
        # Get existing or create new
        subscription = await self.repository.get_subscription(user_id, channel)

        if not subscription:
            subscription = NotificationSubscription(
                user_id=user_id,
                channel=channel,
                enabled=enabled,
                notification_types=notification_types or [],
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC)
            )
        else:
            subscription.enabled = enabled

        # Update URLs if provided
        if webhook_url is not None:
            subscription.webhook_url = webhook_url
        if slack_webhook is not None:
            subscription.slack_webhook = slack_webhook
        if notification_types is not None:
            subscription.notification_types = notification_types

        await self.repository.upsert_subscription(user_id, channel, subscription)

        return subscription

    async def mark_all_as_read(self, user_id: UserId) -> int:
        """Mark all notifications as read for a user."""
        count = await self.repository.mark_all_as_read(user_id)

        if count > 0 and self.event_bus:
            await self.event_bus.publish(
                "notifications.all_read",
                {
                    "user_id": user_id,
                    "count": count,
                    "read_at": datetime.now(UTC).isoformat()
                }
            )

        return count

    async def get_subscriptions(self, user_id: UserId) -> dict[str, NotificationSubscription]:
        """Get all notification subscriptions for a user."""
        return await self.repository.get_all_subscriptions(user_id)

    async def delete_notification(
            self,
            user_id: UserId,
            notification_id: NotificationId
    ) -> bool:
        """Delete a notification."""
        return await self.repository.delete_notification(str(notification_id), user_id)

    async def send_test_notification(
            self,
            user_id: UserId,
            request: TestNotificationRequest
    ) -> Notification:
        """Send a test notification to verify channel configuration."""
        # Create test context
        context = {
            "test": True,
            "timestamp": datetime.now(UTC).isoformat(),
            "channel": str(request.channel),
            "type": str(request.notification_type)
        }

        # Create and send test notification
        return await self.create_notification(
            user_id=user_id,
            notification_type=request.notification_type,
            context=context,
            channel=request.channel,
            priority=NotificationPriority.LOW
        )


@asynccontextmanager
async def notification_service_context(
        notification_repository: NotificationRepository,
        event_service: KafkaEventService,
        event_bus_manager: Any = None
) -> AsyncIterator[NotificationService]:
    """Context manager for notification service."""
    service = NotificationService(
        notification_repository=notification_repository,
        event_service=event_service,
        event_bus_manager=event_bus_manager
    )

    try:
        await service.initialize()
        yield service
    finally:
        await service.shutdown()
