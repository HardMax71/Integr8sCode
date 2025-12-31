import logging

import pytest

from app.events.schema.schema_registry import SchemaRegistryManager
from tests.helpers import make_execution_requested_event
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.services.idempotency.middleware import IdempotentEventHandler


pytestmark = [pytest.mark.integration]

_test_logger = logging.getLogger("test.idempotency.idempotent_handler")


@pytest.mark.asyncio
async def test_idempotent_handler_blocks_duplicates(scope) -> None:  # type: ignore[valid-type]
    manager: IdempotencyManager = await scope.get(IdempotencyManager)

    processed: list[str] = []

    async def _handler(ev) -> None:  # noqa: ANN001
        processed.append(ev.event_id)

    handler = IdempotentEventHandler(
        handler=_handler,
        idempotency_manager=manager,
        key_strategy="event_based",
        logger=_test_logger,
    )

    ev = make_execution_requested_event(execution_id="exec-dup-1")

    await handler(ev)
    await handler(ev)  # duplicate

    assert processed == [ev.event_id]


@pytest.mark.asyncio
async def test_idempotent_handler_content_hash_blocks_same_content(scope) -> None:  # type: ignore[valid-type]
    manager: IdempotencyManager = await scope.get(IdempotencyManager)

    processed: list[str] = []

    async def _handler(ev) -> None:  # noqa: ANN001
        processed.append(ev.execution_id)

    handler = IdempotentEventHandler(
        handler=_handler,
        idempotency_manager=manager,
        key_strategy="content_hash",
        logger=_test_logger,
    )

    e1 = make_execution_requested_event(execution_id="exec-dup-2")
    e2 = make_execution_requested_event(execution_id="exec-dup-2")

    await handler(e1)
    await handler(e2)

    assert processed == [e1.execution_id]
