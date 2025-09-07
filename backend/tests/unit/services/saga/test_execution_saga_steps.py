import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.db.repositories.resource_allocation_repository import ResourceAllocationRepository
from app.infrastructure.kafka.events.metadata import EventMetadata
from app.services.saga.execution_saga import (
    AllocateResourcesStep,
    CreatePodStep,
    DeletePodCompensation,
    ExecutionSaga,
    MonitorExecutionStep,
    QueueExecutionStep,
    ReleaseResourcesCompensation,
    RemoveFromQueueCompensation,
    ValidateExecutionStep,
)
from app.services.saga.saga_step import SagaContext


pytestmark = pytest.mark.unit


def _event(script: str = "print(1)", timeout: int = 60) -> ExecutionRequestedEvent:
    return ExecutionRequestedEvent(
        execution_id="e1",
        script=script,
        language="python",
        language_version="3.11",
        runtime_image="python:3.11-slim",
        runtime_command=["python"],
        runtime_filename="main.py",
        timeout_seconds=timeout,
        cpu_limit="500m",
        memory_limit="256Mi",
        cpu_request="250m",
        memory_request="128Mi",
        priority=0,
        metadata=EventMetadata(service_name="svc", service_version="1", user_id="u1"),
    )


@pytest.mark.asyncio
async def test_validate_execution_step_success_and_fail() -> None:
    ctx = SagaContext("s1", "e1")
    step = ValidateExecutionStep()
    assert await step.execute(ctx, _event()) is True

    # too large script
    big = "x" * (1024 * 1024 + 1)
    assert await step.execute(SagaContext("s1", "e1"), _event(script=big)) is False
    # too big timeout
    assert await step.execute(SagaContext("s1", "e1"), _event(timeout=301)) is False
    # get_compensation returns None
    assert step.get_compensation() is None


@pytest.mark.asyncio
async def test_allocate_resources_step_success_and_limit() -> None:
    ctx = SagaContext("s1", "e1")
    alloc_repo = AsyncMock(spec=ResourceAllocationRepository)
    alloc_repo.count_active = AsyncMock(return_value=0)
    alloc_repo.create_allocation = AsyncMock(return_value=True)
    ctx.set("execution_id", "e1")

    step = AllocateResourcesStep(alloc_repo=alloc_repo)
    ok = await step.execute(ctx, _event())
    assert ok is True and ctx.get("resources_allocated") is True

    # resource limit reached
    alloc_repo.count_active = AsyncMock(return_value=100)
    ctx2 = SagaContext("s1", "e1")
    ctx2.set("execution_id", "e1")
    assert await step.execute(ctx2, _event()) is False
    # get_compensation type
    assert isinstance(step.get_compensation(), ReleaseResourcesCompensation)


@pytest.mark.asyncio
async def test_queue_create_monitor_and_compensations() -> None:
    ctx = SagaContext("s1", "e1")
    ctx.set("execution_id", "e1")

    # queue
    q = QueueExecutionStep()
    assert await q.execute(ctx, _event()) is True and ctx.get("queued") is True
    assert isinstance(q.get_compensation(), RemoveFromQueueCompensation)

    # create pod with publish disabled (no producer required)
    cp = CreatePodStep(producer=None, publish_commands=False)
    assert await cp.execute(ctx, _event()) is True and ctx.get("pod_creation_triggered") is not True

    # enable publish and use dummy producer collecting events
    events = []
    class Prod:
        async def produce(self, **kwargs):  # noqa: ANN001
            events.append(kwargs["event_to_produce"])  # type: ignore[index]
    # Create with injected producer and publish enabled
    cp2 = CreatePodStep(producer=Prod(), publish_commands=True)
    assert await cp2.execute(ctx, _event()) is True and ctx.get("pod_creation_triggered") is True
    assert events and events[0].execution_id == "e1"
    assert isinstance(cp2.get_compensation(), DeletePodCompensation)

    # monitor
    m = MonitorExecutionStep()
    assert await m.execute(ctx, _event()) is True and ctx.get("monitoring_active") is True
    # get_compensation is None
    assert m.get_compensation() is None

    # ReleaseResourcesCompensation
    alloc_repo = AsyncMock(spec=ResourceAllocationRepository)
    alloc_repo.release_allocation = AsyncMock(return_value=True)
    comp_rel = ReleaseResourcesCompensation(alloc_repo=alloc_repo)
    ctx.set("allocation_id", "e1")
    assert await comp_rel.compensate(ctx) is True
    # no allocation id path
    ctx.set("allocation_id", None)
    assert await comp_rel.compensate(ctx) is True

    # RemoveFromQueueCompensation when queued
    comp_rem = RemoveFromQueueCompensation()
    ctx.set("queued", True)
    assert await comp_rem.compensate(ctx) is True
    # early return when not queued or no execution_id
    ctx_empty = SagaContext("s1", "e1")
    assert await comp_rem.compensate(ctx_empty) is True

    # DeletePodCompensation only when triggered
    comp_del = DeletePodCompensation(producer=Prod())
    assert await comp_del.compensate(ctx) is True  # pod_creation_triggered may be False => True
    ctx.set("pod_creation_triggered", True)
    assert await comp_del.compensate(ctx) is True

    # CreatePodStep exception path: missing producer and publish enabled
    cp_missing = CreatePodStep(producer=None, publish_commands=True)
    assert await cp_missing.execute(SagaContext("s1","e1"), _event()) is False

    # ReleaseResourcesCompensation missing repo path -> False
    comp_rel2 = ReleaseResourcesCompensation()
    ctx_no_db = SagaContext("s1", "e1"); ctx_no_db.set("allocation_id", "e1")
    assert await comp_rel2.compensate(ctx_no_db) is False


def test_execution_saga_metadata() -> None:
    s = ExecutionSaga()
    assert ExecutionSaga.get_name() == "execution_saga"
    assert ExecutionSaga.get_trigger_events()
    steps = s.get_steps()
    assert [st.name for st in steps][:2] == ["validate_execution", "allocate_resources"]
