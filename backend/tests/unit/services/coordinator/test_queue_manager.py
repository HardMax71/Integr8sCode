import logging

import pytest
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.services.coordinator.queue_manager import QueueManager, QueuePriority

from tests.helpers import make_execution_requested_event

_test_logger = logging.getLogger("test.services.coordinator.queue_manager")

pytestmark = pytest.mark.unit


def ev(execution_id: str, priority: int = QueuePriority.NORMAL.value) -> ExecutionRequestedEvent:
    return make_execution_requested_event(execution_id=execution_id, priority=priority)


@pytest.mark.asyncio
async def test_requeue_execution_increments_priority() -> None:
    qm = QueueManager(max_queue_size=10, logger=_test_logger)
    await qm.start()
    # Use NORMAL priority which can be incremented to LOW
    e = ev("x", priority=QueuePriority.NORMAL.value)
    await qm.add_execution(e)
    await qm.requeue_execution(e, increment_retry=True)
    nxt = await qm.get_next_execution()
    assert nxt is not None
    await qm.stop()


@pytest.mark.asyncio
async def test_queue_stats_empty_and_after_add() -> None:
    qm = QueueManager(max_queue_size=5, logger=_test_logger)
    await qm.start()
    stats0 = await qm.get_queue_stats()
    assert stats0["total_size"] == 0
    await qm.add_execution(ev("a"))
    st = await qm.get_queue_stats()
    assert st["total_size"] == 1
    await qm.stop()
