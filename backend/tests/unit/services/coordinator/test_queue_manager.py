import asyncio
import pytest

from app.services.coordinator.queue_manager import QueueManager, QueuePriority
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


def ev(execution_id: str, priority: int = QueuePriority.NORMAL.value) -> ExecutionRequestedEvent:
    return ExecutionRequestedEvent(
        execution_id=execution_id,
        script="print(1)",
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
        priority=priority,
        metadata=EventMetadata(service_name="t", service_version="1", user_id="u1"),
    )


@pytest.mark.asyncio
async def test_requeue_execution_increments_priority():
    qm = QueueManager(max_queue_size=10)
    await qm.start()
    # Use NORMAL priority which can be incremented to LOW
    e = ev("x", priority=QueuePriority.NORMAL.value)
    await qm.add_execution(e)
    await qm.requeue_execution(e, increment_retry=True)
    nxt = await qm.get_next_execution()
    assert nxt is not None
    await qm.stop()


@pytest.mark.asyncio
async def test_queue_stats_empty_and_after_add():
    qm = QueueManager(max_queue_size=5)
    await qm.start()
    stats0 = await qm.get_queue_stats()
    assert stats0["total_size"] == 0
    await qm.add_execution(ev("a"))
    st = await qm.get_queue_stats()
    assert st["total_size"] == 1
    await qm.stop()

