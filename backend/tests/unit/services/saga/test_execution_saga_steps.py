from unittest.mock import AsyncMock

import pytest
import structlog

from app.domain.events import DomainEvent, ExecutionRequestedEvent
from app.events.core import UnifiedProducer
from app.services.saga import (
    CreatePodStep,
    DeletePodCompensation,
    ExecutionSaga,
    SagaContext,
    ValidateExecutionStep,
)
from tests.conftest import make_execution_requested_event

pytestmark = pytest.mark.unit

_logger = structlog.get_logger()


def _req(timeout: int = 30, script: str = "print('x')") -> ExecutionRequestedEvent:
    return make_execution_requested_event(execution_id="e1", script=script, timeout_seconds=timeout)


async def test_validate_execution_step_success_and_failures() -> None:
    ctx = SagaContext("s1", "e1")
    ok = await ValidateExecutionStep(logger=_logger).execute(ctx, _req())
    assert ok is True and ctx.get("execution_id") == "e1"

    # The admin settings bound the timeout (up to 3600 s), so the step accepts their maximum
    ctx2 = SagaContext("s1", "e1")
    assert await ValidateExecutionStep(logger=_logger).execute(ctx2, _req(timeout=3600)) is True
    assert ctx2.get("timeout_seconds") == 3600

    # Script too big → raises
    ctx3 = SagaContext("s1", "e1")
    big = "x" * (1024 * 1024 + 1)
    with pytest.raises(ValueError, match="Script size exceeds limit"):
        await ValidateExecutionStep(logger=_logger).execute(ctx3, _req(script=big))


class _FakeProducer(UnifiedProducer):
    """Fake UnifiedProducer for testing."""

    def __init__(self) -> None:
        self.events: list[DomainEvent] = []

    async def produce(
        self, event_to_produce: DomainEvent, key: str | None = None, headers: dict[str, str] | None = None
    ) -> None:
        self.events.append(event_to_produce)


async def test_create_pod_step_publish_flag_and_compensation() -> None:
    prod = _FakeProducer()

    # Skip publish path
    ctx = SagaContext("s1", "e1")
    ctx.set("execution_id", "e1")
    s1 = CreatePodStep(producer=prod, publish_commands=False, logger=_logger)
    ok1 = await s1.execute(ctx, _req())
    assert ok1 is True and ctx.get("pod_creation_triggered") is False

    # Publish path succeeds
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("execution_id", "e2")
    s2 = CreatePodStep(producer=prod, publish_commands=True, logger=_logger)
    ok2 = await s2.execute(ctx2, _req())
    assert ok2 is True and ctx2.get("pod_creation_triggered") is True and prod.events

    # DeletePod compensation triggers only when flagged and producer exists
    comp = DeletePodCompensation(producer=prod, logger=_logger)
    ctx2.set("pod_creation_triggered", True)
    assert await comp.compensate(ctx2) is True


async def test_delete_pod_compensation_variants() -> None:
    prod = _FakeProducer()

    # Not triggered -> True early
    ctx = SagaContext("s", "e")
    ctx.set("pod_creation_triggered", False)
    assert await DeletePodCompensation(producer=prod, logger=_logger).compensate(ctx) is True

    # Triggered -> publishes delete command
    ctx2 = SagaContext("s2", "e2")
    ctx2.set("pod_creation_triggered", True)
    ctx2.set("execution_id", "e2")
    assert await DeletePodCompensation(producer=prod, logger=_logger).compensate(ctx2) is True
    assert len(prod.events) == 1

    # get_compensation return types
    assert ValidateExecutionStep(logger=_logger).get_compensation() is None
    assert isinstance(
        CreatePodStep(prod, publish_commands=False, logger=_logger).get_compensation(),
        DeletePodCompensation,
    )


def test_execution_saga_bind_and_get_steps_sets_flags_and_types() -> None:
    s = ExecutionSaga()
    s.bind_dependencies(
        producer=AsyncMock(spec=UnifiedProducer),
        publish_commands=True,
        logger=_logger,
    )
    steps = s.get_steps()
    assert [step.name for step in steps] == ["validate_execution", "create_pod"]
    cps = [st for st in steps if isinstance(st, CreatePodStep)][0]
    assert cps.publish_commands is True
