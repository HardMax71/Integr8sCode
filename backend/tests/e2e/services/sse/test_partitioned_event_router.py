import asyncio
import contextlib
from uuid import uuid4

import pytest
import redis.asyncio as redis
import structlog
from opentelemetry import trace

from app.domain.enums import EventType
from app.domain.sse import SSEExecutionEventData
from app.services.sse import SSERedisBus
from app.settings import Settings

pytestmark = [pytest.mark.e2e]

_test_logger = structlog.get_logger("test.services.sse.partitioned_event_router_integration")


async def test_bus_routes_event_to_redis(redis_client: redis.Redis, test_settings: Settings) -> None:
    suffix = uuid4().hex[:6]
    bus = SSERedisBus(
        redis_client,
        logger=_test_logger,
        tracer=trace.NoOpTracer(),
        exec_prefix=f"sse:exec:{suffix}:",
        notif_prefix=f"sse:notif:{suffix}:",
    )

    execution_id = f"e-{uuid4().hex[:8]}"
    ev = SSEExecutionEventData(
        event_type=EventType.EXECUTION_REQUESTED,
        execution_id=execution_id,
    )

    messages = bus.listen_execution(execution_id)
    next_msg = asyncio.ensure_future(anext(messages))
    try:
        # Pub/sub drops messages published before SUBSCRIBE lands, so wait until Redis reports the subscriber
        async with asyncio.timeout(2.0):
            while (await redis_client.pubsub_numsub(f"sse:exec:{suffix}:{execution_id}"))[0][1] == 0:
                await asyncio.sleep(0.01)
        await bus.publish_event(execution_id, ev)
        msg = await asyncio.wait_for(next_msg, timeout=2.0)
    finally:
        next_msg.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await next_msg
        await messages.aclose()

    assert msg is not None
    assert msg.event_type == ev.event_type
