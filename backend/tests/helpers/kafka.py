from typing import Awaitable, Callable

import pytest

from app.events.core import UnifiedProducer
from app.infrastructure.kafka.events.base import BaseEvent


@pytest.fixture(scope="function")
async def producer(scope) -> UnifiedProducer:  # type: ignore[valid-type]
    """Real Kafka producer from DI scope."""
    return await scope.get(UnifiedProducer)


@pytest.fixture(scope="function")
def send_event(producer: UnifiedProducer) -> Callable[[BaseEvent], Awaitable[None]]:  # type: ignore[valid-type]
    async def _send(ev: BaseEvent) -> None:
        await producer.produce(ev)
    return _send

