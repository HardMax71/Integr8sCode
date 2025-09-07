from typing import ClassVar, Literal

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.storage import StorageType
from app.infrastructure.kafka.events.base import BaseEvent


# Script Events
class ScriptSavedEvent(BaseEvent):
    event_type: Literal[EventType.SCRIPT_SAVED] = EventType.SCRIPT_SAVED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SCRIPT_EVENTS
    script_id: str
    user_id: str
    title: str
    language: str


class ScriptDeletedEvent(BaseEvent):
    event_type: Literal[EventType.SCRIPT_DELETED] = EventType.SCRIPT_DELETED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SCRIPT_EVENTS
    script_id: str
    user_id: str
    deleted_by: str | None = None


class ScriptSharedEvent(BaseEvent):
    event_type: Literal[EventType.SCRIPT_SHARED] = EventType.SCRIPT_SHARED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SCRIPT_EVENTS
    script_id: str
    shared_by: str
    shared_with: list[str]
    permissions: str


# Security Events
class SecurityViolationEvent(BaseEvent):
    event_type: Literal[EventType.SECURITY_VIOLATION] = EventType.SECURITY_VIOLATION
    topic: ClassVar[KafkaTopic] = KafkaTopic.SECURITY_EVENTS
    user_id: str | None = None
    violation_type: str
    details: str
    ip_address: str | None = None


class RateLimitExceededEvent(BaseEvent):
    event_type: Literal[EventType.RATE_LIMIT_EXCEEDED] = EventType.RATE_LIMIT_EXCEEDED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SECURITY_EVENTS
    user_id: str | None = None
    endpoint: str
    limit: int
    window_seconds: int


class AuthFailedEvent(BaseEvent):
    event_type: Literal[EventType.AUTH_FAILED] = EventType.AUTH_FAILED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SECURITY_EVENTS
    username: str | None = None
    reason: str
    ip_address: str | None = None


# Resource Events
class ResourceLimitExceededEvent(BaseEvent):
    event_type: Literal[EventType.RESOURCE_LIMIT_EXCEEDED] = EventType.RESOURCE_LIMIT_EXCEEDED
    topic: ClassVar[KafkaTopic] = KafkaTopic.RESOURCE_EVENTS
    resource_type: str
    limit: int
    requested: int
    user_id: str | None = None


class QuotaExceededEvent(BaseEvent):
    event_type: Literal[EventType.QUOTA_EXCEEDED] = EventType.QUOTA_EXCEEDED
    topic: ClassVar[KafkaTopic] = KafkaTopic.RESOURCE_EVENTS
    quota_type: str
    limit: int
    current_usage: int
    user_id: str


# System Events
class SystemErrorEvent(BaseEvent):
    event_type: Literal[EventType.SYSTEM_ERROR] = EventType.SYSTEM_ERROR
    topic: ClassVar[KafkaTopic] = KafkaTopic.SYSTEM_EVENTS
    error_type: str
    message: str
    service_name: str
    stack_trace: str | None = None


class ServiceUnhealthyEvent(BaseEvent):
    event_type: Literal[EventType.SERVICE_UNHEALTHY] = EventType.SERVICE_UNHEALTHY
    topic: ClassVar[KafkaTopic] = KafkaTopic.SYSTEM_EVENTS
    service_name: str
    health_check: str
    reason: str


class ServiceRecoveredEvent(BaseEvent):
    event_type: Literal[EventType.SERVICE_RECOVERED] = EventType.SERVICE_RECOVERED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SYSTEM_EVENTS
    service_name: str
    health_check: str
    downtime_seconds: int


# Result Events
class ResultStoredEvent(BaseEvent):
    event_type: Literal[EventType.RESULT_STORED] = EventType.RESULT_STORED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_RESULTS
    execution_id: str
    storage_type: StorageType
    storage_path: str
    size_bytes: int


class ResultFailedEvent(BaseEvent):
    event_type: Literal[EventType.RESULT_FAILED] = EventType.RESULT_FAILED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_RESULTS
    execution_id: str
    error: str
    storage_type: StorageType | None = None
