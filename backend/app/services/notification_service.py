import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import auto
from typing import Any, Awaitable, Callable

import httpx
from jinja2 import Template

from app.core.exceptions import ServiceError
from app.core.logging import logger
from app.core.metrics.context import get_notification_metrics
from app.core.utils import StringEnum
from app.db.repositories.notification_repository import NotificationRepository
from app.domain.enums.events import EventType
from app.domain.enums.kafka import GroupId
from app.domain.enums.notification import (
    NotificationChannel,
    NotificationPriority,
    NotificationStatus,
    NotificationType,
)
from app.domain.enums.user import UserRole
from app.domain.notification.models import (
    DomainNotification,
    DomainNotificationListResult,
    DomainNotificationSubscription,
    DomainNotificationTemplate,
)
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.dispatcher import EventDispatcher
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionCompletedEvent,
    ExecutionFailedEvent,
    ExecutionTimeoutEvent,
)
from app.infrastructure.kafka.mappings import get_topic_for_event
from app.services.event_bus import EventBusManager
from app.services.kafka_event_service import KafkaEventService
from app.settings import get_settings

# Type aliases
type EventPayload = dict[str, Any]
type NotificationContext = dict[str, Any]
type ChannelHandler = Callable[[DomainNotification, DomainNotificationSubscription], Awaitable[None]]
type SystemNotificationStats = dict[str, int]
type SlackMessage = dict[str, Any]

# Constants
THROTTLE_WINDOW_HOURS: int = 1
THROTTLE_MAX_PER_HOUR: int = 5
PENDING_BATCH_SIZE: int = 10
OLD_NOTIFICATION_DAYS: int = 30
RETRY_DELAY_MINUTES: int = 5


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


class NotificationService:
    def __init__(
            self,
            notification_repository: NotificationRepository,
            event_service: KafkaEventService,
            event_bus_manager: EventBusManager,
            schema_registry_manager: SchemaRegistryManager
    ) -> None:
        self.repository = notification_repository
        self.event_service = event_service
        self.event_bus_manager = event_bus_manager
        self.metrics = get_notification_metrics()
        self.settings = get_settings()
        self.schema_registry_manager = schema_registry_manager

        # State
        self._state = ServiceState.IDLE
        self._throttle_cache = ThrottleCache()

        # Tasks
        self._tasks: set[asyncio.Task[None]] = set()

        self._consumer: UnifiedConsumer | None = None
        self._dispatcher: EventDispatcher | None = None
        self._consumer_task: asyncio.Task[None] | None = None

        logger.info(
            "NotificationService initialized",
            extra={
                "repository": type(notification_repository).__name__,
                "event_service": type(event_service).__name__,
                "schema_registry": type(schema_registry_manager).__name__
            }
        )

        # Channel handlers mapping
        self._channel_handlers: dict[NotificationChannel, ChannelHandler] = {
            NotificationChannel.IN_APP: self._send_in_app,
            NotificationChannel.WEBHOOK: self._send_webhook,
            NotificationChannel.SLACK: self._send_slack
        }

    @property
    def state(self) -> ServiceState:
        return self._state

    async def initialize(self) -> None:
        if self._state != ServiceState.IDLE:
            logger.warning(f"Cannot initialize in state: {self._state}")
            return

        self._state = ServiceState.INITIALIZING

        # Load templates
        await self._load_default_templates()

        # Start processors
        self._state = ServiceState.RUNNING
        self._start_background_tasks()

        logger.info("Notification service initialized (without Kafka consumer)")

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
            DomainNotificationTemplate(
                notification_type=NotificationType.EXECUTION_COMPLETED,
                subject_template="Execution Completed: {{ execution_id }}",
                body_template="Your code execution {{ execution_id }} completed successfully in {{ duration }}s.",
                channels=[NotificationChannel.IN_APP, NotificationChannel.WEBHOOK]
            ),
            DomainNotificationTemplate(
                notification_type=NotificationType.EXECUTION_FAILED,
                subject_template="Execution Failed: {{ execution_id }}",
                body_template="Your code execution {{ execution_id }} failed: {{ error }}",
                channels=[NotificationChannel.IN_APP, NotificationChannel.WEBHOOK, NotificationChannel.SLACK],
                priority=NotificationPriority.HIGH
            ),
            DomainNotificationTemplate(
                notification_type=NotificationType.EXECUTION_TIMEOUT,
                subject_template="Execution Timeout: {{ execution_id }}",
                body_template="Your code execution {{ execution_id }} timed out after {{ timeout }}s.",
                channels=[NotificationChannel.IN_APP, NotificationChannel.WEBHOOK],
                priority=NotificationPriority.HIGH
            ),
            DomainNotificationTemplate(
                notification_type=NotificationType.SYSTEM_UPDATE,
                subject_template="System Update: {{ update_type }}",
                body_template="{{ message }}",
                channels=[NotificationChannel.IN_APP],
                priority=NotificationPriority.MEDIUM
            ),
            DomainNotificationTemplate(
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
            bootstrap_servers=self.settings.KAFKA_BOOTSTRAP_SERVERS,
            group_id=GroupId.NOTIFICATION_SERVICE,
            max_poll_records=10,
            enable_auto_commit=True,
            auto_offset_reset="latest"  # Only process new events
        )

        execution_results_topic = get_topic_for_event(EventType.EXECUTION_COMPLETED)

        # Log topics for debugging
        logger.info(f"Notification service will subscribe to topics: {execution_results_topic}")

        # Create dispatcher and register handlers for specific event types
        self._dispatcher = EventDispatcher()
        self._dispatcher.register_handler(EventType.EXECUTION_COMPLETED, self._handle_execution_completed_wrapper)
        self._dispatcher.register_handler(EventType.EXECUTION_FAILED, self._handle_execution_failed_wrapper)
        self._dispatcher.register_handler(EventType.EXECUTION_TIMEOUT, self._handle_execution_timeout_wrapper)

        # Create consumer with dispatcher
        self._consumer = UnifiedConsumer(
            consumer_config,
            event_dispatcher=self._dispatcher
        )

        # Start consumer
        await self._consumer.start([execution_results_topic])

        # Start consumer task
        self._consumer_task = asyncio.create_task(self._run_consumer())
        self._tasks.add(self._consumer_task)
        self._consumer_task.add_done_callback(self._tasks.discard)

        logger.info("Notification service subscribed to execution events")

    async def create_notification(
            self,
            user_id: str,
            notification_type: NotificationType,
            context: NotificationContext,
            channel: NotificationChannel | None = None,
            scheduled_for: datetime | None = None,
            priority: NotificationPriority | None = None,
            correlation_id: str | None = None,
            related_entity_id: str | None = None,
            related_entity_type: str | None = None
    ) -> DomainNotification:
        logger.info(
            f"Creating notification for user {user_id}",
            extra={
                "user_id": user_id,
                "notification_type": str(notification_type),
                "channel": str(channel) if channel else "default",
                "scheduled": scheduled_for is not None,
                "correlation_id": correlation_id,
                "related_entity_id": related_entity_id
            }
        )

        # Check throttling
        if await self._throttle_cache.check_throttle(user_id, notification_type):
            error_msg = (f"Notification rate limit exceeded for user {user_id}, type {notification_type}. "
                         f"Max {THROTTLE_MAX_PER_HOUR} per {THROTTLE_WINDOW_HOURS} hour(s)")
            logger.warning(error_msg)
            # Throttling is a client-driven rate issue
            raise ServiceError(error_msg, status_code=429)

        # Get template
        template = await self.repository.get_template(notification_type)
        if not template:
            error_msg = (f"No notification template configured for type: {notification_type}. "
                         f"Please contact administrator.")
            logger.error(error_msg, extra={"notification_type": str(notification_type), "user_id": user_id})
            # Misconfiguration - treat as server error
            raise ServiceError(error_msg, status_code=500)

        # Render notification content
        try:
            subject = Template(template.subject_template).render(**context)
            body = Template(template.body_template).render(**context)
            action_url = None
            if template.action_url_template:
                action_url = Template(template.action_url_template).render(**context)

            logger.debug(
                "Rendered notification content",
                extra={
                    "subject_length": len(subject),
                    "body_length": len(body),
                    "has_action_url": action_url is not None
                }
            )
        except Exception as e:
            error_msg = (f"Failed to render notification template for {notification_type}: {str(e)}. "
                         f"Context keys: {list(context.keys())}")
            logger.error(error_msg, exc_info=True)
            raise ValueError(error_msg) from e

        # Use provided channel or first from template
        notification_channel = channel or template.channels[0]

        # Create notification
        notification = DomainNotification(
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
            metadata=context
        )

        # Save to database
        await self.repository.create_notification(notification)

        # Publish event
        event_bus = await self.event_bus_manager.get_event_bus()
        await event_bus.publish(
            "notifications.created",
            {
                "notification_id": str(notification.notification_id),
                "user_id": user_id,
                "type": str(notification_type)
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
            target_users: list[str] | None = None,
            target_roles: list[UserRole] | None = None
    ) -> SystemNotificationStats:
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
        if target_users:
            users_to_notify = target_users
        elif target_roles:
            users_to_notify = await self.repository.get_users_by_roles(target_roles)
        else:
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

    async def _deliver_notification(self, notification: DomainNotification) -> None:
        """Deliver notification through configured channel."""
        logger.info(
            f"Delivering notification {notification.notification_id}",
            extra={
                "notification_id": str(notification.notification_id),
                "user_id": notification.user_id,
                "channel": str(notification.channel),
                "type": str(notification.notification_type),
                "priority": str(notification.priority)
            }
        )

        # Check user subscription for the channel
        subscription = await self.repository.get_subscription(
            notification.user_id,
            notification.channel
        )

        if not subscription or not subscription.enabled:
            error_msg = (f"User {notification.user_id} has not enabled {notification.channel} notifications. "
                         f"Please enable in settings.")
            logger.info(error_msg)
            notification.status = NotificationStatus.FAILED
            notification.error_message = error_msg
            await self.repository.update_notification(notification)
            return

        # Check notification type filter
        if (subscription.notification_types and
                notification.notification_type not in subscription.notification_types):
            error_msg = (f"Notification type '{notification.notification_type}' "
                         f"is filtered out by user preferences for channel {notification.channel}")
            logger.info(error_msg)
            notification.status = NotificationStatus.FAILED
            notification.error_message = error_msg
            await self.repository.update_notification(notification)
            return

        # Send through channel
        start_time = asyncio.get_event_loop().time()
        try:
            handler = self._channel_handlers.get(notification.channel)
            if handler:
                logger.debug(f"Using handler {handler.__name__} for channel {notification.channel}")
                await handler(notification, subscription)
                delivery_time = asyncio.get_event_loop().time() - start_time

                # Update status
                notification.status = NotificationStatus.SENT
                notification.sent_at = datetime.now(UTC)

                logger.info(
                    f"Successfully delivered notification {notification.notification_id}",
                    extra={
                        "notification_id": str(notification.notification_id),
                        "channel": str(notification.channel),
                        "delivery_time_ms": int(delivery_time * 1000)
                    }
                )

                # Metrics
                self.metrics.record_notification_sent(
                    str(notification.notification_type)
                )
                self.metrics.record_notification_delivery_time(
                    delivery_time,
                    str(notification.notification_type)
                )
            else:
                error_msg = (f"No handler configured for notification channel: {notification.channel}. "
                             f"Available channels: {list(self._channel_handlers.keys())}")
                raise ValueError(error_msg)

        except Exception as e:
            error_details = {
                "notification_id": str(notification.notification_id),
                "channel": str(notification.channel),
                "error_type": type(e).__name__,
                "error_message": str(e),
                "retry_count": notification.retry_count,
                "max_retries": notification.max_retries
            }

            logger.error(
                f"Failed to deliver notification {notification.notification_id}: {str(e)}",
                extra=error_details,
                exc_info=True
            )

            notification.status = NotificationStatus.FAILED
            notification.failed_at = datetime.now(UTC)
            notification.error_message = f"Delivery failed via {notification.channel}: {str(e)}"
            notification.retry_count = notification.retry_count + 1

            # Schedule retry if under limit
            if notification.retry_count < notification.max_retries:
                retry_time = datetime.now(UTC) + timedelta(minutes=RETRY_DELAY_MINUTES)
                notification.scheduled_for = retry_time
                notification.status = NotificationStatus.PENDING
                logger.info(
                    f"Scheduled retry {notification.retry_count}/{notification.max_retries} "
                    f"for {notification.notification_id}",
                    extra={"retry_at": retry_time.isoformat()}
                )
            else:
                logger.warning(
                    f"Max retries exceeded for notification {notification.notification_id}",
                    extra=error_details
                )

            # Metrics
            self.metrics.record_notification_failed(
                str(notification.notification_type),
                type(e).__name__
            )

        await self.repository.update_notification(notification)

    async def _send_in_app(
            self,
            notification: DomainNotification,
            subscription: DomainNotificationSubscription
    ) -> None:
        """Send in-app notification."""
        # In-app notifications are already stored, just update status
        notification.status = NotificationStatus.DELIVERED
        await self.repository.update_notification(notification)

    async def _send_webhook(
            self,
            notification: DomainNotification,
            subscription: DomainNotificationSubscription
    ) -> None:
        """Send webhook notification."""
        webhook_url = notification.webhook_url or subscription.webhook_url
        if not webhook_url:
            raise ValueError(
                f"No webhook URL configured for user {notification.user_id} on channel {notification.channel}. "
                f"Configure in notification settings.")

        payload = {
            "notification_id": str(notification.notification_id),
            "type": str(notification.notification_type),
            "subject": notification.subject,
            "body": notification.body,
            "priority": str(notification.priority),
            "timestamp": notification.created_at.timestamp()
        }

        if notification.action_url:
            payload["action_url"] = notification.action_url
        if notification.related_entity_id:
            payload["related_entity_id"] = notification.related_entity_id
            payload["related_entity_type"] = notification.related_entity_type or ""

        headers = notification.webhook_headers or {}
        headers["Content-Type"] = "application/json"

        logger.debug(
            f"Sending webhook notification to {webhook_url}",
            extra={
                "notification_id": str(notification.notification_id),
                "payload_size": len(str(payload)),
                "webhook_url": webhook_url
            }
        )

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

            logger.debug(
                "Webhook delivered successfully",
                extra={
                    "notification_id": str(notification.notification_id),
                    "status_code": response.status_code,
                    "response_time_ms": int(response.elapsed.total_seconds() * 1000)
                }
            )

    async def _send_slack(
            self,
            notification: DomainNotification,
            subscription: DomainNotificationSubscription
    ) -> None:
        """Send Slack notification."""
        if not subscription.slack_webhook:
            raise ValueError(
                f"No Slack webhook URL configured for user {notification.user_id}. "
                f"Please configure Slack integration in notification settings.")

        # Format message for Slack
        slack_message: SlackMessage = {
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

        logger.debug(
            "Sending Slack notification",
            extra={
                "notification_id": str(notification.notification_id),
                "has_action": notification.action_url is not None,
                "priority_color": self._get_slack_color(notification.priority)
            }
        )

        async with httpx.AsyncClient() as client:
            response = await client.post(
                subscription.slack_webhook,
                json=slack_message,
                timeout=30.0
            )
            response.raise_for_status()
            notification.delivered_at = datetime.now(UTC)
            notification.status = NotificationStatus.DELIVERED

            logger.debug(
                "Slack notification delivered successfully",
                extra={
                    "notification_id": str(notification.notification_id),
                    "status_code": response.status_code
                }
            )

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

    async def _handle_execution_timeout_typed(self, event: ExecutionTimeoutEvent) -> None:
        """Handle typed execution timeout event."""
        try:
            user_id = event.metadata.user_id
            if not user_id:
                logger.error("No user_id in event metadata")
                return

            # Use model_dump to get all event data
            event_data = event.model_dump(
                exclude={"metadata", "event_type", "event_version", "timestamp", "aggregate_id", "topic"})

            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.EXECUTION_TIMEOUT,
                context=event_data,
                priority=NotificationPriority.HIGH,
                correlation_id=event.metadata.correlation_id,
                related_entity_id=event.execution_id,
                related_entity_type="execution"
            )
        except Exception as e:
            logger.error(f"Error handling execution timeout event: {e}")

    async def _handle_execution_completed_typed(self, event: ExecutionCompletedEvent) -> None:
        """Handle typed execution completed event."""
        try:
            user_id = event.metadata.user_id
            if not user_id:
                logger.error("No user_id in event metadata")
                return

            # Use model_dump to get all event data
            event_data = event.model_dump(
                exclude={"metadata", "event_type", "event_version", "timestamp", "aggregate_id", "topic"})

            # Truncate stdout/stderr for notification context
            event_data["stdout"] = event_data["stdout"][:200]
            event_data["stderr"] = event_data["stderr"][:200]

            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.EXECUTION_COMPLETED,
                context=event_data,
                correlation_id=event.metadata.correlation_id,
                related_entity_id=event.execution_id,
                related_entity_type="execution"
            )
        except Exception as e:
            logger.error(f"Error handling execution completed event: {e}")

    async def _handle_execution_completed_wrapper(self, event: BaseEvent) -> None:
        """Wrapper for handling ExecutionCompletedEvent."""
        assert isinstance(event, ExecutionCompletedEvent)
        await self._handle_execution_completed_typed(event)

    async def _handle_execution_failed_wrapper(self, event: BaseEvent) -> None:
        """Wrapper for handling ExecutionFailedEvent."""
        assert isinstance(event, ExecutionFailedEvent)
        await self._handle_execution_failed_typed(event)

    async def _handle_execution_timeout_wrapper(self, event: BaseEvent) -> None:
        """Wrapper for handling ExecutionTimeoutEvent."""
        assert isinstance(event, ExecutionTimeoutEvent)
        await self._handle_execution_timeout_typed(event)

    async def _handle_execution_failed_typed(self, event: ExecutionFailedEvent) -> None:
        """Handle typed execution failed event."""
        try:
            user_id = event.metadata.user_id
            if not user_id:
                logger.error("No user_id in event metadata")
                return

            # Use model_dump to get all event data
            event_data = event.model_dump(
                exclude={"metadata", "event_type", "event_version", "timestamp", "aggregate_id", "topic"})

            # Truncate stdout/stderr for notification context
            if "stdout" in event_data and event_data["stdout"]:
                event_data["stdout"] = event_data["stdout"][:200]
            if "stderr" in event_data and event_data["stderr"]:
                event_data["stderr"] = event_data["stderr"][:200]

            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.EXECUTION_FAILED,
                context=event_data,
                priority=NotificationPriority.HIGH,
                correlation_id=event.metadata.correlation_id,
                related_entity_id=event.execution_id,
                related_entity_type="execution"
            )
        except Exception as e:
            logger.error(f"Error handling execution failed event: {e}")

    # Public API methods

    async def mark_as_read(self, user_id: str, notification_id: str) -> bool:
        """Mark notification as read."""
        try:
            success = await self.repository.mark_as_read(str(notification_id), user_id)

            event_bus = await self.event_bus_manager.get_event_bus()
            if success:
                await event_bus.publish(
                    "notifications.read",
                    {
                        "notification_id": str(notification_id),
                        "user_id": user_id,
                        "read_at": datetime.now(UTC).isoformat()
                    }
                )

            if not success:
                raise ServiceError("Notification not found", status_code=404)

            return True

        except Exception as e:
            logger.error(f"Error marking notification as read: {e}")
            raise ServiceError("Failed to mark notification as read", status_code=500) from e

    async def get_notifications(
            self,
            user_id: str,
            status: NotificationStatus | None = None,
            limit: int = 20,
            offset: int = 0
    ) -> list[DomainNotification]:
        """Get notifications for a user."""
        notifications = await self.repository.list_notifications(
            user_id=user_id,
            status=status,
            skip=offset,
            limit=limit
        )

        return notifications

    async def get_unread_count(self, user_id: str) -> int:
        """Get count of unread notifications."""
        return await self.repository.get_unread_count(user_id)

    async def list_notifications(
            self,
            user_id: str,
            status: NotificationStatus | None = None,
            limit: int = 20,
            offset: int = 0
    ) -> DomainNotificationListResult:
        """List notifications with pagination."""
        # Get notifications
        notifications = await self.get_notifications(
            user_id=user_id,
            status=status,
            limit=limit,
            offset=offset
        )

        # Get counts
        additional_filters: dict[str, object] | None = {"status": status} if status else None
        total, unread_count = await asyncio.gather(
            self.repository.count_notifications(user_id, additional_filters),
            self.get_unread_count(user_id)
        )

        return DomainNotificationListResult(
            notifications=notifications,
            total=total,
            unread_count=unread_count
        )

    async def update_subscription(
            self,
            user_id: str,
            channel: NotificationChannel,
            enabled: bool,
            webhook_url: str | None = None,
            slack_webhook: str | None = None,
            notification_types: list[NotificationType] | None = None
    ) -> DomainNotificationSubscription:
        """Update notification subscription preferences."""
        # Validate channel-specific requirements
        if channel == NotificationChannel.WEBHOOK and enabled:
            if not webhook_url:
                raise ServiceError("webhook_url is required when enabling WEBHOOK", status_code=422)
            if not (webhook_url.startswith("http://") or webhook_url.startswith("https://")):
                raise ServiceError("webhook_url must start with http:// or https://", status_code=422)
        if channel == NotificationChannel.SLACK and enabled:
            if not slack_webhook:
                raise ServiceError("slack_webhook is required when enabling SLACK", status_code=422)
            if not slack_webhook.startswith("https://hooks.slack.com/"):
                raise ServiceError("slack_webhook must be a valid Slack webhook URL", status_code=422)

        # Get existing or create new
        subscription = await self.repository.get_subscription(user_id, channel)

        if not subscription:
            subscription = DomainNotificationSubscription(
                user_id=user_id,
                channel=channel,
                enabled=enabled,
                notification_types=notification_types or []
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

    async def mark_all_as_read(self, user_id: str) -> int:
        """Mark all notifications as read for a user."""
        count = await self.repository.mark_all_as_read(user_id)

        event_bus = await self.event_bus_manager.get_event_bus()
        if count > 0:
            await event_bus.publish(
                "notifications.all_read",
                {
                    "user_id": user_id,
                    "count": count,
                    "read_at": datetime.now(UTC).isoformat()
                }
            )

        return count

    async def get_subscriptions(self, user_id: str) -> dict[str, DomainNotificationSubscription]:
        """Get all notification subscriptions for a user."""
        return await self.repository.get_all_subscriptions(user_id)

    async def delete_notification(
            self,
            user_id: str,
            notification_id: str
    ) -> bool:
        """Delete a notification."""
        deleted = await self.repository.delete_notification(str(notification_id), user_id)
        if not deleted:
            raise ServiceError("Notification not found", status_code=404)
        return deleted
