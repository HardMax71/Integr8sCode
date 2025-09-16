import pytest

from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.services.coordinator.coordinator import ExecutionCoordinator


def _mk_request(execution_id: str = "e-1") -> ExecutionRequestedEvent:
    return ExecutionRequestedEvent(
        execution_id=execution_id,
        script="print(1)",
        language="python",
        language_version="3.11",
        runtime_image="python:3.11-slim",
        runtime_command=["python"],
        runtime_filename="main.py",
        timeout_seconds=10,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        priority=5,
        metadata=EventMetadata(service_name="tests", service_version="1", user_id="u1"),
    )


@pytest.mark.asyncio
async def test_handle_requested_and_schedule(scope) -> None:  # type: ignore[valid-type]
    coord: ExecutionCoordinator = await scope.get(ExecutionCoordinator)
    ev = _mk_request("e-real-1")

    # Directly route requested event (no Kafka consumer)
    await coord._handle_execution_requested(ev)  # noqa: SLF001

    pos = await coord.queue_manager.get_queue_position("e-real-1")
    assert pos is not None

    # Schedule one execution from queue
    next_ev = await coord.queue_manager.get_next_execution()
    assert next_ev is not None and next_ev.execution_id == "e-real-1"
    await coord._schedule_execution(next_ev)  # noqa: SLF001
    # Should be tracked as active
    assert "e-real-1" in coord._active_executions  # noqa: SLF001

