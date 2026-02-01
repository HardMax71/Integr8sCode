import asyncio
import logging
from uuid import uuid4

import pytest
import redis.asyncio as redis
from app.core.metrics import EventMetrics
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager
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

    disp = EventDispatcher(logger=_test_logger)
    for et in SSERedisBus.SSE_ROUTED_EVENTS:
        disp.register_handler(et, bus.route_domain_event)

    execution_id = f"e-{uuid4().hex[:8]}"
    subscription = await bus.open_subscription(execution_id)

    ev = make_execution_requested_event(execution_id=execution_id)
    handler = disp._handlers[ev.event_type][0]
    await handler(ev)

    msg = await asyncio.wait_for(subscription.get(RedisSSEMessage), timeout=2.0)
    assert msg is not None
    assert str(msg.event_type) == str(ev.event_type)


@pytest.mark.asyncio
@pytest.mark.kafka
async def test_sse_consumer_start_and_stop(
    redis_client: redis.Redis, test_settings: Settings,
) -> None:
    suffix = uuid4().hex[:6]
    bus = SSERedisBus(
        redis_client,
        exec_prefix=f"sse:exec:{suffix}:",
        notif_prefix=f"sse:notif:{suffix}:",
        logger=_test_logger,
    )

    config = ConsumerConfig(
        bootstrap_servers=test_settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id="sse-bridge-pool",
        client_id="sse-consumer-test-0",
        enable_auto_commit=True,
        auto_offset_reset="latest",
        max_poll_interval_ms=test_settings.KAFKA_MAX_POLL_INTERVAL_MS,
        session_timeout_ms=test_settings.KAFKA_SESSION_TIMEOUT_MS,
        heartbeat_interval_ms=test_settings.KAFKA_HEARTBEAT_INTERVAL_MS,
        request_timeout_ms=test_settings.KAFKA_REQUEST_TIMEOUT_MS,
    )
    dispatcher = EventDispatcher(logger=_test_logger)
    for et in SSERedisBus.SSE_ROUTED_EVENTS:
        dispatcher.register_handler(et, bus.route_domain_event)

    consumer = UnifiedConsumer(
        config=config,
        event_dispatcher=dispatcher,
        schema_registry=SchemaRegistryManager(settings=test_settings, logger=_test_logger),
        settings=test_settings,
        logger=_test_logger,
        event_metrics=EventMetrics(test_settings),
    )
    topics = list(CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.WEBSOCKET_GATEWAY])
    await consumer.start(topics)
    await consumer.stop()
