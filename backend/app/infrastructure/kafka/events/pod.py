from typing import ClassVar, Literal

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.events.base import BaseEvent


class PodCreatedEvent(BaseEvent):
    event_type: Literal[EventType.POD_CREATED] = EventType.POD_CREATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.POD_EVENTS
    execution_id: str
    pod_name: str
    namespace: str


class PodScheduledEvent(BaseEvent):
    event_type: Literal[EventType.POD_SCHEDULED] = EventType.POD_SCHEDULED
    topic: ClassVar[KafkaTopic] = KafkaTopic.POD_EVENTS
    execution_id: str
    pod_name: str
    node_name: str


class PodRunningEvent(BaseEvent):
    event_type: Literal[EventType.POD_RUNNING] = EventType.POD_RUNNING
    topic: ClassVar[KafkaTopic] = KafkaTopic.POD_STATUS_UPDATES
    execution_id: str
    pod_name: str
    container_statuses: str  # JSON serialized list of container statuses


class PodTerminatedEvent(BaseEvent):
    event_type: Literal[EventType.POD_TERMINATED] = EventType.POD_TERMINATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.POD_STATUS_UPDATES
    execution_id: str
    pod_name: str
    exit_code: int
    reason: str | None = None
    message: str | None = None


class PodSucceededEvent(BaseEvent):
    event_type: Literal[EventType.POD_SUCCEEDED] = EventType.POD_SUCCEEDED
    topic: ClassVar[KafkaTopic] = KafkaTopic.POD_STATUS_UPDATES
    execution_id: str
    pod_name: str
    exit_code: int
    stdout: str | None = None
    stderr: str | None = None


class PodFailedEvent(BaseEvent):
    event_type: Literal[EventType.POD_FAILED] = EventType.POD_FAILED
    topic: ClassVar[KafkaTopic] = KafkaTopic.POD_STATUS_UPDATES
    execution_id: str
    pod_name: str
    exit_code: int
    reason: str | None = None
    message: str | None = None
    stdout: str | None = None
    stderr: str | None = None


class PodDeletedEvent(BaseEvent):
    event_type: Literal[EventType.POD_DELETED] = EventType.POD_DELETED
    topic: ClassVar[KafkaTopic] = KafkaTopic.POD_EVENTS
    execution_id: str
    pod_name: str
    reason: str | None = None
