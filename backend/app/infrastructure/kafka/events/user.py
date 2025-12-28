from typing import ClassVar, Literal

from app.domain.enums.auth import LoginMethod, SettingsType
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.events.base import BaseEvent


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
    event_type: Literal[EventType.USER_SETTINGS_UPDATED] = EventType.USER_SETTINGS_UPDATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_SETTINGS_EVENTS
    user_id: str
    settings_type: SettingsType
    updated: dict[str, str]


class UserThemeChangedEvent(BaseEvent):
    event_type: Literal[EventType.USER_THEME_CHANGED] = EventType.USER_THEME_CHANGED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_SETTINGS_THEME_EVENTS
    user_id: str
    old_theme: str
    new_theme: str


class UserNotificationSettingsUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.USER_NOTIFICATION_SETTINGS_UPDATED] = EventType.USER_NOTIFICATION_SETTINGS_UPDATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_SETTINGS_NOTIFICATION_EVENTS
    user_id: str
    settings: dict[str, bool]
    channels: list[str] | None = None


class UserEditorSettingsUpdatedEvent(BaseEvent):
    event_type: Literal[EventType.USER_EDITOR_SETTINGS_UPDATED] = EventType.USER_EDITOR_SETTINGS_UPDATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.USER_SETTINGS_EDITOR_EVENTS
    user_id: str
    settings: dict[str, str | int | bool]
