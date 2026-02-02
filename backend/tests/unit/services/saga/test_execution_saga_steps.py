import pytest
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.domain.events.typed import DomainEvent, ExecutionRequestedEvent
from app.domain.saga import DomainResourceAllocation, DomainResourceAllocationCreate
from app.events.core import UnifiedProducer
from app.services.saga.execution_saga import (
    AllocateResourcesStep,
    CreatePodStep,
    DeletePodCompensation,
    ExecutionSaga,
    ReleaseResourcesCompensation,
    ValidateExecutionStep,
)
from app.services.saga.saga_step import SagaContext

from tests.conftest import make_execution_requested_event

pytestmark = pytest.mark.unit


def _req(timeout: int = 30, script: str = "print('x')") -> ExecutionRequestedEvent:
    return make_execution_requested_event(execution_id="e1", script=script, timeout_seconds=timeout)


@pytest.mark.asyncio
async def test_validate_execution_step_success_and_failures() -> None:
    ctx = SagaContext("s1", "e1")
    ok = await ValidateExecutionStep().execute(ctx, _req())
    assert ok is True and ctx.get("execution_id") == "e1"

    # Timeout too large → raises
    ctx2 = SagaContext("s1", "e1")
    with pytest.raises(ValueError, match="Timeout exceeds maximum"):
        await ValidateExecutionStep().execute(ctx2, _req(timeout=301))

    # Script too big → raises
    ctx3 = SagaContext("s1", "e1")
    big = "x" * (1024 * 1024 + 1)
    with pytest.raises(ValueError, match="Script size exceeds limit"):
        await ValidateExecutionStep().execute(ctx3, _req(script=big))


class _FakeAllocRepo(ResourceAllocationRepository):
    """Fake ResourceAllocationRepository for testing."""

    def __init__(self, active: int = 0, alloc_id: str = "alloc-1") -> None:
        self.active = active
        self.alloc_id = alloc_id
        self.released: list[str] = []

    async def count_active(self, language: str) -> int:
        return self.active

    async def create_allocation(self, create_data: DomainResourceAllocationCreate) -> DomainResourceAllocation:
        return DomainResourceAllocation(
            allocation_id=self.alloc_id,
            execution_id=create_data.execution_id,
            language=create_data.language,
            cpu_request=create_data.cpu_request,
            memory_request=create_data.memory_request,
            cpu_limit=create_data.cpu_limit,
            memory_limit=create_data.memory_limit,
        )

    async def release_allocation(self, allocation_id: str) -> bool:
        self.released.append(allocation_id)
        return True


@pytest.mark.asyncio
async def test_allocate_resources_step_paths() -> None:
    ctx = SagaContext("s1", "e1")
    ctx.set("execution_id", "e1")
    ok = await AllocateResourcesStep(alloc_repo=_FakeAllocRepo(active=0, alloc_id="alloc-1")).execute(ctx, _req())
    assert ok is True and ctx.get("resources_allocated") is True and ctx.get("allocation_id") == "alloc-1"

    # Limit exceeded → raises
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("execution_id", "e2")
    with pytest.raises(ValueError, match="Resource limit exceeded"):
        await AllocateResourcesStep(alloc_repo=_FakeAllocRepo(active=100)).execute(ctx2, _req())


class _FakeProducer(UnifiedProducer):
    """Fake UnifiedProducer for testing."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def produce(self, event_to_produce: DomainEvent, key: str | None = None,
                      headers: dict[str, str] | None = None) -> None:
        self.events.append(event_to_produce)


@pytest.mark.asyncio
async def test_create_pod_step_publish_flag_and_compensation() -> None:
    prod = _FakeProducer()

    # Skip publish path
    ctx = SagaContext("s1", "e1")
    ctx.set("execution_id", "e1")
    s1 = CreatePodStep(producer=prod, publish_commands=False)
    ok1 = await s1.execute(ctx, _req())
    assert ok1 is True and ctx.get("pod_creation_triggered") is False

    # Publish path succeeds
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("execution_id", "e2")
    s2 = CreatePodStep(producer=prod, publish_commands=True)
    ok2 = await s2.execute(ctx2, _req())
    assert ok2 is True and ctx2.get("pod_creation_triggered") is True and prod.events

    # DeletePod compensation triggers only when flagged and producer exists
    comp = DeletePodCompensation(producer=prod)
    ctx2.set("pod_creation_triggered", True)
    assert await comp.compensate(ctx2) is True


@pytest.mark.asyncio
async def test_release_resources_compensation() -> None:
    repo = _FakeAllocRepo()
    comp = ReleaseResourcesCompensation(alloc_repo=repo)
    ctx = SagaContext("s1", "e1")
    ctx.set("allocation_id", "alloc-1")
    assert await comp.compensate(ctx) is True and repo.released == ["alloc-1"]

    # Missing allocation_id -> True short-circuit
    ctx2 = SagaContext("sX", "eX")
    assert await ReleaseResourcesCompensation(alloc_repo=repo).compensate(ctx2) is True


@pytest.mark.asyncio
async def test_delete_pod_compensation_variants() -> None:
    prod = _FakeProducer()

    # Not triggered -> True early
    ctx = SagaContext("s", "e")
    ctx.set("pod_creation_triggered", False)
    assert await DeletePodCompensation(producer=prod).compensate(ctx) is True

    # Triggered -> publishes delete command
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("pod_creation_triggered", True)
    ctx2.set("execution_id", "e2")
    assert await DeletePodCompensation(producer=prod).compensate(ctx2) is True
    assert len(prod.events) == 1

    # get_compensation return types
    assert ValidateExecutionStep().get_compensation() is None
    assert isinstance(AllocateResourcesStep(_FakeAllocRepo()).get_compensation(), ReleaseResourcesCompensation)
    assert isinstance(CreatePodStep(prod, publish_commands=False).get_compensation(), DeletePodCompensation)


def test_execution_saga_bind_and_get_steps_sets_flags_and_types() -> None:
    class DummyProd(UnifiedProducer):
        def __init__(self) -> None:
            pass

    class DummyAlloc(ResourceAllocationRepository):
        def __init__(self) -> None:
            pass

    s = ExecutionSaga()
    s.bind_dependencies(producer=DummyProd(), alloc_repo=DummyAlloc(), publish_commands=True)
    steps = s.get_steps()
    assert len(steps) == 3
    cps = [st for st in steps if isinstance(st, CreatePodStep)][0]
    assert cps.publish_commands is True
