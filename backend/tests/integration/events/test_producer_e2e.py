import asyncio
import json
from uuid import uuid4

import pytest

from app.events.core import UnifiedProducer, ProducerConfig
from app.events.schema.schema_registry import SchemaRegistryManager
from app.infrastructure.kafka.events.execution import ExecutionRequestedEvent
from app.infrastructure.kafka.events.metadata import EventMetadata


pytestmark = [pytest.mark.integration, pytest.mark.kafka]


@pytest.mark.asyncio
async def test_unified_producer_start_produce_send_to_dlq_stop(scope):  # type: ignore[valid-type]
    schema: SchemaRegistryManager = await scope.get(SchemaRegistryManager)
    prod = UnifiedProducer(ProducerConfig(bootstrap_servers="localhost:9092"), schema)
    await prod.start()

    try:
        ev = ExecutionRequestedEvent(
            execution_id=f"exec-{uuid4().hex[:8]}",
            script="print('x')",
            language="python",
            language_version="3.11",
            runtime_image="python:3.11-slim",
            runtime_command=["python", "-c"],
            runtime_filename="main.py",
            timeout_seconds=5,
            cpu_limit="100m",
            memory_limit="128Mi",
            cpu_request="50m",
            memory_request="64Mi",
            metadata=EventMetadata(service_name="tests", service_version="1.0"),
        )
        await prod.produce(ev)

        # Exercise send_to_dlq path
        await prod.send_to_dlq(ev, original_topic=str(ev.topic), error=RuntimeError("forced"), retry_count=1)

        # Nudge the poll loop to deliver
        await asyncio.sleep(0.5)

        st = prod.get_status()
        assert st["running"] is True and st["state"] == "running"
    finally:
        await prod.stop()


def test_producer_handle_stats_path():
    # Directly run stats parsing to cover branch logic; avoid relying on timing
    from app.events.core.producer import UnifiedProducer as UP, ProducerMetrics
    m = ProducerMetrics()
    p = object.__new__(UP)  # bypass __init__ safely for method call
    # Inject required attributes
    p._metrics = m  # type: ignore[attr-defined]
    p._stats_callback = None  # type: ignore[attr-defined]
    payload = json.dumps({
        "msg_cnt": 1,
        "topics": {
            "t": {"partitions": {"0": {"msgq_cnt": 2, "rtt": {"avg": 5}}}}
        }
    })
    UP._handle_stats(p, payload)  # type: ignore[misc]
    assert m.queue_size == 1 and m.avg_latency_ms > 0

