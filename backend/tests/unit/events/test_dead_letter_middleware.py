from unittest.mock import AsyncMock, MagicMock

import pytest
from aiokafka.errors import KafkaError
from dishka import Provider, Scope, make_async_container
from dishka_faststream import setup_dishka
from faststream.kafka import KafkaBroker, KafkaRouter, TestKafkaBroker

from app.core.metrics import DLQMetrics
from app.db import DLQRepository
from app.dlq import DLQ_GROUP_HEADER, DLQ_RETRY_HEADER, DLQMessage, DLQMessageStatus
from app.dlq.manager import DLQManager
from app.domain.events import EventMetadata, UserRegisteredEvent
from app.events.middlewares import DeadLetterMiddleware, RetryTargetMiddleware
from app.settings import Settings

pytestmark = pytest.mark.unit


def _event() -> UserRegisteredEvent:
    return UserRegisteredEvent(
        user_id="u1",
        username="alice",
        email="alice@example.com",
        metadata=EventMetadata(service_name="auth-service", service_version="1", user_id="u1"),
    )


class _Subscriber:
    """Hands each delivered event to the test's mock, so the test sees what the handler got."""

    def __init__(self, handler: AsyncMock) -> None:
        self.handler = handler

    async def on_user_registered(self, body: UserRegisteredEvent) -> None:
        await self.handler(body)


async def _deliver(manager: AsyncMock, handler: AsyncMock, headers: dict[str, str] | None = None) -> None:
    """Publish one event to a group-a subscriber, wired the way the workers wire it."""
    provider = Provider(scope=Scope.APP)
    provider.from_context(provides=DLQManager, scope=Scope.APP)

    router = KafkaRouter(middlewares=(DeadLetterMiddleware,))
    router.subscriber("user_registered", group_id="group-a")(_Subscriber(handler).on_user_registered)

    broker = KafkaBroker(middlewares=(RetryTargetMiddleware,))
    broker.include_router(router)
    setup_dishka(make_async_container(provider, context={DLQManager: manager}), broker=broker, auto_inject=True)
    async with TestKafkaBroker(broker) as test_broker:
        await test_broker.publish(_event(), "user_registered", headers=headers)


async def test_failure_is_saved_for_the_failing_group_and_propagates() -> None:
    manager = AsyncMock(spec=DLQManager)
    handler = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(RuntimeError, match="boom"):
        await _deliver(manager, handler, headers={DLQ_GROUP_HEADER: "group-a", DLQ_RETRY_HEADER: "2"})

    manager.handle_message.assert_awaited_once()
    assert manager.handle_message.await_args is not None
    saved: DLQMessage = manager.handle_message.await_args.args[0]
    assert saved.event.event_type == "user_registered"
    assert saved.original_topic == "user_registered"
    assert saved.consumer_group == "group-a"
    assert saved.error == "boom"
    assert saved.retry_count == 2
    assert saved.producer_id == "auth-service"


async def test_success_saves_nothing() -> None:
    manager = AsyncMock(spec=DLQManager)
    handler = AsyncMock()

    await _deliver(manager, handler)

    handler.assert_awaited_once()
    manager.handle_message.assert_not_awaited()


@pytest.mark.parametrize(
    ("headers", "runs"),
    [
        (None, True),
        ({DLQ_GROUP_HEADER: "group-a", DLQ_RETRY_HEADER: "1"}, True),
        ({DLQ_GROUP_HEADER: "group-b", DLQ_RETRY_HEADER: "1"}, False),
    ],
)
async def test_retry_runs_only_in_the_group_it_names(headers: dict[str, str] | None, runs: bool) -> None:
    handler = AsyncMock()

    await _deliver(AsyncMock(spec=DLQManager), handler, headers=headers)

    assert handler.await_count == (1 if runs else 0)


async def test_retry_publishes_to_the_original_topic_for_the_failed_group(test_settings: Settings) -> None:
    broker = AsyncMock(spec=KafkaBroker)
    repository = AsyncMock(spec=DLQRepository)
    manager = DLQManager(test_settings, broker, MagicMock(), MagicMock(spec=DLQMetrics), repository)
    message = DLQMessage(event=_event(), original_topic="user_registered", consumer_group="group-a", retry_count=1)

    await manager.retry_message(message)

    retry_publish = broker.publish.await_args_list[0]
    assert retry_publish.kwargs["topic"] == "user_registered"
    assert retry_publish.kwargs["headers"] == {DLQ_GROUP_HEADER: "group-a", DLQ_RETRY_HEADER: "2"}
    status_update = repository.update_status.await_args
    assert status_update is not None
    assert status_update.args[:2] == (message.event.event_id, "group-a")
    assert status_update.args[2].retry_count == 2


async def test_failed_retry_publish_puts_the_row_back(test_settings: Settings) -> None:
    broker = AsyncMock(spec=KafkaBroker)
    broker.publish.side_effect = KafkaError("broker down")
    repository = AsyncMock(spec=DLQRepository)
    manager = DLQManager(test_settings, broker, MagicMock(), MagicMock(spec=DLQMetrics), repository)
    message = DLQMessage(event=_event(), original_topic="user_registered", consumer_group="group-a", retry_count=1)

    with pytest.raises(KafkaError):
        await manager.retry_message(message)

    updates = [c.args[2] for c in repository.update_status.await_args_list]
    assert [(u.status, u.retry_count) for u in updates] == [
        (DLQMessageStatus.RETRIED, 2),
        (DLQMessageStatus.SCHEDULED, 1),
    ]
