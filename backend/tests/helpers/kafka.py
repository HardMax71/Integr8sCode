from collections.abc import Awaitable, Callable

import pytest
from app.domain.events.typed import DomainEvent
from app.events.core import UnifiedProducer
from dishka import AsyncContainer


@pytest.fixture(scope="function")
async def producer(scope: AsyncContainer) -> UnifiedProducer:
    """Real Kafka producer from DI scope."""
    prod: UnifiedProducer = await scope.get(UnifiedProducer)
    return prod


@pytest.fixture(scope="function")
def send_event(producer: UnifiedProducer) -> Callable[[DomainEvent], Awaitable[None]]:
    async def _send(ev: DomainEvent) -> None:
        await producer.produce(ev)
    return _send

