import asyncio
import uuid

import pytest

from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.events.core.dispatcher import EventDispatcher as Disp
from tests.helpers import make_execution_requested_event
from app.services.idempotency.idempotency_manager import IdempotencyManager
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.settings import get_settings
from tests.helpers.eventually import eventually

pytestmark = [pytest.mark.integration, pytest.mark.kafka, pytest.mark.redis]


@pytest.mark.asyncio
async def test_consumer_idempotent_wrapper_blocks_duplicates(scope) -> None:  # type: ignore[valid-type]
    producer: UnifiedProducer = await scope.get(UnifiedProducer)
    idm: IdempotencyManager = await scope.get(IdempotencyManager)

    # Build a dispatcher with a counter
    disp: Disp = EventDispatcher()
    seen = {"n": 0}

    @disp.register(EventType.EXECUTION_REQUESTED)
    async def handle(_ev):  # noqa: ANN001
        seen["n"] += 1

    # Real consumer with idempotent wrapper
    settings = get_settings()
    cfg = ConsumerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=f"test-idem-consumer.{uuid.uuid4().hex[:6]}",
        enable_auto_commit=True,
        auto_offset_reset="earliest",
    )
    base = UnifiedConsumer(cfg, event_dispatcher=disp)
    wrapper = IdempotentConsumerWrapper(
        consumer=base,
        idempotency_manager=idm,
        dispatcher=disp,
        default_key_strategy="event_based",
        enable_for_all_handlers=True,
    )

    await wrapper.start([KafkaTopic.EXECUTION_EVENTS])
    try:
        # Produce the same event twice (same event_id)
        execution_id = f"e-{uuid.uuid4().hex[:8]}"
        ev = make_execution_requested_event(execution_id=execution_id)
        await producer.produce(ev, key=execution_id)
        await producer.produce(ev, key=execution_id)

        async def _one():
            assert seen["n"] == 1

        await eventually(_one, timeout=10.0, interval=0.2)
    finally:
        await wrapper.stop()
