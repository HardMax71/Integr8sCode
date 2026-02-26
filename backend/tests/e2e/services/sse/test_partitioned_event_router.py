import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
import redis.asyncio as redis
import structlog
from app.core.metrics import ConnectionMetrics
from app.domain.enums import EventType
from app.domain.sse import SSEExecutionEventData
from app.services.sse import SSERedisBus
from app.settings import Settings

pytestmark = [pytest.mark.e2e, pytest.mark.redis]

_test_logger = structlog.get_logger("test.services.sse.partitioned_event_router_integration")


@pytest.mark.asyncio
async def test_bus_routes_event_to_redis(redis_client: redis.Redis, test_settings: Settings) -> None:
    suffix = uuid4().hex[:6]
    bus = SSERedisBus(
        redis_client,
        logger=_test_logger,
        connection_metrics=MagicMock(spec=ConnectionMetrics),
        exec_prefix=f"sse:exec:{suffix}:",
        notif_prefix=f"sse:notif:{suffix}:",
    )

    execution_id = f"e-{uuid4().hex[:8]}"
    ev = SSEExecutionEventData(
        event_type=EventType.EXECUTION_REQUESTED,
        execution_id=execution_id,
    )

    # Start generator (subscription happens on first __anext__) and publish concurrently.
    # By the time publish fires (~1 Redis RTT), the subscribe is already established.
    messages = bus.listen_execution(execution_id)
    pub_task = asyncio.create_task(bus.publish_event(execution_id, ev))
    msg = await asyncio.wait_for(messages.__anext__(), timeout=2.0)
    await pub_task
    await messages.aclose()

    assert msg is not None
    assert str(msg.event_type) == str(ev.event_type)
