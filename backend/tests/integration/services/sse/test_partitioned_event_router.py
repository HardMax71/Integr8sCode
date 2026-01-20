import asyncio
import logging
from uuid import uuid4

import pytest
from app.events.core import EventDispatcher
from app.schemas_pydantic.sse import RedisSSEMessage
from app.services.sse.event_router import SSEEventRouter
from app.services.sse.redis_bus import SSERedisBus

from tests.helpers import make_execution_requested_event

pytestmark = [pytest.mark.integration, pytest.mark.redis]

_test_logger = logging.getLogger("test.services.sse.event_router_integration")


@pytest.mark.asyncio
async def test_event_router_bridges_to_redis(
    sse_redis_bus: SSERedisBus,
) -> None:
    """Test that SSEEventRouter routes events to Redis correctly."""
    router = SSEEventRouter(sse_bus=sse_redis_bus, logger=_test_logger)

    # Register handlers with dispatcher
    disp = EventDispatcher(logger=_test_logger)
    router.register_handlers(disp)

    # Open Redis subscription for our execution id
    execution_id = f"e-{uuid4().hex[:8]}"
    subscription = await sse_redis_bus.open_subscription(execution_id)

    # Create and route an event
    ev = make_execution_requested_event(execution_id=execution_id)
    handler = disp.get_handlers(ev.event_type)[0]
    await handler(ev)

    # Await the subscription - verify event arrived in Redis
    msg = await asyncio.wait_for(subscription.get(RedisSSEMessage), timeout=2.0)
    assert msg is not None
    assert str(msg.event_type) == str(ev.event_type)
