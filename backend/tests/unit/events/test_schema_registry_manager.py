import logging

import pytest
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.settings import Settings

_test_logger = logging.getLogger("test.events.schema_registry_manager")


def test_deserialize_json_execution_requested(test_settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    m = SchemaRegistryManager(test_settings, logger=_test_logger)
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
        "priority": 5,
        "metadata": {"service_name": "t", "service_version": "1.0"},
    }
    ev = m.deserialize_json(data)
    assert isinstance(ev, ExecutionRequestedEvent)
    assert ev.execution_id == "e1"
    assert ev.language == "python"


def test_deserialize_json_missing_type_raises(test_settings: Settings, caplog: pytest.LogCaptureFixture) -> None:
    m = SchemaRegistryManager(test_settings, logger=_test_logger)
    with pytest.raises(ValueError):
        m.deserialize_json({})
