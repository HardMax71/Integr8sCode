import logging
from collections.abc import Callable
from typing import Any

import pytest
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.services.idempotency.middleware import IdempotentEventHandler
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration]

_test_logger = logging.getLogger("test.idempotency.idempotent_handler")


@pytest.mark.asyncio
async def test_idempotent_handler_blocks_duplicates(scope: AsyncContainer, unique_id: Callable[[str], str]) -> None:
    manager: IdempotencyManager = await scope.get(IdempotencyManager)

    processed: list[str] = []

    async def _handler(ev: Any) -> None:
        processed.append(ev.event_id)

    handler = IdempotentEventHandler(
        handler=_handler,
        idempotency_manager=manager,
        key_strategy="event_based",
        logger=_test_logger,
    )

    ev = make_execution_requested_event(execution_id=unique_id("exec-"))

    await handler(ev)
    await handler(ev)  # duplicate

    assert processed == [ev.event_id]


@pytest.mark.asyncio
async def test_idempotent_handler_content_hash_blocks_same_content(
    scope: AsyncContainer, unique_id: Callable[[str], str]
) -> None:
    manager: IdempotencyManager = await scope.get(IdempotencyManager)

    processed: list[str] = []

    async def _handler(ev: Any) -> None:
        processed.append(ev.execution_id)

    handler = IdempotentEventHandler(
        handler=_handler,
        idempotency_manager=manager,
        key_strategy="content_hash",
        logger=_test_logger,
    )

    # Same execution_id means same content hash
    execution_id = unique_id("exec-")
    e1 = make_execution_requested_event(execution_id=execution_id)
    e2 = make_execution_requested_event(execution_id=execution_id)

    await handler(e1)
    await handler(e2)

    assert processed == [e1.execution_id]
