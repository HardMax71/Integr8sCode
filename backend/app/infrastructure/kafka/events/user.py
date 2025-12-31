from typing import ClassVar, Literal

from pydantic_avro.to_avro.base import AvroBase

from app.domain.enums.auth import LoginMethod
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.events.base import BaseEvent


class NotificationSettingsPayload(AvroBase):
    """Avro-compatible payload for notification settings changes."""

    execution_completed: bool | None = None
    execution_failed: bool | None = None
    system_updates: bool | None = None
    security_alerts: bool | None = None
    channels: list[str] | None = None


class EditorSettingsPayload(AvroBase):
    """Avro-compatible payload for editor settings changes."""

    theme: str | None = None
    font_size: int | None = None
    tab_size: int | None = None
    use_tabs: bool | None = None
    word_wrap: bool | None = None
    show_line_numbers: bool | None = None


class UserRegisteredEvent(BaseEvent):
    event_type: Literal[EventType.USER_REGISTERED] = EventType.USER_REGISTERED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_EVENTS
    user_id: str
    username: str
    email: str


class UserLoggedInEvent(BaseEvent):
    event_type: Literal[EventType.USER_LOGGED_IN] = EventType.USER_LOGGED_IN
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_EVENTS
    user_id: str
    login_method: LoginMethod
    ip_address: str | None = None
    user_agent: str | None = None


class UserLoggedOutEvent(BaseEvent):
    event_type: Literal[EventType.USER_LOGGED_OUT] = EventType.USER_LOGGED_OUT
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_EVENTS
    user_id: str
    logout_reason: str | None = None


class UserUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.USER_UPDATED] = EventType.USER_UPDATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_EVENTS
    user_id: str
    updated_fields: list[str]
    updated_by: str | None = None


class UserDeletedEvent(BaseEvent):
    event_type: Literal[EventType.USER_DELETED] = EventType.USER_DELETED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_EVENTS
    user_id: str
    deleted_by: str | None = None
    reason: str | None = None


class UserSettingsUpdatedEvent(BaseEvent):
    """Unified event for all user settings changes with typed payloads."""

    event_type: Literal[EventType.USER_SETTINGS_UPDATED] = EventType.USER_SETTINGS_UPDATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_SETTINGS_EVENTS
    user_id: str
    changed_fields: list[str]
    # Typed fields for each settings category (Avro-compatible)
    theme: str | None = None
    timezone: str | None = None
    date_format: str | None = None
    time_format: str | None = None
    notifications: NotificationSettingsPayload | None = None
    editor: EditorSettingsPayload | None = None
    reason: str | None = None
