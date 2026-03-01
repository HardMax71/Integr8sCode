import dataclasses
from datetime import datetime, timezone
from typing import Any

import pytest
import structlog
from app.db.repositories import ResourceAllocationRepository, SagaRepository
from app.domain.admin import SystemSettings
from app.domain.enums import SagaState
from app.domain.events import (
    DomainEvent,
    EventMetadata,
    ExecutionCompletedEvent,
    ExecutionRequestedEvent,
    ResourceUsageDomain,
)
from app.domain.saga import (
    DomainResourceAllocation,
    DomainResourceAllocationCreate,
    Saga,
    SagaConfig,
    SagaNotFoundError,
)
from app.events.core import UnifiedProducer
from app.services.execution_queue import ExecutionQueueService
from app.services.runtime_settings import RuntimeSettingsLoader
from app.services.saga import ExecutionSaga, SagaOrchestrator

from tests.conftest import make_execution_requested_event

pytestmark = pytest.mark.unit

_test_logger = structlog.get_logger("test.services.saga.orchestrator")


class _FakeRepo(SagaRepository):
    """Fake SagaRepository for testing."""

    def __init__(self) -> None:
        self.saved: list[Saga] = []
        self.existing: dict[tuple[str, str], Saga] = {}
        self.fail_on_create: bool = False

    def _find_by_id(self, saga_id: str) -> Saga | None:
        for saga in [*self.saved, *self.existing.values()]:
            if saga.saga_id == saga_id:
                return saga
        return None

    async def get_or_create_saga(self, saga: Saga) -> tuple[Saga, bool]:
        if self.fail_on_create:
            raise RuntimeError("Simulated DB failure")
        key = (saga.execution_id, saga.saga_name)
        if key in self.existing:
            return self.existing[key], False
        self.existing[key] = saga
        self.saved.append(saga)
        return saga, True

    async def get_saga(self, saga_id: str) -> Saga | None:
        return self._find_by_id(saga_id)

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str) -> Saga | None:
        return self.existing.get((execution_id, saga_name))

    async def save_saga(self, saga_id: str, **updates: Any) -> Saga:
        saga = self._find_by_id(saga_id)
        if not saga:
            raise SagaNotFoundError(saga_id)
        for field, value in updates.items():
            setattr(saga, field, value)
        saga.updated_at = datetime.now(timezone.utc)
        return saga


class _FakeProd(UnifiedProducer):
    """Fake UnifiedProducer for testing."""

    def __init__(self) -> None:
        pass  # Skip parent __init__

    async def produce(
        self, event_to_produce: DomainEvent, key: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        return None


class _FakeAlloc(ResourceAllocationRepository):
    """Fake ResourceAllocationRepository for testing."""

    def __init__(self) -> None:
        self.allocations: list[DomainResourceAllocation] = []

    async def count_active(self, language: str) -> int:
        return 0

    async def create_allocation(self, create_data: DomainResourceAllocationCreate) -> DomainResourceAllocation:
        alloc = DomainResourceAllocation(
            allocation_id="alloc-1",
            **dataclasses.asdict(create_data),
        )
        self.allocations.append(alloc)
        return alloc

    async def release_allocation(self, allocation_id: str) -> bool:
        return True


class _FakeQueue(ExecutionQueueService):
    """Fake ExecutionQueueService for testing."""

    def __init__(self) -> None:
        self.enqueued: list[ExecutionRequestedEvent] = []
        self._pending: list[tuple[str, ExecutionRequestedEvent]] = []
        self.released: list[str] = []
        self._retry_counts: dict[str, int] = {}

    async def enqueue(self, event: ExecutionRequestedEvent) -> int:
        self.enqueued.append(event)
        self._pending.append((event.execution_id, event))
        return len(self._pending) - 1

    async def try_schedule(self, max_active: int) -> tuple[str, ExecutionRequestedEvent] | None:
        if not self._pending:
            return None
        return self._pending.pop(0)

    async def release(self, execution_id: str) -> None:
        self.released.append(execution_id)

    async def remove(self, execution_id: str) -> bool:
        self._pending = [(eid, ev) for eid, ev in self._pending if eid != execution_id]
        return True

    async def increment_retry_count(self, execution_id: str) -> int:
        self._retry_counts[execution_id] = self._retry_counts.get(execution_id, 0) + 1
        return self._retry_counts[execution_id]

    async def update_priority(self, execution_id: str, new_priority: Any) -> bool:
        return True

    async def get_queue_status(self) -> dict[str, int]:
        return {"queue_depth": len(self._pending), "active_count": 0}

    async def get_pending_by_priority(self) -> dict[str, int]:
        return {}


class _FakeRuntimeSettings(RuntimeSettingsLoader):
    """Fake RuntimeSettingsLoader for testing."""

    def __init__(self) -> None:
        pass  # Skip parent __init__

    async def get_effective_settings(self) -> SystemSettings:
        return SystemSettings(
            max_timeout_seconds=30,
            memory_limit="128Mi",
            cpu_limit="100m",
            max_concurrent_executions=10,
            session_timeout_minutes=30,
        )


def _orch(
    repo: SagaRepository | None = None,
    queue: _FakeQueue | None = None,
) -> SagaOrchestrator:
    return SagaOrchestrator(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=True),
        saga_repository=repo or _FakeRepo(),
        producer=_FakeProd(),
        resource_allocation_repository=_FakeAlloc(),
        logger=_test_logger,
        queue_service=queue or _FakeQueue(),
        runtime_settings=_FakeRuntimeSettings(),
    )


@pytest.mark.asyncio
async def test_handle_event_enqueues_and_starts_saga() -> None:
    fake_repo = _FakeRepo()
    fake_queue = _FakeQueue()
    orch = _orch(repo=fake_repo, queue=fake_queue)
    event = make_execution_requested_event(execution_id="e")
    await orch.handle_execution_requested(event)
    # Event was enqueued
    assert len(fake_queue.enqueued) == 1
    assert fake_queue.enqueued[0].execution_id == "e"
    # The saga is created and fully executed (steps run to completion)
    assert len(fake_repo.saved) >= 1
    first_saved = fake_repo.saved[0]
    assert first_saved.execution_id == "e"
    assert first_saved.saga_name == ExecutionSaga.get_name()


@pytest.mark.asyncio
async def test_existing_saga_short_circuits() -> None:
    fake_repo = _FakeRepo()
    fake_queue = _FakeQueue()
    saga_name = ExecutionSaga.get_name()
    s = Saga(saga_id="sX", saga_name=saga_name, execution_id="e", state=SagaState.RUNNING)
    fake_repo.existing[("e", saga_name)] = s
    orch = _orch(repo=fake_repo, queue=fake_queue)
    # Should not create a duplicate — returns existing
    await orch.handle_execution_requested(make_execution_requested_event(execution_id="e"))
    # Event was still enqueued (queue is separate from saga)
    assert len(fake_queue.enqueued) == 1
    # No new sagas saved — existing saga was returned as-is
    assert fake_repo.saved == []
    # Slot stays held — execution is already running, released on completion
    assert fake_queue.released == []


@pytest.mark.asyncio
async def test_resolve_completion_releases_queue() -> None:
    fake_repo = _FakeRepo()
    fake_queue = _FakeQueue()
    orch = _orch(repo=fake_repo, queue=fake_queue)

    # First create a saga
    event = make_execution_requested_event(execution_id="e1")
    await orch.handle_execution_requested(event)

    # Now complete it
    completed_event = ExecutionCompletedEvent(
        execution_id="e1",
        aggregate_id="e1",
        exit_code=0,
        stdout="ok",
        stderr="",
        resource_usage=ResourceUsageDomain(
            execution_time_wall_seconds=1.0,
            cpu_time_jiffies=100,
            clk_tck_hertz=100,
            peak_memory_kb=1024,
        ),
        metadata=EventMetadata(service_name="test", service_version="1.0.0", user_id="u"),
    )
    await orch.handle_execution_completed(completed_event)

    # Execution should be released from queue
    assert "e1" in fake_queue.released


@pytest.mark.asyncio
async def test_start_saga_failure_requeues_execution() -> None:
    fake_repo = _FakeRepo()
    fake_queue = _FakeQueue()
    fake_repo.fail_on_create = True
    orch = _orch(repo=fake_repo, queue=fake_queue)

    event = make_execution_requested_event(execution_id="e1")
    await orch.handle_execution_requested(event)

    # Event was enqueued initially
    assert fake_queue.enqueued[0].execution_id == "e1"
    # Slot was released on failure
    assert "e1" in fake_queue.released
    # Event was re-enqueued so the execution is not lost
    assert len(fake_queue.enqueued) == 2
    assert fake_queue.enqueued[1].execution_id == "e1"


@pytest.mark.asyncio
async def test_resolve_completion_releases_slot_when_saga_already_terminal() -> None:
    """Slot must be released even when the saga is already in a terminal state."""
    fake_repo = _FakeRepo()
    fake_queue = _FakeQueue()
    orch = _orch(repo=fake_repo, queue=fake_queue)

    # Create a saga and move it to TIMEOUT (simulating check_timeouts)
    event = make_execution_requested_event(execution_id="e1")
    await orch.handle_execution_requested(event)
    saga = fake_repo.saved[0]
    saga.state = SagaState.TIMEOUT

    fake_queue.released.clear()

    # Now a COMPLETED event arrives — saga is already terminal
    completed_event = ExecutionCompletedEvent(
        execution_id="e1",
        aggregate_id="e1",
        exit_code=0,
        stdout="ok",
        stderr="",
        resource_usage=ResourceUsageDomain(
            execution_time_wall_seconds=1.0,
            cpu_time_jiffies=100,
            clk_tck_hertz=100,
            peak_memory_kb=1024,
        ),
        metadata=EventMetadata(service_name="test", service_version="1.0.0", user_id="u"),
    )
    await orch.handle_execution_completed(completed_event)

    # Slot released despite saga being already terminal
    assert "e1" in fake_queue.released


@pytest.mark.asyncio
async def test_resolve_completion_releases_slot_when_no_saga_found() -> None:
    """Slot must be released even when no saga record exists."""
    fake_repo = _FakeRepo()
    fake_queue = _FakeQueue()
    orch = _orch(repo=fake_repo, queue=fake_queue)

    completed_event = ExecutionCompletedEvent(
        execution_id="orphan",
        aggregate_id="orphan",
        exit_code=0,
        stdout="ok",
        stderr="",
        resource_usage=ResourceUsageDomain(
            execution_time_wall_seconds=1.0,
            cpu_time_jiffies=100,
            clk_tck_hertz=100,
            peak_memory_kb=1024,
        ),
        metadata=EventMetadata(service_name="test", service_version="1.0.0", user_id="u"),
    )
    await orch.handle_execution_completed(completed_event)

    # Slot released even though no saga was found
    assert "orphan" in fake_queue.released


@pytest.mark.asyncio
async def test_max_retries_exceeded_fails_execution() -> None:
    """After _MAX_SAGA_START_RETRIES failures, the execution is dropped with FAILED state."""
    fake_repo = _FakeRepo()
    fake_queue = _FakeQueue()
    fake_repo.fail_on_create = True
    orch = _orch(repo=fake_repo, queue=fake_queue)

    event = make_execution_requested_event(execution_id="e1")

    # Simulate repeated failures by pre-setting retry count to threshold - 1
    fake_queue._retry_counts["e1"] = orch._MAX_SAGA_START_RETRIES - 1

    await orch.handle_execution_requested(event)

    # Retry count reached max — execution should NOT be re-enqueued a second time
    # (only the initial enqueue from handle_execution_requested)
    assert len(fake_queue.enqueued) == 1
    # Slot was released
    assert "e1" in fake_queue.released


@pytest.mark.asyncio
async def test_retry_count_increments_across_failures() -> None:
    """Each saga start failure increments the retry count via the queue service."""
    fake_repo = _FakeRepo()
    fake_queue = _FakeQueue()
    fake_repo.fail_on_create = True
    orch = _orch(repo=fake_repo, queue=fake_queue)

    event = make_execution_requested_event(execution_id="e1")
    await orch.handle_execution_requested(event)

    # First failure: retry count = 1, event re-enqueued
    assert fake_queue._retry_counts["e1"] == 1
    assert len(fake_queue.enqueued) == 2  # initial + re-enqueue

    # Trigger second attempt (fake queue has the re-enqueued event)
    await orch.try_schedule_from_queue()
    assert fake_queue._retry_counts["e1"] == 2
    assert len(fake_queue.enqueued) == 3  # another re-enqueue

    # Trigger third attempt — should exceed max retries (3 >= 3)
    await orch.try_schedule_from_queue()
    assert fake_queue._retry_counts["e1"] == 3
    # No more re-enqueues after max retries
    assert len(fake_queue.enqueued) == 3
