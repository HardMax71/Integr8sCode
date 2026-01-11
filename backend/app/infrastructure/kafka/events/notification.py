from datetime import datetime
from typing import ClassVar, Literal

from pydantic import Field

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.notification import NotificationChannel, NotificationSeverity
from app.infrastructure.kafka.events.base import BaseEvent


class NotificationCreatedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_CREATED] = EventType.NOTIFICATION_CREATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.NOTIFICATION_EVENTS
    notification_id: str
    user_id: str
    subject: str
    body: str
    severity: NotificationSeverity
    tags: list[str]
    channels: list[NotificationChannel]


class NotificationSentEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_SENT] = EventType.NOTIFICATION_SENT
    topic: ClassVar[KafkaTopic] = KafkaTopic.NOTIFICATION_EVENTS
    notification_id: str
    user_id: str
    channel: NotificationChannel
    sent_at: datetime


class NotificationDeliveredEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_DELIVERED] = EventType.NOTIFICATION_DELIVERED
    topic: ClassVar[KafkaTopic] = KafkaTopic.NOTIFICATION_EVENTS
    notification_id: str
    user_id: str
    channel: NotificationChannel
    delivered_at: datetime


class NotificationFailedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_FAILED] = EventType.NOTIFICATION_FAILED
    topic: ClassVar[KafkaTopic] = KafkaTopic.NOTIFICATION_EVENTS
    notification_id: str
    user_id: str
    channel: NotificationChannel
    error: str
    retry_count: int


class NotificationReadEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_READ] = EventType.NOTIFICATION_READ
    topic: ClassVar[KafkaTopic] = KafkaTopic.NOTIFICATION_EVENTS
    notification_id: str
    user_id: str
    read_at: datetime


class NotificationClickedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_CLICKED] = EventType.NOTIFICATION_CLICKED
    topic: ClassVar[KafkaTopic] = KafkaTopic.NOTIFICATION_EVENTS
    notification_id: str
    user_id: str
    clicked_at: datetime
    action: str | None = None


class NotificationPreferencesUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.NOTIFICATION_PREFERENCES_UPDATED] = EventType.NOTIFICATION_PREFERENCES_UPDATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.NOTIFICATION_EVENTS
    user_id: str
    changed_fields: list[str] = Field(default_factory=list)
