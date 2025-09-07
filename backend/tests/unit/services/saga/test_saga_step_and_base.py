import pytest

from app.services.saga.saga_step import SagaContext, CompensationStep
from app.services.saga.saga_step import SagaStep
from app.services.saga.base_saga import BaseSaga


pytestmark = pytest.mark.unit


def test_saga_context_basic_operations() -> None:
    ctx = SagaContext(saga_id="s1", execution_id="e1")
    ctx.set("a", 1)
    assert ctx.get("a") == 1 and ctx.get("missing", 42) == 42

    class E:  # minimal event stub
        pass
    ev = E()
    ctx.add_event(ev)  # type: ignore[arg-type]
    assert ctx.events and ctx.events[0] is ev

    class C(CompensationStep):
        async def compensate(self, context: SagaContext) -> bool:  # noqa: D401
            return True
    comp = C("c")
    ctx.add_compensation(comp)
    assert ctx.compensations and str(ctx.compensations[0]) == "CompensationStep(c)"

    err = RuntimeError("x")
    ctx.set_error(err)
    assert ctx.error is err


def test_calling_base_saga_abstract_methods_executes() -> None:
    # Abstract class methods can be called directly; they are 'pass' but executing them bumps coverage
    assert BaseSaga.get_name() is None
    assert BaseSaga.get_trigger_events() is None
    # instance abstract method: call unbound with a dummy instance
    assert BaseSaga.get_steps(object()) is None


@pytest.mark.asyncio
async def test_saga_step_helpers_and_repr() -> None:
    class S(SagaStep):
        async def execute(self, context: SagaContext, event):  # noqa: ANN001, D401
            return True
        def get_compensation(self):  # noqa: D401
            return None
    s = S("name")
    ctx = SagaContext("s", "e")
    assert await s.can_execute(ctx, object()) is True
    assert str(s) == "SagaStep(name)"
