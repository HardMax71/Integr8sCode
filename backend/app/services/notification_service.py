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
from typing import Any, ClassVar, Protocol

import httpx
from fastapi import Request
from jinja2 import Template
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel

from app.config import get_settings
from app.core.logging import logger
from app.core.metrics import NOTIFICATION_DELIVERY_TIME, NOTIFICATIONS_FAILED, NOTIFICATIONS_SENT
from app.db.mongodb import DatabaseManager
from app.schemas_avro.event_schemas import EventType
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
        cutoff = now - timedelta(hours=THROTTLE_WINDOW_HOURS)

        async with self._lock:
            # Clean old entries
            if key in self._entries:
                self._entries[key] = [
                    ts for ts in self._entries[key]
                    if ts > cutoff
                ]

            # Check limit
            recent_count = len(self._entries.get(key, []))
            if recent_count >= THROTTLE_MAX_PER_HOUR:
                return True

            # Add new entry
            if key not in self._entries:
                self._entries[key] = []
            self._entries[key].append(now)

            return False

    async def clear(self) -> None:
        """Clear all throttle entries."""
        async with self._lock:
            self._entries.clear()


@dataclass(frozen=True, slots=True)
class DefaultTemplate:
    """Default notification template configuration."""
    notification_type: NotificationType
    channels: list[NotificationChannel]
    priority: NotificationPriority
    subject_template: str
    body_template: str
    action_url_template: str | None = None


# Default templates
DEFAULT_TEMPLATES: tuple[DefaultTemplate, ...] = (
    DefaultTemplate(
        notification_type=NotificationType.EXECUTION_COMPLETED,
        channels=[NotificationChannel.IN_APP],
        priority=NotificationPriority.MEDIUM,
        subject_template="Execution {{ execution_id }} completed successfully",
        body_template="""Your code execution has completed successfully.

Execution ID: {{ execution_id }}
Language: {{ language }}
Duration: {{ duration_seconds }}s
Output Lines: {{ output_lines }}

View results: {{ action_url }}""",
        action_url_template="/editor?execution={{ execution_id }}"
    ),
    DefaultTemplate(
        notification_type=NotificationType.EXECUTION_FAILED,
        channels=[NotificationChannel.IN_APP],
        priority=NotificationPriority.HIGH,
        subject_template="Execution {{ execution_id }} failed",
        body_template="""Your code execution has failed.

Execution ID: {{ execution_id }}
Language: {{ language }}
Error: {{ error_message }}

View details: {{ action_url }}""",
        action_url_template="/editor?execution={{ execution_id }}"
    ),
    DefaultTemplate(
        notification_type=NotificationType.SECURITY_ALERT,
        channels=[NotificationChannel.IN_APP],
        priority=NotificationPriority.URGENT,
        subject_template="Security Alert: {{ alert_type }}",
        body_template="""A security event has been detected on your account.

Alert Type: {{ alert_type }}
Details: {{ details }}
Time: {{ timestamp }}
IP Address: {{ ip_address }}

If this wasn't you, please secure your account immediately.

View details: {{ action_url }}""",
        action_url_template="/settings/security"
    ),
)


class EventBus(Protocol):
    """Protocol for event bus operations."""

    async def subscribe(self, event_type: str, handler: Any) -> None:
        """Subscribe to event type."""
        ...

    async def publish(self, topic: str, data: Any) -> None:
        """Publish event to topic."""
        ...


class NotificationService:
    """Service for managing event-driven notifications with modern patterns."""

    def __init__(
            self,
            db_manager: DatabaseManager,
            event_service: KafkaEventService,
            event_bus_manager: Any = None
    ) -> None:
        """Initialize the notification service."""
        self.db_manager = db_manager
        self._db: AsyncIOMotorDatabase[Any] | None = db_manager.db
        self.event_service = event_service
        self.event_bus_manager = event_bus_manager
        self.event_bus: EventBus | None = None
        self.settings = get_settings()

        # State
        self._state = ServiceState.IDLE
        self._throttle_cache = ThrottleCache()

        # Tasks
        self._tasks: set[asyncio.Task[None]] = set()

        # Channel handlers mapping
        self._channel_handlers: dict[NotificationChannel, ChannelHandler] = {
            NotificationChannel.IN_APP: self._send_in_app,
            NotificationChannel.WEBHOOK: self._send_webhook,
            NotificationChannel.SLACK: self._send_slack
        }
    
    @property
    def db(self) -> AsyncIOMotorDatabase[Any]:
        """Get database with null check"""
        if self._db is None:
            raise RuntimeError("Database not initialized")
        return self._db

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
            await self._create_indexes()

            # Load templates
            await self._load_default_templates()

            # Start processors
            self._state = ServiceState.RUNNING
            self._start_background_tasks()

            # Subscribe to events
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

        # Clear cache
        await self._throttle_cache.clear()

        self._state = ServiceState.STOPPED
        logger.info("Notification service shut down")

    async def _create_indexes(self) -> None:
        """Create database indexes for notifications."""
        indexes = [
            # Notifications
            self.db.notifications.create_indexes([
                IndexModel([("user_id", ASCENDING), ("created_at", DESCENDING)]),
                IndexModel([("status", ASCENDING), ("scheduled_for", ASCENDING)]),
                IndexModel([("correlation_id", ASCENDING)]),
                IndexModel([("related_entity_id", ASCENDING), ("related_entity_type", ASCENDING)])
            ]),
            # Rules
            self.db.notification_rules.create_indexes([
                IndexModel([("event_types", ASCENDING)]),
                IndexModel([("enabled", ASCENDING)])
            ]),
            # Subscriptions
            self.db.notification_subscriptions.create_indexes([
                IndexModel([("user_id", ASCENDING), ("channel", ASCENDING)], unique=True),
                IndexModel([("enabled", ASCENDING)])
            ])
        ]

        await asyncio.gather(*indexes)

    async def _load_default_templates(self) -> None:
        """Load default notification templates."""
        operations = []

        for template_config in DEFAULT_TEMPLATES:
            template = NotificationTemplate(
                notification_type=template_config.notification_type,
                channels=template_config.channels,
                priority=template_config.priority,
                subject_template=template_config.subject_template,
                body_template=template_config.body_template,
                action_url_template=template_config.action_url_template
            )

            operations.append(
                self.db.notification_templates.update_one(
                    {"notification_type": template.notification_type},
                    {"$set": template.model_dump()},
                    upsert=True
                )
            )

        await asyncio.gather(*operations)

    def _start_background_tasks(self) -> None:
        """Start background processing tasks."""
        self._tasks.add(asyncio.create_task(self._process_pending_notifications()))
        self._tasks.add(asyncio.create_task(self._process_scheduled_notifications()))
        self._tasks.add(asyncio.create_task(self._cleanup_old_notifications()))

    async def _subscribe_to_events(self) -> None:
        """Subscribe to events that trigger notifications."""
        if not self.event_bus:
            logger.warning("Event bus not available, skipping event subscriptions")
            return

        # Event handlers mapping
        handlers = {
            EventType.EXECUTION_COMPLETED: self._handle_execution_completed,
            EventType.EXECUTION_FAILED: self._handle_execution_failed,
            EventType.EXECUTION_TIMEOUT: self._handle_execution_timeout,
            EventType.USER_SETTINGS_UPDATED: self._handle_settings_updated,
            EventType.RESOURCE_LIMIT_EXCEEDED: self._handle_resource_limit
        }

        # Subscribe concurrently
        subscriptions = [
            self.event_bus.subscribe(event_type, handler)
            for event_type, handler in handlers.items()
        ]

        await asyncio.gather(*subscriptions)

    async def create_notification(
            self,
            user_id: UserId,
            notification_type: NotificationType,
            channel: NotificationChannel,
            context: NotificationContext,
            priority: NotificationPriority | None = None,
            scheduled_for: datetime | None = None
    ) -> Notification | None:
        """Create a notification from template."""
        # Check subscription
        subscription = await self._get_user_subscription(user_id, channel)
        if not subscription or not subscription.enabled:
            logger.info(f"User {user_id} not subscribed to {channel} notifications")
            return None

        if notification_type not in subscription.notification_types:
            logger.info(f"User {user_id} not subscribed to {notification_type} notifications")
            return None

        # Get template
        template = await self.db.notification_templates.find_one({
            "notification_type": notification_type
        })

        if not template:
            logger.error(f"No template found for notification type {notification_type}")
            return None

        # Check throttling
        if await self._throttle_cache.check_throttle(user_id, notification_type):
            logger.info(f"Notification throttled for user {user_id}, type {notification_type}")
            return None

        # Render content
        subject = Template(template["subject_template"]).render(**context)
        body = Template(template["body_template"]).render(**context)
        action_url = (
            Template(template["action_url_template"]).render(**context)
            if template.get("action_url_template")
            else None
        )

        # Create notification
        notification = Notification(
            user_id=user_id,
            notification_type=notification_type,
            channel=channel,
            priority=priority or template.get("priority", NotificationPriority.MEDIUM),
            subject=subject,
            body=body,
            action_url=action_url,
            scheduled_for=scheduled_for,
            correlation_id=context.get("correlation_id"),
            related_entity_id=context.get("entity_id"),
            related_entity_type=context.get("entity_type"),
            metadata=context
        )

        # Save to database
        await self.db.notifications.insert_one(notification.model_dump())

        # Publish event
        await self._publish_notification_event(
            EventType.NOTIFICATION_CREATED,
            notification
        )

        return notification

    async def send_notification(self, notification: Notification) -> bool:
        """Send a notification through the appropriate channel."""
        try:
            # Update status
            notification.status = NotificationStatus.SENDING
            await self._update_notification(notification)

            # Get handler
            handler = self._channel_handlers.get(notification.channel)
            if not handler:
                raise ValueError(f"No handler for channel {notification.channel}")

            # Send through channel
            start_time = datetime.now(UTC)
            success = await handler(notification)
            delivery_time = (datetime.now(UTC) - start_time).total_seconds()

            # Process result
            delivery = NotificationDelivery(
                notification_id=str(notification.notification_id),
                channel=notification.channel,
                success=success,
                delivery_time_seconds=delivery_time,
                error=notification.error_message if not success else None
            )

            await self._process_delivery_result(notification, delivery)

            return bool(success)

        except Exception as e:
            logger.error(f"Error sending notification {notification.notification_id}: {e}")

            notification.status = NotificationStatus.FAILED
            notification.error_message = str(e)
            notification.failed_at = datetime.now(UTC)

            await self._update_notification(notification)
            await self._publish_notification_event(
                EventType.NOTIFICATION_FAILED,
                notification,
                error=str(e)
            )

            return False

    async def _process_delivery_result(
            self,
            notification: Notification,
            delivery: NotificationDelivery
    ) -> None:
        """Process notification delivery result."""
        if delivery.success:
            # Success handling
            notification.status = NotificationStatus.SENT
            notification.sent_at = datetime.now(UTC)

            # Metrics
            NOTIFICATIONS_SENT.labels(
                channel=notification.channel,
                notification_type=notification.notification_type
            ).inc()

            NOTIFICATION_DELIVERY_TIME.labels(
                channel=notification.channel
            ).observe(delivery.delivery_time_seconds)

            # Event
            await self._publish_notification_event(
                EventType.NOTIFICATION_SENT,
                notification,
                delivery_time_seconds=delivery.delivery_time_seconds
            )
        else:
            # Failure handling
            notification.status = NotificationStatus.FAILED
            notification.failed_at = datetime.now(UTC)
            notification.retry_count += 1

            NOTIFICATIONS_FAILED.labels(
                channel=notification.channel,
                notification_type=notification.notification_type
            ).inc()

            # Schedule retry if under limit
            if notification.retry_count < notification.max_retries:
                notification.status = NotificationStatus.PENDING
                notification.scheduled_for = datetime.now(UTC) + timedelta(
                    minutes=RETRY_DELAY_MINUTES * notification.retry_count
                )

        await self._update_notification(notification)

    async def _send_in_app(self, notification: Notification) -> bool:
        """Send in-app notification through SSE."""
        if not self.event_bus:
            logger.error("Event bus not available for in-app notifications")
            return False

        try:
            # Publish to user's event stream
            await self.event_bus.publish(
                f"user.{notification.user_id}.notifications",
                {
                    "id": str(notification.notification_id),
                    "type": notification.notification_type,
                    "subject": notification.subject,
                    "body": notification.body,
                    "action_url": notification.action_url,
                    "priority": notification.priority,
                    "created_at": notification.created_at.isoformat()
                }
            )

            logger.info(f"In-app notification sent to user {notification.user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send in-app notification: {e}")
            notification.error_message = str(e)
            return False

    async def _send_webhook(self, notification: Notification) -> bool:
        """Send webhook notification."""
        try:
            # Get webhook URL
            webhook_url = notification.webhook_url
            if not webhook_url:
                subscription = await self._get_user_subscription(
                    notification.user_id,
                    NotificationChannel.WEBHOOK
                )
                webhook_url = subscription.webhook_url if subscription else None

            if not webhook_url:
                raise ValueError("No webhook URL configured")

            # Prepare payload
            payload = {
                "notification_id": str(notification.notification_id),
                "type": notification.notification_type,
                "subject": notification.subject,
                "body": notification.body,
                "action_url": notification.action_url,
                "priority": notification.priority,
                "metadata": notification.metadata,
                "timestamp": datetime.now(UTC).isoformat()
            }

            # Send webhook
            async with httpx.AsyncClient() as client:
                headers = notification.webhook_headers or {}
                headers["Content-Type"] = "application/json"

                response = await client.post(
                    webhook_url,
                    json=payload,
                    headers=headers,
                    timeout=30.0
                )
                response.raise_for_status()

            logger.info(f"Webhook sent to {webhook_url}")
            return True

        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")
            notification.error_message = str(e)
            return False

    async def _send_slack(self, notification: Notification) -> bool:
        """Send Slack notification."""
        try:
            # Get Slack webhook
            subscription = await self._get_user_subscription(
                notification.user_id,
                NotificationChannel.SLACK
            )

            if not subscription or not subscription.slack_webhook:
                raise ValueError("No Slack webhook configured")

            # Build Slack message
            slack_message = self._build_slack_message(notification)

            # Send to Slack
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    subscription.slack_webhook,
                    json=slack_message,
                    timeout=30.0
                )
                response.raise_for_status()

            logger.info(f"Slack notification sent for user {notification.user_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to send Slack notification: {e}")
            notification.error_message = str(e)
            return False

    def _build_slack_message(self, notification: Notification) -> dict[str, Any]:
        """Build Slack message structure."""
        blocks: list[dict[str, Any]] = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": notification.subject
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": notification.body
                }
            }
        ]

        # Add action button if URL provided
        if notification.action_url:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "View Details"
                    },
                    "url": f"{self.settings.APP_URL}{notification.action_url}"
                    }
                ]
            })

        return {
            "text": notification.subject,
            "blocks": blocks
        }

    async def _get_user_subscription(
            self,
            user_id: UserId,
            channel: NotificationChannel
    ) -> NotificationSubscription | None:
        """Get user's subscription preferences for a channel."""
        sub_data = await self.db.notification_subscriptions.find_one({
            "user_id": user_id,
            "channel": channel
        })

        if sub_data:
            return NotificationSubscription(**sub_data)

        # Return default subscription
        return NotificationSubscription(
            user_id=user_id,
            channel=channel,
            notification_types=[nt for nt in NotificationType],
            enabled=True
        )

    async def _update_notification(self, notification: Notification) -> None:
        """Update notification in database."""
        await self.db.notifications.update_one(
            {"notification_id": str(notification.notification_id)},
            {"$set": notification.model_dump()}
        )

    async def _publish_notification_event(
            self,
            event_type: EventType,
            notification: Notification,
            **extra_payload: Any
    ) -> None:
        """Publish notification-related event."""
        payload = {
            "notification_id": str(notification.notification_id),
            "user_id": notification.user_id,
            "type": notification.notification_type,
            "channel": notification.channel,
            "priority": notification.priority,
            **extra_payload
        }

        await self.event_service.publish_event(
            event_type=event_type,
            aggregate_id=f"notification_{notification.notification_id}",
            payload=payload
        )

    async def _process_pending_notifications(self) -> None:
        """Process pending notifications in batches."""
        while self._state == ServiceState.RUNNING:
            try:
                # Find pending notifications
                cursor = self.db.notifications.find({
                    "status": NotificationStatus.PENDING,
                    "$or": [
                        {"scheduled_for": None},
                        {"scheduled_for": {"$lte": datetime.now(UTC)}}
                    ]
                }).limit(PENDING_BATCH_SIZE)

                # Process batch
                async for notification_data in cursor:
                    notification = Notification(**notification_data)
                    await self.send_notification(notification)

            except Exception as e:
                logger.error(f"Error processing pending notifications: {e}")

            await asyncio.sleep(5)

    async def _process_scheduled_notifications(self) -> None:
        """Process scheduled notifications."""
        while self._state == ServiceState.RUNNING:
            try:
                # Find due scheduled notifications
                cursor = self.db.notifications.find({
                    "status": NotificationStatus.PENDING,
                    "scheduled_for": {
                        "$lte": datetime.now(UTC),
                        "$ne": None
                    }
                }).limit(PENDING_BATCH_SIZE)

                # Process batch
                async for notification_data in cursor:
                    notification = Notification(**notification_data)
                    await self.send_notification(notification)

            except Exception as e:
                logger.error(f"Error processing scheduled notifications: {e}")

            await asyncio.sleep(30)

    async def _cleanup_old_notifications(self) -> None:
        """Clean up old notifications periodically."""
        while self._state == ServiceState.RUNNING:
            try:
                # Calculate cutoff
                cutoff = datetime.now(UTC) - timedelta(days=OLD_NOTIFICATION_DAYS)

                # Delete old notifications
                result = await self.db.notifications.delete_many({
                    "created_at": {"$lt": cutoff}
                })

                if result.deleted_count > 0:
                    logger.info(f"Deleted {result.deleted_count} old notifications")

            except Exception as e:
                logger.error(f"Error cleaning up notifications: {e}")

            await asyncio.sleep(3600)  # Run hourly

    # Event handlers

    async def _handle_execution_completed(self, event: EventPayload) -> None:
        """Handle execution completed event."""
        try:
            payload = event.get("payload", {})
            user_id = event.get("metadata", {}).get("user_id")

            if not user_id:
                return

            # Check user settings
            settings = await self._get_user_notification_settings(user_id)
            if not settings.get("execution_completed"):
                return

            # Create context
            context: NotificationContext = {
                "execution_id": payload.get("execution_id"),
                "language": payload.get("language"),
                "duration_seconds": payload.get("duration_seconds", 0),
                "output_lines": len(payload.get("output", "").split("\n")),
                "correlation_id": event.get("correlation_id"),
                "entity_id": payload.get("execution_id"),
                "entity_type": "execution"
            }

            # Create notifications for enabled channels
            await self._create_channel_notifications(
                user_id,
                NotificationType.EXECUTION_COMPLETED,
                context,
                settings.get("channels", ["in_app"])
            )

        except Exception as e:
            logger.error(f"Error handling execution completed event: {e}")

    async def _handle_execution_failed(self, event: EventPayload) -> None:
        """Handle execution failed event."""
        try:
            payload = event.get("payload", {})
            user_id = event.get("metadata", {}).get("user_id")

            if not user_id:
                return

            # Check user settings
            settings = await self._get_user_notification_settings(user_id)
            if not settings.get("execution_failed"):
                return

            # Create context
            context: NotificationContext = {
                "execution_id": payload.get("execution_id"),
                "language": payload.get("language"),
                "error_message": payload.get("error", "Unknown error"),
                "correlation_id": event.get("correlation_id"),
                "entity_id": payload.get("execution_id"),
                "entity_type": "execution"
            }

            # Create notifications
            await self._create_channel_notifications(
                user_id,
                NotificationType.EXECUTION_FAILED,
                context,
                settings.get("channels", ["in_app"]),
                priority=NotificationPriority.HIGH
            )

        except Exception as e:
            logger.error(f"Error handling execution failed event: {e}")

    async def _handle_execution_timeout(self, event: EventPayload) -> None:
        """Handle execution timeout event."""
        try:
            payload = event.get("payload", {})
            user_id = event.get("metadata", {}).get("user_id")

            if not user_id:
                return

            # Create context
            context: NotificationContext = {
                "execution_id": payload.get("execution_id"),
                "language": payload.get("language"),
                "timeout_seconds": payload.get("timeout_seconds", 30),
                "correlation_id": event.get("correlation_id"),
                "entity_id": payload.get("execution_id"),
                "entity_type": "execution"
            }

            # Create notification
            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.EXECUTION_TIMEOUT,
                channel=NotificationChannel.IN_APP,
                context=context,
                priority=NotificationPriority.HIGH
            )

        except Exception as e:
            logger.error(f"Error handling execution timeout event: {e}")

    async def _handle_settings_updated(self, event: EventPayload) -> None:
        """Handle settings updated event."""
        try:
            payload = event.get("payload", {})
            user_id = payload.get("user_id")
            changes = payload.get("changes", [])

            if not user_id or not changes:
                return

            # Filter significant changes
            significant_fields = {"notifications", "security", "privacy"}
            significant_changes = [
                change for change in changes
                if change.get("field_path") in significant_fields
            ]

            if not significant_changes:
                return

            # Create context
            context: NotificationContext = {
                "changes": [change.get("field_path") for change in significant_changes],
                "change_count": len(significant_changes),
                "timestamp": event.get("timestamp"),
                "correlation_id": event.get("correlation_id")
            }

            # Create notification
            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.SETTINGS_CHANGED,
                channel=NotificationChannel.IN_APP,
                context=context
            )

        except Exception as e:
            logger.error(f"Error handling settings updated event: {e}")

    async def _handle_resource_limit(self, event: EventPayload) -> None:
        """Handle resource limit exceeded event."""
        try:
            payload = event.get("payload", {})
            user_id = event.get("metadata", {}).get("user_id")

            if not user_id:
                return

            # Create context
            context: NotificationContext = {
                "execution_id": payload.get("execution_id"),
                "resource_type": payload.get("resource_type", "unknown"),
                "limit": payload.get("limit"),
                "usage": payload.get("usage"),
                "correlation_id": event.get("correlation_id"),
                "entity_id": payload.get("execution_id"),
                "entity_type": "execution"
            }

            # Create notification
            await self.create_notification(
                user_id=user_id,
                notification_type=NotificationType.RESOURCE_LIMIT,
                channel=NotificationChannel.IN_APP,
                context=context,
                priority=NotificationPriority.HIGH
            )

        except Exception as e:
            logger.error(f"Error handling resource limit event: {e}")

    async def _get_user_notification_settings(
            self,
            user_id: UserId
    ) -> dict[str, Any]:
        """Get user notification settings."""
        settings = await self.db.user_settings_snapshots.find_one({
            "user_id": user_id
        })

        if not settings:
            return {"notifications": {}}

        return dict(settings.get("notifications", {}))

    async def _create_channel_notifications(
            self,
            user_id: UserId,
            notification_type: NotificationType,
            context: NotificationContext,
            channels: list[str],
            priority: NotificationPriority | None = None
    ) -> None:
        """Create notifications for multiple channels."""
        tasks = [
            self.create_notification(
                user_id=user_id,
                notification_type=notification_type,
                channel=NotificationChannel(channel),
                context=context,
                priority=priority
            )
            for channel in channels
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

    # Public API methods

    async def mark_as_read(
            self,
            notification_id: NotificationId,
            user_id: UserId
    ) -> bool:
        """Mark notification as read."""
        try:
            result = await self.db.notifications.update_one(
                {"notification_id": str(notification_id), "user_id": user_id},
                {
                    "$set": {
                        "status": NotificationStatus.READ,
                        "read_at": datetime.now(UTC)
                    }
                }
            )

            if result.modified_count > 0:
                # Publish event
                await self.event_service.publish_event(
                    event_type=EventType.NOTIFICATION_READ,
                    aggregate_id=f"notification_{notification_id}",
                    payload={
                        "notification_id": notification_id,
                        "user_id": user_id
                    }
                )
                return True

            return False

        except Exception as e:
            logger.error(f"Error marking notification as read: {e}")
            return False

    async def get_user_notifications(
            self,
            user_id: UserId,
            status: NotificationStatus | None = None,
            limit: int = 50,
            skip: int = 0
    ) -> list[Notification]:
        """Get notifications for a user."""
        query = {"user_id": user_id}
        if status:
            query["status"] = status

        cursor = self.db.notifications.find(query).sort(
            "created_at", DESCENDING
        ).skip(skip).limit(limit)

        notifications = []
        async for notification_data in cursor:
            notifications.append(Notification(**notification_data))

        return notifications

    async def get_unread_count(self, user_id: UserId) -> int:
        """Get count of unread notifications."""
        return await self.db.notifications.count_documents({
            "user_id": user_id,
            "status": {"$in": [NotificationStatus.SENT, NotificationStatus.DELIVERED]}
        })

    async def get_user_notifications_list(
            self,
            user_id: UserId,
            status: NotificationStatus | None = None,
            limit: int = 50,
            skip: int = 0
    ) -> NotificationListResponse:
        """Get user notifications with pagination."""
        # Get notifications
        notifications = await self.get_user_notifications(
            user_id=user_id,
            status=status,
            limit=limit,
            skip=skip
        )

        # Get counts
        query = {"user_id": user_id}
        if status:
            query["status"] = status

        total, unread_count = await asyncio.gather(
            self.db.notifications.count_documents(query),
            self.get_unread_count(user_id)
        )

        # Build response
        notification_responses = [
            NotificationResponse(
                notification_id=str(notification.notification_id),
                notification_type=notification.notification_type,
                channel=notification.channel,
                status=notification.status,
                subject=notification.subject,
                body=notification.body,
                action_url=notification.action_url,
                created_at=notification.created_at,
                read_at=notification.read_at,
                priority=notification.priority
            )
            for notification in notifications
        ]

        return NotificationListResponse(
            notifications=notification_responses,
            total=total,
            unread_count=unread_count
        )

    async def update_subscription(
            self,
            user_id: UserId,
            channel: NotificationChannel,
            subscription: NotificationSubscription
    ) -> NotificationSubscription:
        """Update user's notification subscription."""
        subscription.user_id = user_id
        subscription.channel = channel
        subscription.updated_at = datetime.now(UTC)

        await self.db.notification_subscriptions.replace_one(
            {"user_id": user_id, "channel": channel},
            subscription.model_dump(),
            upsert=True
        )

        # Publish event
        await self.event_service.publish_event(
            event_type=EventType.NOTIFICATION_PREFERENCES_UPDATED,
            aggregate_id=f"user_notifications_{user_id}",
            payload={
                "user_id": user_id,
                "channel": channel,
                "enabled": subscription.enabled,
                "notification_types": subscription.notification_types
            }
        )

        return subscription

    async def mark_all_as_read(self, user_id: UserId) -> int:
        """Mark all notifications as read for a user."""
        result = await self.db.notifications.update_many(
            {
                "user_id": user_id,
                "status": {"$in": [NotificationStatus.SENT, NotificationStatus.DELIVERED]}
            },
            {
                "$set": {
                    "status": NotificationStatus.READ,
                    "read_at": datetime.now(UTC)
                }
            }
        )
        return result.modified_count

    async def get_subscriptions(
            self,
            user_id: UserId
    ) -> list[NotificationSubscription]:
        """Get all notification subscriptions for a user."""
        subscriptions = []

        for channel in NotificationChannel:
            sub_data = await self.db.notification_subscriptions.find_one({
                "user_id": user_id,
                "channel": channel
            })

            if sub_data:
                subscriptions.append(NotificationSubscription(**sub_data))
            else:
                # Return default subscription
                subscriptions.append(NotificationSubscription(
                    user_id=user_id,
                    channel=channel,
                    notification_types=[nt for nt in NotificationType],
                    enabled=True,
                ))

        return subscriptions

    async def delete_notification(
            self,
            notification_id: NotificationId,
            user_id: UserId
    ) -> bool:
        """Delete a notification."""
        result = await self.db.notifications.delete_one({
            "notification_id": notification_id,
            "user_id": user_id
        })
        return result.deleted_count > 0


class NotificationManager:
    """Manager for NotificationService lifecycle with singleton pattern."""

    _instance: ClassVar['NotificationManager | None'] = None
    _lock: ClassVar[asyncio.Lock] = asyncio.Lock()

    def __new__(cls) -> 'NotificationManager':
        """Create or return singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """Initialize the manager."""
        if not hasattr(self, '_initialized'):
            self._service: NotificationService | None = None
            self._initialized = True

    async def get_service(
            self,
            db_manager: DatabaseManager,
            event_service: KafkaEventService,
            event_bus_manager: Any = None
    ) -> NotificationService:
        """Get or create service instance."""
        async with self._lock:
            if self._service is None:
                self._service = NotificationService(
                    db_manager,
                    event_service,
                    event_bus_manager
                )
                await self._service.initialize()
            return self._service

    async def shutdown(self) -> None:
        """Shutdown the service."""
        async with self._lock:
            if self._service:
                await self._service.shutdown()
                self._service = None


@asynccontextmanager
async def create_notification_service(
        db_manager: DatabaseManager,
        event_service: KafkaEventService,
        event_bus_manager: Any = None
) -> AsyncIterator[NotificationService]:
    """Create and manage notification service instance."""
    service = NotificationService(db_manager, event_service, event_bus_manager)

    try:
        await service.initialize()
        yield service
    finally:
        await service.shutdown()


def get_notification_service(request: Request) -> NotificationService:
    """FastAPI dependency to get notification service."""
    try:
        manager: NotificationManager = request.app.state.notification_manager
        if manager._service is None:
            raise RuntimeError("Notification service not initialized")
        return manager._service
    except AttributeError as e:
        raise RuntimeError("Notification manager not found in app state") from e
