"""Saga-related Kafka events."""

from datetime import datetime
from typing import ClassVar, Literal

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.infrastructure.kafka.events.base import BaseEvent


class SagaStartedEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_STARTED] = EventType.SAGA_STARTED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_EVENTS
    saga_id: str
    saga_name: str
    execution_id: str
    initial_event_id: str


class SagaCompletedEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_COMPLETED] = EventType.SAGA_COMPLETED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_EVENTS
    saga_id: str
    saga_name: str
    execution_id: str
    completed_steps: list[str]


class SagaFailedEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_FAILED] = EventType.SAGA_FAILED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_EVENTS
    saga_id: str
    saga_name: str
    execution_id: str
    failed_step: str
    error: str


class SagaCancelledEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_CANCELLED] = EventType.SAGA_CANCELLED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_EVENTS
    saga_id: str
    saga_name: str
    execution_id: str
    reason: str
    completed_steps: list[str]
    compensated_steps: list[str]
    cancelled_at: datetime | None = None
    cancelled_by: str | None = None


class SagaCompensatingEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_COMPENSATING] = EventType.SAGA_COMPENSATING
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_EVENTS
    saga_id: str
    saga_name: str
    execution_id: str
    compensating_step: str


class SagaCompensatedEvent(BaseEvent):
    event_type: Literal[EventType.SAGA_COMPENSATED] = EventType.SAGA_COMPENSATED
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_EVENTS
    saga_id: str
    saga_name: str
    execution_id: str
    compensated_steps: list[str]


# Saga Command Events
class CreatePodCommandEvent(BaseEvent):
    event_type: Literal[EventType.CREATE_POD_COMMAND] = EventType.CREATE_POD_COMMAND
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_COMMANDS
    saga_id: str
    execution_id: str
    script: str
    language: str
    language_version: str
    runtime_image: str
    runtime_command: list[str]
    runtime_filename: str
    timeout_seconds: int
    cpu_limit: str
    memory_limit: str
    cpu_request: str
    memory_request: str
    priority: int
    pod_spec: dict[str, str | int | list[str]] | None = None


class DeletePodCommandEvent(BaseEvent):
    event_type: Literal[EventType.DELETE_POD_COMMAND] = EventType.DELETE_POD_COMMAND
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_COMMANDS
    saga_id: str
    execution_id: str
    reason: str
    pod_name: str | None = None
    namespace: str | None = None


class AllocateResourcesCommandEvent(BaseEvent):
    event_type: Literal[EventType.ALLOCATE_RESOURCES_COMMAND] = EventType.ALLOCATE_RESOURCES_COMMAND
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_COMMANDS
    execution_id: str
    cpu_request: str
    memory_request: str


class ReleaseResourcesCommandEvent(BaseEvent):
    event_type: Literal[EventType.RELEASE_RESOURCES_COMMAND] = EventType.RELEASE_RESOURCES_COMMAND
    topic: ClassVar[KafkaTopic] = KafkaTopic.SAGA_COMMANDS
    execution_id: str
    cpu_request: str
    memory_request: str
