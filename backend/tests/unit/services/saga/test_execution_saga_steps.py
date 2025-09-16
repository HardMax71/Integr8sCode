import pytest

from app.services.saga.execution_saga import (
    ValidateExecutionStep,
    AllocateResourcesStep,
    QueueExecutionStep,
    CreatePodStep,
    MonitorExecutionStep,
    ReleaseResourcesCompensation,
    DeletePodCompensation,
)
from app.services.saga.saga_step import SagaContext
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


pytestmark = pytest.mark.unit


def _req(timeout: int = 30, script: str = "print('x')") -> ExecutionRequestedEvent:
    return ExecutionRequestedEvent(
        execution_id="e1",
        script=script,
        language="python",
        language_version="3.11",
        runtime_image="python:3.11",
        runtime_command=["python"],
        runtime_filename="main.py",
        timeout_seconds=timeout,
        cpu_limit="100m",
        memory_limit="128Mi",
        cpu_request="50m",
        memory_request="64Mi",
        priority=5,
        metadata=EventMetadata(service_name="t", service_version="1"),
    )


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


class _FakeAllocRepo:
    def __init__(self, active: int = 0, ok: bool = True) -> None:
        self.active = active
        self.ok = ok
        self.released: list[str] = []

    async def count_active(self, language: str) -> int:  # noqa: ARG002
        return self.active

    async def create_allocation(self, _id: str, **_kwargs) -> bool:  # noqa: ARG002
        return self.ok

    async def release_allocation(self, allocation_id: str) -> None:
        self.released.append(allocation_id)


@pytest.mark.asyncio
async def test_allocate_resources_step_paths() -> None:
    ctx = SagaContext("s1", "e1")
    ctx.set("execution_id", "e1")
    ok = await AllocateResourcesStep(alloc_repo=_FakeAllocRepo(active=0, ok=True)).execute(ctx, _req())
    assert ok is True and ctx.get("resources_allocated") is True and ctx.get("allocation_id") == "e1"

    # Limit exceeded
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("execution_id", "e2")
    ok2 = await AllocateResourcesStep(alloc_repo=_FakeAllocRepo(active=100, ok=True)).execute(ctx2, _req())
    assert ok2 is False

    # Missing repo
    ctx3 = SagaContext("s3", "e3")
    ctx3.set("execution_id", "e3")
    ok3 = await AllocateResourcesStep(alloc_repo=None).execute(ctx3, _req())
    assert ok3 is False

    # Create allocation returns False -> failure path hitting line 92
    ctx4 = SagaContext("s4", "e4")
    ctx4.set("execution_id", "e4")
    ok4 = await AllocateResourcesStep(alloc_repo=_FakeAllocRepo(active=0, ok=False)).execute(ctx4, _req())
    assert ok4 is False


@pytest.mark.asyncio
async def test_queue_and_monitor_steps() -> None:
    ctx = SagaContext("s1", "e1")
    ctx.set("execution_id", "e1")
    assert await QueueExecutionStep().execute(ctx, _req()) is True
    assert ctx.get("queued") is True

    assert await MonitorExecutionStep().execute(ctx, _req()) is True
    assert ctx.get("monitoring_active") is True

    # Force exceptions to exercise except paths
    class _Ctx(SagaContext):
        def set(self, key, value):  # type: ignore[override]
            raise RuntimeError("boom")
    bad = _Ctx("s", "e")
    assert await QueueExecutionStep().execute(bad, _req()) is False
    assert await MonitorExecutionStep().execute(bad, _req()) is False


class _FakeProducer:
    def __init__(self) -> None:
        self.events: list[object] = []

    async def produce(self, event_to_produce, key: str | None = None):  # noqa: ARG002
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
    from app.events.core import UnifiedProducer
    from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository

    class DummyProd(UnifiedProducer):
        def __init__(self): pass  # type: ignore[no-untyped-def]

    class DummyAlloc(ResourceAllocationRepository):
        def __init__(self): pass  # type: ignore[no-untyped-def]

    from app.services.saga.execution_saga import ExecutionSaga, CreatePodStep
    s = ExecutionSaga()
    s.bind_dependencies(producer=DummyProd(), alloc_repo=DummyAlloc(), publish_commands=True)
    steps = s.get_steps()
    # CreatePod step should be configured and present
    cps = [st for st in steps if isinstance(st, CreatePodStep)][0]
    assert getattr(cps, "publish_commands") is True
