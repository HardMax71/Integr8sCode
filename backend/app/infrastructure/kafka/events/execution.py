from datetime import datetime
from typing import ClassVar, Literal

from pydantic import ConfigDict

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.storage import ExecutionErrorType
from app.domain.execution import ResourceUsageDomain
from app.infrastructure.kafka.events.base import BaseEvent


class ExecutionRequestedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_REQUESTED] = EventType.EXECUTION_REQUESTED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_EVENTS
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
    priority: int = 5

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": EventType.EXECUTION_REQUESTED,
                "execution_id": "550e8400-e29b-41d4-a716-446655440000",
                "script": "print('Hello, World!')",
                "language": "python",
                "language_version": "3.11",
                "runtime_image": "python:3.11-slim",
                "runtime_command": ["python"],
                "runtime_filename": "main.py",
                "timeout_seconds": 30,
                "cpu_limit": "100m",
                "memory_limit": "128Mi",
                "cpu_request": "50m",
                "memory_request": "64Mi",
                "priority": 5,
            }
        }
    )


class ExecutionAcceptedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_ACCEPTED] = EventType.EXECUTION_ACCEPTED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_EVENTS
    execution_id: str
    queue_position: int
    estimated_wait_seconds: float | None = None
    priority: int = 5


class ExecutionQueuedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_QUEUED] = EventType.EXECUTION_QUEUED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_EVENTS
    execution_id: str
    position_in_queue: int | None = None
    estimated_start_time: datetime | None = None


class ExecutionRunningEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_RUNNING] = EventType.EXECUTION_RUNNING
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_EVENTS
    execution_id: str
    pod_name: str
    progress_percentage: int | None = None


class ExecutionStartedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_STARTED] = EventType.EXECUTION_STARTED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_EVENTS
    execution_id: str
    pod_name: str
    node_name: str | None = None
    container_id: str | None = None


class ExecutionCompletedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_COMPLETED] = EventType.EXECUTION_COMPLETED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_COMPLETED
    execution_id: str
    exit_code: int
    resource_usage: ResourceUsageDomain
    stdout: str = ""
    stderr: str = ""


class ExecutionFailedEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_FAILED] = EventType.EXECUTION_FAILED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_FAILED
    execution_id: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int
    error_type: ExecutionErrorType
    error_message: str
    resource_usage: ResourceUsageDomain | None = None


class ExecutionTimeoutEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_TIMEOUT] = EventType.EXECUTION_TIMEOUT
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_TIMEOUT
    execution_id: str
    timeout_seconds: int
    resource_usage: ResourceUsageDomain
    stdout: str = ""
    stderr: str = ""


class ExecutionCancelledEvent(BaseEvent):
    event_type: Literal[EventType.EXECUTION_CANCELLED] = EventType.EXECUTION_CANCELLED
    topic: ClassVar[KafkaTopic] = KafkaTopic.EXECUTION_EVENTS
    execution_id: str
    reason: str
    cancelled_by: str | None = None
    force_terminated: bool = False

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "event_type": "execution.cancelled",
                "execution_id": "550e8400-e29b-41d4-a716-446655440000",
                "reason": "user_requested",
                "cancelled_by": "user123",
                "force_terminated": False,
            }
        }
    )
