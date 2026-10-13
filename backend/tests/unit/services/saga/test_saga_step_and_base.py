import pytest

from app.domain.events import SystemErrorEvent
from app.services.saga.saga_step import CompensationStep, SagaContext, SagaStep

pytestmark = pytest.mark.unit


class _DummyComp(CompensationStep):
    def __init__(self) -> None:
        super().__init__("dummy")

    async def compensate(self, context: SagaContext) -> bool:
        return True


async def test_context_add_compensation() -> None:
    ctx = SagaContext("s1", "e1")
    comp = _DummyComp()
    ctx.add_compensation(comp)
    assert len(ctx.compensations) == 1


class _NamedStep(SagaStep[SystemErrorEvent]):
    async def execute(self, context: SagaContext, event: SystemErrorEvent) -> bool:
        return True

    def get_compensation(self) -> CompensationStep | None:
        return None


def test_saga_step_str() -> None:
    s = _NamedStep("nm")
    assert str(s) == "SagaStep(nm)"
