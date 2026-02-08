import pytest
from app.domain.events import SystemErrorEvent
from app.services.saga.saga_step import CompensationStep, SagaContext, SagaStep

pytestmark = pytest.mark.unit


def test_saga_context_public_dict_filters_and_encodes() -> None:
    ctx = SagaContext("s1", "e1")
    ctx.set("a", 1)
    ctx.set("b", {"x": 2})
    ctx.set("c", [1, 2, 3])
    ctx.set("_private", {"won't": "leak"})

    # Complex non-JSON object -> should be dropped
    class X:
        pass

    ctx.set("complex", X())
    # Nested complex objects get encoded by jsonable_encoder
    # The nested dict with a complex object gets partially encoded
    ctx.set("nested", {"ok": 1, "bad": X()})

    d = ctx.to_public_dict()
    # jsonable_encoder converts unknown objects to {}, which is still considered "simple"
    # so they pass through the filter
    assert d == {"a": 1, "b": {"x": 2}, "c": [1, 2, 3], "complex": {}, "nested": {"ok": 1, "bad": {}}}


class _DummyComp(CompensationStep):
    def __init__(self) -> None:
        super().__init__("dummy")

    async def compensate(self, context: SagaContext) -> bool:  # noqa: ARG002
        return True


@pytest.mark.asyncio
async def test_context_add_compensation() -> None:
    ctx = SagaContext("s1", "e1")
    comp = _DummyComp()
    ctx.add_compensation(comp)
    assert len(ctx.compensations) == 1


def test_saga_step_str() -> None:
    class S(SagaStep[SystemErrorEvent]):
        async def execute(self, context: SagaContext, event: SystemErrorEvent) -> bool:
            return True

        def get_compensation(self) -> CompensationStep | None:
            return None

    s = S("nm")
    assert str(s) == "SagaStep(nm)"
