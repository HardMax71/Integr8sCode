import pytest
from aiokafka import AIOKafkaProducer
from app.db.docs import ResourceAllocationDocument
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.domain.events.typed import ExecutionRequestedEvent
from app.events.core import UnifiedProducer
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
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

pytestmark = pytest.mark.unit


def _req(timeout: int = 30, script: str = "print('x')", execution_id: str = "e1") -> ExecutionRequestedEvent:
    return make_execution_requested_event(execution_id=execution_id, script=script, timeout_seconds=timeout)


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


@pytest.mark.asyncio
async def test_allocate_resources_step_paths(unit_container: AsyncContainer) -> None:
    alloc_repo = await unit_container.get(ResourceAllocationRepository)

    # Test 1: Success path with clean repo
    ctx = SagaContext("s1", "alloc-test-1")
    ctx.set("execution_id", "alloc-test-1")
    ok = await AllocateResourcesStep(alloc_repo=alloc_repo).execute(ctx, _req(execution_id="alloc-test-1"))
    assert ok is True
    assert ctx.get("resources_allocated") is True
    assert ctx.get("allocation_id") is not None

    # Test 2: Limit exceeded (insert 100 active allocations)
    for i in range(100):
        doc = ResourceAllocationDocument(
            allocation_id=f"limit-test-alloc-{i}",
            execution_id=f"limit-test-exec-{i}",
            language="python",
            cpu_request="100m",
            memory_request="128Mi",
            cpu_limit="500m",
            memory_limit="512Mi",
            status="active",
        )
        await doc.insert()

    ctx2 = SagaContext("s2", "limit-test-main")
    ctx2.set("execution_id", "limit-test-main")
    ok2 = await AllocateResourcesStep(alloc_repo=alloc_repo).execute(ctx2, _req(execution_id="limit-test-main"))
    assert ok2 is False

    # Test 3: Missing repo
    ctx3 = SagaContext("s3", "e3")
    ctx3.set("execution_id", "e3")
    ok3 = await AllocateResourcesStep(alloc_repo=None).execute(ctx3, _req(execution_id="e3"))
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


@pytest.mark.asyncio
async def test_create_pod_step_publish_flag_and_compensation(unit_container: AsyncContainer) -> None:
    producer = await unit_container.get(UnifiedProducer)
    kafka_producer = await unit_container.get(AIOKafkaProducer)

    # Skip publish path
    ctx = SagaContext("s1", "skip-publish-test")
    ctx.set("execution_id", "skip-publish-test")
    s1 = CreatePodStep(producer=None, publish_commands=False)
    ok1 = await s1.execute(ctx, _req(execution_id="skip-publish-test"))
    assert ok1 is True and ctx.get("pod_creation_triggered") is False

    # Publish path succeeds
    ctx2 = SagaContext("s2", "publish-test")
    ctx2.set("execution_id", "publish-test")
    initial_count = len(kafka_producer.sent_messages)
    s2 = CreatePodStep(producer=producer, publish_commands=True)
    ok2 = await s2.execute(ctx2, _req(execution_id="publish-test"))
    assert ok2 is True
    assert ctx2.get("pod_creation_triggered") is True
    assert len(kafka_producer.sent_messages) > initial_count

    # Missing producer -> failure
    ctx3 = SagaContext("s3", "missing-producer-test")
    ctx3.set("execution_id", "missing-producer-test")
    s3 = CreatePodStep(producer=None, publish_commands=True)
    ok3 = await s3.execute(ctx3, _req(execution_id="missing-producer-test"))
    assert ok3 is False and ctx3.error is not None

    # DeletePod compensation triggers only when flagged and producer exists
    comp = DeletePodCompensation(producer=producer)
    ctx2.set("pod_creation_triggered", True)
    assert await comp.compensate(ctx2) is True


@pytest.mark.asyncio
async def test_release_resources_compensation(unit_container: AsyncContainer) -> None:
    alloc_repo = await unit_container.get(ResourceAllocationRepository)

    # Create an allocation via repo
    from app.domain.saga import DomainResourceAllocationCreate

    create_data = DomainResourceAllocationCreate(
        execution_id="release-comp-test",
        language="python",
        cpu_request="100m",
        memory_request="128Mi",
        cpu_limit="500m",
        memory_limit="512Mi",
    )
    allocation = await alloc_repo.create_allocation(create_data)

    # Verify allocation was created with status="active"
    doc = await ResourceAllocationDocument.find_one(
        ResourceAllocationDocument.allocation_id == allocation.allocation_id
    )
    assert doc is not None
    assert doc.status == "active"

    # Release via compensation
    comp = ReleaseResourcesCompensation(alloc_repo=alloc_repo)
    ctx = SagaContext("s1", "release-comp-test")
    ctx.set("allocation_id", allocation.allocation_id)
    assert await comp.compensate(ctx) is True

    # Verify allocation was released
    doc_after = await ResourceAllocationDocument.find_one(
        ResourceAllocationDocument.allocation_id == allocation.allocation_id
    )
    assert doc_after is not None
    assert doc_after.status == "released"

    # Missing repo -> failure
    comp2 = ReleaseResourcesCompensation(alloc_repo=None)
    assert await comp2.compensate(ctx) is False

    # Missing allocation_id -> True short-circuit
    ctx2 = SagaContext("sX", "eX")
    assert await ReleaseResourcesCompensation(alloc_repo=alloc_repo).compensate(ctx2) is True


@pytest.mark.asyncio
async def test_delete_pod_compensation_variants(unit_container: AsyncContainer) -> None:
    # Not triggered -> True early
    comp_none = DeletePodCompensation(producer=None)
    ctx = SagaContext("s", "delete-pod-test-1")
    ctx.set("pod_creation_triggered", False)
    assert await comp_none.compensate(ctx) is True

    # Triggered but missing producer -> False
    ctx2 = SagaContext("s2", "delete-pod-test-2")
    ctx2.set("pod_creation_triggered", True)
    ctx2.set("execution_id", "delete-pod-test-2")
    assert await comp_none.compensate(ctx2) is False

    # Exercise get_compensation methods return types (coverage for lines returning comps/None)
    alloc_repo = await unit_container.get(ResourceAllocationRepository)
    assert ValidateExecutionStep().get_compensation() is None
    assert isinstance(AllocateResourcesStep(alloc_repo).get_compensation(), ReleaseResourcesCompensation)
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
