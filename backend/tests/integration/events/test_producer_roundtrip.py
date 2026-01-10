import logging
from uuid import uuid4

import pytest
from app.events.core import ProducerConfig, UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings
from dishka import AsyncContainer

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.producer_roundtrip")


@pytest.mark.asyncio
async def test_unified_producer_start_produce_send_to_dlq_stop(
    scope: AsyncContainer, test_settings: Settings
) -> None:
    schema: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    prod = UnifiedProducer(
        ProducerConfig(bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS),
        schema,
        logger=_test_logger,
        settings=test_settings,
    )

    async with prod:
        ev = make_execution_requested_event(execution_id=f"exec-{uuid4().hex[:8]}")
        await prod.produce(ev)

        # Exercise send_to_dlq path
        await prod.send_to_dlq(ev, original_topic=str(ev.topic), error=RuntimeError("forced"), retry_count=1)

        st = prod.get_status()
        assert st["running"] is True and st["state"] == "running"
