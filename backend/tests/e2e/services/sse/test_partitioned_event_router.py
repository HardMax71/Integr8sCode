import asyncio
import logging
from uuid import uuid4

import pytest
import redis.asyncio as redis
from app.schemas_pydantic.sse import RedisSSEMessage
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings

from tests.conftest import make_execution_requested_event

pytestmark = [pytest.mark.e2e, pytest.mark.redis]

_test_logger = logging.getLogger("test.services.sse.partitioned_event_router_integration")


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
    subscription = await bus.open_subscription(execution_id)

    ev = make_execution_requested_event(execution_id=execution_id)
    await bus.route_domain_event(ev)

    msg = await asyncio.wait_for(subscription.get(RedisSSEMessage), timeout=2.0)
    assert msg is not None
    assert msg.event_type == type(ev).topic()
