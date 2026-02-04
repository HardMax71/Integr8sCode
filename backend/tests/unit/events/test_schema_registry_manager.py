import pytest
from pydantic import ValidationError

from app.domain.enums.execution import QueuePriority
from app.domain.events.typed import DomainEventAdapter, ExecutionRequestedEvent


def test_domain_event_adapter_execution_requested() -> None:
    data = {
        "event_type": "execution_requested",
        "execution_id": "e1",
        "script": "print('ok')",
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
        "priority": QueuePriority.NORMAL,
        "metadata": {"service_name": "t", "service_version": "1.0"},
    }
    ev = DomainEventAdapter.validate_python(data)
    assert isinstance(ev, ExecutionRequestedEvent)
    assert ev.execution_id == "e1"
    assert ev.language == "python"


def test_domain_event_adapter_missing_type_raises() -> None:
    with pytest.raises(ValidationError):
        DomainEventAdapter.validate_python({})
