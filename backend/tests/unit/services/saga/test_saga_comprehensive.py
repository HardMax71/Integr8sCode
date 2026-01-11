"""Trimmed, fast unit tests for saga essentials.

This file intentionally focuses on deterministic, pure logic checks that don't
require heavy mocking or external services. Full end‑to‑end behavior is covered
by integration tests under tests/integration/saga/.
"""

import pytest
from app.domain.enums.events import EventType
from app.domain.enums.saga import SagaState
from app.domain.saga.models import Saga
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.services.saga.execution_saga import ExecutionSaga
from app.services.saga.saga_step import CompensationStep, SagaContext, SagaStep

from tests.helpers import make_execution_requested_event

pytestmark = pytest.mark.unit


class _NoopComp(CompensationStep):
    async def compensate(self, context: SagaContext) -> bool:  # noqa: ARG002
        return True


class _Step(SagaStep[BaseEvent]):
    def __init__(self, name: str, ok: bool = True) -> None:
        super().__init__(name)
        self._ok = ok

    async def execute(self, context: SagaContext, event: BaseEvent) -> bool:  # noqa: ARG002
        return self._ok

    def get_compensation(self) -> CompensationStep:
        return _NoopComp(f"{self.name}-comp")


def _req_event() -> ExecutionRequestedEvent:
    return make_execution_requested_event(execution_id="e1", script="print('x')")


def test_saga_context_public_filtering() -> None:
    ctx = SagaContext("s1", "e1")
    ctx.set("public", 1)
    ctx.set("_private", 2)
    out = ctx.to_public_dict()
    assert "public" in out and "_private" not in out


def test_execution_saga_triggers_on_request() -> None:
    # No orchestrator needed: this is pure metadata
    assert EventType.EXECUTION_REQUESTED in ExecutionSaga.get_trigger_events()


@pytest.mark.asyncio
async def test_step_success_and_compensation_chain() -> None:
    ctx = SagaContext("s1", "e1")
    s_ok = _Step("ok", ok=True)
    s_fail = _Step("fail", ok=False)
    ctx.add_compensation(s_ok.get_compensation())
    evt = _req_event()
    assert await s_ok.execute(ctx, evt) is True
    assert await s_fail.execute(ctx, evt) is False


def test_saga_state_transitions_minimal() -> None:
    s = Saga(saga_id="s1", saga_name="execution_saga", execution_id="e1", state=SagaState.RUNNING)
    s.state = SagaState.COMPLETED
    assert s.state is SagaState.COMPLETED
    s.state = SagaState.FAILED
    assert s.state is SagaState.FAILED
