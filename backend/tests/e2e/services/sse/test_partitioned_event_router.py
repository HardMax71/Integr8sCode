import asyncio
import structlog
from uuid import uuid4

import pytest
import redis.asyncio as redis
from app.services.sse import SSERedisBus
from app.settings import Settings

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.redis]

_test_logger = structlog.get_logger("test.services.sse.partitioned_event_router_integration")


@pytest.mark.asyncio
async def test_bus_routes_event_to_redis(redis_client: redis.Redis, test_settings: Settings) -> None:
    suffix = uuid4().hex[:6]
    bus = SSERedisBus(
        redis_client,
        exec_prefix=f"sse:exec:{suffix}:",
        notif_prefix=f"sse:notif:{suffix}:",
        logger=_test_logger,
    )

    execution_id = f"e-{uuid4().hex[:8]}"
    ev = make_execution_requested_event(execution_id=execution_id)

    # Start generator (subscription happens on first __anext__) and publish concurrently.
    # By the time publish fires (~1 Redis RTT), the subscribe is already established.
    messages = bus.listen_execution(execution_id)
    pub_task = asyncio.create_task(bus.publish_event(execution_id, ev))
    msg = await asyncio.wait_for(messages.__anext__(), timeout=2.0)
    await pub_task

    assert msg is not None
    assert str(msg.event_type) == str(ev.event_type)
