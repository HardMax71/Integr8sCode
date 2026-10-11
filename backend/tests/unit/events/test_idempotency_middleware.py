from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import structlog
from dishka import Provider, Scope, make_async_container
from dishka_faststream import setup_dishka
from faststream.kafka import KafkaBroker, KafkaRouter, TestKafkaBroker

from app.domain.events import EventMetadata, UserRegisteredEvent
from app.domain.idempotency import IdempotencyStatus, KeyStrategy
from app.events.middlewares import idempotent
from app.services.idempotency import IdempotencyManager, IdempotencyResult

pytestmark = pytest.mark.unit


def _event() -> UserRegisteredEvent:
    return UserRegisteredEvent(
        user_id="u1",
        username="alice",
        email="alice@example.com",
        metadata=EventMetadata(service_name="test", service_version="1", user_id="u1"),
    )


def _reservation(is_duplicate: bool) -> IdempotencyResult:
    status = IdempotencyStatus.COMPLETED if is_duplicate else IdempotencyStatus.PROCESSING
    return IdempotencyResult(
        is_duplicate=is_duplicate, status=status, created_at=datetime.now(timezone.utc), key="idempotency:k"
    )


async def _deliver(idem: AsyncMock, handler: AsyncMock) -> None:
    """Publish one event through a router guarded by the middleware, wired the way the workers wire it."""
    provider = Provider(scope=Scope.APP)
    provider.provide(lambda: idem, provides=IdempotencyManager)
    provider.provide(lambda: MagicMock(spec=structlog.stdlib.BoundLogger), provides=structlog.stdlib.BoundLogger)

    router = KafkaRouter(middlewares=(idempotent(KeyStrategy.EVENT_BASED, ttl_seconds=60),))

    @router.subscriber("user_registered", group_id="test")
    async def on_user_registered(body: UserRegisteredEvent) -> None:
        await handler(body)

    broker = KafkaBroker()
    broker.include_router(router)
    setup_dishka(make_async_container(provider), broker=broker, auto_inject=True)
    async with TestKafkaBroker(broker) as test_broker:
        await test_broker.publish(_event(), "user_registered")


async def test_new_key_runs_handler_and_marks_completed() -> None:
    idem = AsyncMock(spec=IdempotencyManager)
    idem.check_and_reserve.return_value = _reservation(is_duplicate=False)
    handler = AsyncMock()

    await _deliver(idem, handler)

    handler.assert_awaited_once()
    assert handler.await_args is not None
    assert handler.await_args.args[0].event_id == idem.check_and_reserve.await_args.kwargs["event"].event_id
    idem.check_and_reserve.assert_awaited_once()
    assert idem.check_and_reserve.await_args.kwargs["key_strategy"] == KeyStrategy.EVENT_BASED
    assert idem.check_and_reserve.await_args.kwargs["ttl_seconds"] == 60
    idem.mark_completed.assert_awaited_once()
    idem.mark_failed.assert_not_awaited()


async def test_duplicate_skips_handler() -> None:
    idem = AsyncMock(spec=IdempotencyManager)
    idem.check_and_reserve.return_value = _reservation(is_duplicate=True)
    handler = AsyncMock()

    await _deliver(idem, handler)

    handler.assert_not_awaited()
    idem.mark_completed.assert_not_awaited()
    idem.mark_failed.assert_not_awaited()


async def test_handler_error_marks_failed_and_propagates() -> None:
    idem = AsyncMock(spec=IdempotencyManager)
    idem.check_and_reserve.return_value = _reservation(is_duplicate=False)
    handler = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await _deliver(idem, handler)

    idem.mark_failed.assert_awaited_once()
    assert idem.mark_failed.await_args is not None
    assert idem.mark_failed.await_args.kwargs["error"] == "boom"
    idem.mark_completed.assert_not_awaited()
