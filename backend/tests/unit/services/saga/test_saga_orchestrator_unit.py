import logging

import pytest
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.db.repositories.saga_repository import SagaRepository
from app.domain.enums import SagaState
from app.domain.events.typed import DomainEvent
from app.domain.saga import DomainResourceAllocation, DomainResourceAllocationCreate
from app.domain.saga.models import Saga, SagaConfig
from app.events.core import UnifiedProducer
from app.services.saga.execution_saga import ExecutionSaga
from app.services.saga.saga_orchestrator import SagaOrchestrator

from tests.conftest import make_execution_requested_event

pytestmark = pytest.mark.unit

_test_logger = logging.getLogger("test.services.saga.orchestrator")


class _FakeRepo(SagaRepository):
    """Fake SagaRepository for testing."""

    def __init__(self) -> None:
        self.saved: list[Saga] = []
        self.existing: dict[tuple[str, str], Saga] = {}

    async def get_or_create_saga(self, saga: Saga) -> tuple[Saga, bool]:
        key = (saga.execution_id, saga.saga_name)
        if key in self.existing:
            return self.existing[key], False
        self.existing[key] = saga
        self.saved.append(saga)
        return saga, True

    async def get_saga_by_execution_and_name(self, execution_id: str, saga_name: str) -> Saga | None:
        return self.existing.get((execution_id, saga_name))

    async def upsert_saga(self, saga: Saga) -> bool:
        self.saved.append(saga)
        return True


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
            **create_data.model_dump(),
        )
        self.allocations.append(alloc)
        return alloc

    async def release_allocation(self, allocation_id: str) -> bool:
        return True


def _orch(repo: SagaRepository | None = None) -> SagaOrchestrator:
    return SagaOrchestrator(
        config=SagaConfig(name="t", enable_compensation=True, store_events=True, publish_commands=False),
        saga_repository=repo or _FakeRepo(),
        producer=_FakeProd(),
        resource_allocation_repository=_FakeAlloc(),
        logger=_test_logger,
    )


@pytest.mark.asyncio
async def test_handle_event_triggers_saga() -> None:
    fake_repo = _FakeRepo()
    orch = _orch(repo=fake_repo)
    await orch.handle_execution_requested(make_execution_requested_event(execution_id="e"))
    # The saga is created and fully executed (steps run to completion)
    assert len(fake_repo.saved) >= 1
    first_saved = fake_repo.saved[0]
    assert first_saved.execution_id == "e"
    assert first_saved.saga_name == ExecutionSaga.get_name()


@pytest.mark.asyncio
async def test_existing_saga_short_circuits() -> None:
    fake_repo = _FakeRepo()
    saga_name = ExecutionSaga.get_name()
    s = Saga(saga_id="sX", saga_name=saga_name, execution_id="e", state=SagaState.RUNNING)
    fake_repo.existing[("e", saga_name)] = s
    orch = _orch(repo=fake_repo)
    # Should not create a duplicate — returns existing
    await orch.handle_execution_requested(make_execution_requested_event(execution_id="e"))
    # No new sagas saved — existing saga was returned as-is
    assert fake_repo.saved == []
