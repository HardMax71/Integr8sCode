import pytest

from tests.helpers import make_execution_requested_event
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.services.idempotency.middleware import idempotent_handler


pytestmark = [pytest.mark.integration]


@pytest.mark.asyncio
async def test_decorator_blocks_duplicate_event(scope) -> None:  # type: ignore[valid-type]
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    calls = {"n": 0}

    @idempotent_handler(idempotency_manager=idm, key_strategy="event_based")
    async def h(ev):  # noqa: ANN001
        calls["n"] += 1

    ev = make_execution_requested_event(execution_id="exec-deco-1")

    await h(ev)
    await h(ev)  # duplicate
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_decorator_custom_key_blocks(scope) -> None:  # type: ignore[valid-type]
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    calls = {"n": 0}

    def fixed_key(_ev):  # noqa: ANN001
        return "fixed-key"

    @idempotent_handler(idempotency_manager=idm, key_strategy="custom", custom_key_func=fixed_key)
    async def h(ev):  # noqa: ANN001
        calls["n"] += 1

    e1 = make_execution_requested_event(execution_id="exec-deco-2a")
    e2 = make_execution_requested_event(execution_id="exec-deco-2b")

    await h(e1)
    await h(e2)  # different event ids but same custom key
    assert calls["n"] == 1
