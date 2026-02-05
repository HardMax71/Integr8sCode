import pytest
from app.domain.enums.execution import QueuePriority
from app.domain.events.typed import BaseEvent, EventMetadata, ExecutionRequestedEvent
from pydantic import ValidationError


def test_execution_requested_event_validation() -> None:
    """Test that ExecutionRequestedEvent can be instantiated with valid data."""
    ev = ExecutionRequestedEvent(
        execution_id="e1",
        script="print('ok')",
        language="python",
        language_version="3.11",
        runtime_image="python:3.11-slim",
        runtime_command=["python"],
        runtime_filename="main.py",
        timeout_seconds=30,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        priority=QueuePriority.NORMAL,
        metadata=EventMetadata(service_name="t", service_version="1.0"),
    )
    assert isinstance(ev, ExecutionRequestedEvent)
    assert ev.execution_id == "e1"
    assert ev.language == "python"


def test_execution_requested_event_topic() -> None:
    """Test that ExecutionRequestedEvent has correct topic."""
    assert ExecutionRequestedEvent.topic() == "execution_requested"


def test_event_missing_required_fields_raises() -> None:
    """Test that missing required fields raise ValidationError."""
    with pytest.raises(ValidationError):
        ExecutionRequestedEvent(  # type: ignore[call-arg]
            execution_id="e1",
            # Missing all other required fields
            metadata=EventMetadata(service_name="t", service_version="1.0"),
        )


def test_base_event_topic_derivation() -> None:
    """Test that topic is derived correctly from class name."""
    # BaseEvent itself should have topic 'base' (class name without 'Event')
    assert BaseEvent.topic() == "base"

    # Subclasses should have their own topics
    assert ExecutionRequestedEvent.topic() == "execution_requested"
