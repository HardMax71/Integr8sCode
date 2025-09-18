import uuid
from typing import Iterable

from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


def make_execution_requested_event(
    *,
    execution_id: str | None = None,
    script: str = "print('hello')",
    language: str = "python",
    language_version: str = "3.11",
    runtime_image: str = "python:3.11-slim",
    runtime_command: Iterable[str] = ("python",),
    runtime_filename: str = "main.py",
    timeout_seconds: int = 5,
    cpu_limit: str = "100m",
    memory_limit: str = "128Mi",
    cpu_request: str = "50m",
    memory_request: str = "64Mi",
    priority: int = 5,
    service_name: str = "tests",
    service_version: str = "1.0.0",
    user_id: str | None = None,
) -> ExecutionRequestedEvent:
    """Factory for ExecutionRequestedEvent with sensible defaults.

    Override any field via keyword args. If no execution_id is provided, a random one is generated.
    """
    if execution_id is None:
        execution_id = f"exec-{uuid.uuid4().hex[:8]}"

    metadata = EventMetadata(service_name=service_name, service_version=service_version, user_id=user_id)
    return ExecutionRequestedEvent(
        execution_id=execution_id,
        script=script,
        language=language,
        language_version=language_version,
        runtime_image=runtime_image,
        runtime_command=list(runtime_command),
        runtime_filename=runtime_filename,
        timeout_seconds=timeout_seconds,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        cpu_request=cpu_request,
        memory_request=memory_request,
        priority=priority,
        metadata=metadata,
    )
