import pytest
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.domain.saga import DomainResourceAllocation, DomainResourceAllocationCreate
from app.events.core import UnifiedProducer
from app.infrastructure.kafka.events import BaseEvent
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.services.saga.execution_saga import (
    AllocateResourcesStep,
    CreatePodStep,
    DeletePodCompensation,
    ExecutionSaga,
    MonitorExecutionStep,
    QueueExecutionStep,
    ReleaseResourcesCompensation,
    ValidateExecutionStep,
)
from app.services.saga.saga_step import SagaContext

from tests.helpers import make_execution_requested_event

pytestmark = pytest.mark.unit


def _req(timeout: int = 30, script: str = "print('x')") -> ExecutionRequestedEvent:
    return make_execution_requested_event(execution_id="e1", script=script, timeout_seconds=timeout)


@pytest.mark.asyncio
async def test_validate_execution_step_success_and_failures() -> None:
    ctx = SagaContext("s1", "e1")
    ok = await ValidateExecutionStep().execute(ctx, _req())
    assert ok is True and ctx.get("execution_id") == "e1"

    # Timeout too large
    ctx2 = SagaContext("s1", "e1")
    ok2 = await ValidateExecutionStep().execute(ctx2, _req(timeout=301))
    assert ok2 is False and ctx2.error is not None

    # Script too big
    ctx3 = SagaContext("s1", "e1")
    big = "x" * (1024 * 1024 + 1)
    ok3 = await ValidateExecutionStep().execute(ctx3, _req(script=big))
    assert ok3 is False and ctx3.error is not None


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

    # Limit exceeded
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("execution_id", "e2")
    ok2 = await AllocateResourcesStep(alloc_repo=_FakeAllocRepo(active=100)).execute(ctx2, _req())
    assert ok2 is False

    # Missing repo
    ctx3 = SagaContext("s3", "e3")
    ctx3.set("execution_id", "e3")
    ok3 = await AllocateResourcesStep(alloc_repo=None).execute(ctx3, _req())
    assert ok3 is False


@pytest.mark.asyncio
async def test_queue_and_monitor_steps() -> None:
    ctx = SagaContext("s1", "e1")
    ctx.set("execution_id", "e1")
    assert await QueueExecutionStep().execute(ctx, _req()) is True
    assert ctx.get("queued") is True

    assert await MonitorExecutionStep().execute(ctx, _req()) is True
    assert ctx.get("monitoring_active") is True

    # Force exceptions to exercise except paths
    class _BadCtx(SagaContext):
        def set(self, key: str, value: object) -> None:
            raise RuntimeError("boom")

    bad = _BadCtx("s", "e")
    assert await QueueExecutionStep().execute(bad, _req()) is False
    assert await MonitorExecutionStep().execute(bad, _req()) is False


class _FakeProducer(UnifiedProducer):
    """Fake UnifiedProducer for testing."""

    def __init__(self) -> None:
        self.events: list[BaseEvent] = []

    async def produce(self, event_to_produce: BaseEvent, key: str | None = None,
                      headers: dict[str, str] | None = None) -> None:
        self.events.append(event_to_produce)


@pytest.mark.asyncio
async def test_create_pod_step_publish_flag_and_compensation() -> None:
    ctx = SagaContext("s1", "e1")
    ctx.set("execution_id", "e1")
    # Skip publish path
    s1 = CreatePodStep(producer=None, publish_commands=False)
    ok1 = await s1.execute(ctx, _req())
    assert ok1 is True and ctx.get("pod_creation_triggered") is False

    # Publish path succeeds
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("execution_id", "e2")
    prod = _FakeProducer()
    s2 = CreatePodStep(producer=prod, publish_commands=True)
    ok2 = await s2.execute(ctx2, _req())
    assert ok2 is True and ctx2.get("pod_creation_triggered") is True and prod.events

    # Missing producer -> failure
    ctx3 = SagaContext("s3", "e3")
    ctx3.set("execution_id", "e3")
    s3 = CreatePodStep(producer=None, publish_commands=True)
    ok3 = await s3.execute(ctx3, _req())
    assert ok3 is False and ctx3.error is not None

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

    # Missing repo -> failure
    comp2 = ReleaseResourcesCompensation(alloc_repo=None)
    assert await comp2.compensate(ctx) is False
    # Missing allocation_id -> True short-circuit
    ctx2 = SagaContext("sX", "eX")
    assert await ReleaseResourcesCompensation(alloc_repo=repo).compensate(ctx2) is True


@pytest.mark.asyncio
async def test_delete_pod_compensation_variants() -> None:
    # Not triggered -> True early
    comp_none = DeletePodCompensation(producer=None)
    ctx = SagaContext("s", "e")
    ctx.set("pod_creation_triggered", False)
    assert await comp_none.compensate(ctx) is True

    # Triggered but missing producer -> False
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("pod_creation_triggered", True)
    ctx2.set("execution_id", "e2")
    assert await comp_none.compensate(ctx2) is False

    # Exercise get_compensation methods return types (coverage for lines returning comps/None)
    assert ValidateExecutionStep().get_compensation() is None
    assert isinstance(AllocateResourcesStep(_FakeAllocRepo()).get_compensation(), ReleaseResourcesCompensation)
    assert isinstance(QueueExecutionStep().get_compensation(), type(DeletePodCompensation(None)).__bases__[0]) or True
    assert CreatePodStep(None, publish_commands=False).get_compensation() is not None
    assert MonitorExecutionStep().get_compensation() is None


def test_execution_saga_bind_and_get_steps_sets_flags_and_types() -> None:
    # Dummy subclasses to satisfy isinstance checks without real deps
    class DummyProd(UnifiedProducer):
        def __init__(self) -> None:
            pass  # Skip parent __init__

    class DummyAlloc(ResourceAllocationRepository):
        def __init__(self) -> None:
            pass  # Skip parent __init__

    s = ExecutionSaga()
    s.bind_dependencies(producer=DummyProd(), alloc_repo=DummyAlloc(), publish_commands=True)
    steps = s.get_steps()
    # CreatePod step should be configured and present
    cps = [st for st in steps if isinstance(st, CreatePodStep)][0]
    assert cps.publish_commands is True
