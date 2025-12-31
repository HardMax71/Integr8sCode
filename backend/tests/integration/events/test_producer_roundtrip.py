import json
import logging
from uuid import uuid4

import pytest
from app.events.core import ProducerConfig, UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.kafka]

_test_logger = logging.getLogger("test.events.producer_roundtrip")


@pytest.mark.asyncio
async def test_unified_producer_start_produce_send_to_dlq_stop(scope):  # type: ignore[valid-type]
    schema: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    prod = UnifiedProducer(ProducerConfig(bootstrap_servers="localhost:9092"), schema, logger=_test_logger)
    await prod.start()

    try:
        ev = make_execution_requested_event(execution_id=f"exec-{uuid4().hex[:8]}")
        await prod.produce(ev)

        # Exercise send_to_dlq path
        await prod.send_to_dlq(ev, original_topic=str(ev.topic), error=RuntimeError("forced"), retry_count=1)

        st = prod.get_status()
        assert st["running"] is True and st["state"] == "running"
    finally:
        await prod.stop()


def test_producer_handle_stats_path():
    # Directly run stats parsing to cover branch logic; avoid relying on timing
    from app.events.core.producer import ProducerMetrics
    from app.events.core.producer import UnifiedProducer as UP

    m = ProducerMetrics()
    p = object.__new__(UP)  # bypass __init__ safely for method call
    # Inject required attributes
    p._metrics = m  # type: ignore[attr-defined]
    p._stats_callback = None  # type: ignore[attr-defined]
    payload = json.dumps({"msg_cnt": 1, "topics": {"t": {"partitions": {"0": {"msgq_cnt": 2, "rtt": {"avg": 5}}}}}})
    UP._handle_stats(p, payload)  # type: ignore[misc]
    assert m.queue_size == 1 and m.avg_latency_ms > 0
