import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis
from app.core.logging import setup_logger
from app.core.providers import (
    BoundaryClientProvider,
    EventProvider,
    LoggingProvider,
    MetricsProvider,
    RedisServicesProvider,
    SettingsProvider,
)
from app.core.tracing import init_tracing
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId
from app.domain.events.typed import DomainEvent
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.sse.event_router import SSE_RELEVANT_EVENTS, SSEEventRouter
from app.services.sse.redis_bus import SSERedisBus
from app.settings import Settings
from dishka import Provider, Scope, make_async_container, provide
from dishka.integrations.faststream import FromDishka, setup_dishka
from faststream import AckPolicy, FastStream
from faststream.kafka import KafkaBroker
from faststream.message import StreamMessage


class SSEBridgeProvider(Provider):
    """Provides SSE bridge specific dependencies."""

    scope = Scope.APP

    @provide
    def get_sse_event_router(
            self,
            sse_redis_bus: SSERedisBus,
            logger: logging.Logger,
    ) -> SSEEventRouter:
        return SSEEventRouter(sse_bus=sse_redis_bus, logger=logger)

    @provide
    def get_sse_redis_bus(
            self,
            redis_client: redis.Redis,
            logger: logging.Logger,
    ) -> SSERedisBus:
        return SSERedisBus(redis_client, logger)


def main() -> None:
    """Entry point for SSE bridge worker."""
    settings = Settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logger.info("Starting SSE Bridge (FastStream)...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name="sse-bridge",
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )

    # DI container - no database needed, just Redis and Kafka
    container = make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BoundaryClientProvider(),
        RedisServicesProvider(),
        MetricsProvider(),
        EventProvider(),
        SSEBridgeProvider(),
        context={Settings: settings},
    )

    # Topics from config
    topics = [
        f"{settings.KAFKA_TOPIC_PREFIX}{t}"
        for t in CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.WEBSOCKET_GATEWAY]
    ]
    group_id = f"{GroupId.WEBSOCKET_GATEWAY}.{settings.KAFKA_GROUP_SUFFIX}"

    broker = KafkaBroker(
        settings.KAFKA_BOOTSTRAP_SERVERS,
        request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
    )

    @asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        app_logger = await container.get(logging.Logger)
        app_logger.info("SSE Bridge starting...")

        # Resolve schema registry (initialization handled by provider)
        schema_registry = await container.get(SchemaRegistryManager)

        # Decoder: Avro message → typed DomainEvent
        async def decode_avro(msg: StreamMessage[Any]) -> DomainEvent:
            return await schema_registry.deserialize_event(msg.body, "sse_bridge")

        # Single handler for all SSE-relevant events
        # No filter needed - we check event_type in handler since route_event handles all types
        @broker.subscriber(
            *topics,
            group_id=group_id,
            ack_policy=AckPolicy.ACK_FIRST,  # SSE bridge is idempotent (Redis pubsub)
            decoder=decode_avro,
        )
        async def handle_sse_event(
            event: DomainEvent,
            router: FromDishka[SSEEventRouter],
        ) -> None:
            """Route domain events to Redis for SSE delivery."""
            if event.event_type in SSE_RELEVANT_EVENTS:
                await router.route_event(event)

        app_logger.info(f"Subscribing to topics: {topics}")
        app_logger.info("SSE Bridge ready")

        try:
            yield
        finally:
            app_logger.info("SSE Bridge shutting down...")
            await container.close()

    app = FastStream(broker, lifespan=lifespan)
    setup_dishka(container=container, app=app, auto_inject=True)

    asyncio.run(app.run())


if __name__ == "__main__":
    main()
