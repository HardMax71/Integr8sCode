"""
DLQ Processor Worker using FastStream.

Processes Dead Letter Queue messages with:
- FastStream subscriber for message consumption (push-based, not polling)
- Timer task in lifespan for scheduled retries
- Dishka DI for dependencies
"""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from app.core.logging import setup_logger
from app.core.providers import (
    BoundaryClientProvider,
    CoreServicesProvider,
    EventProvider,
    LoggingProvider,
    MessagingProvider,
    MetricsProvider,
    RedisServicesProvider,
    RepositoryProvider,
    SettingsProvider,
)
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.dlq import DLQMessage, RetryPolicy, RetryStrategy
from app.dlq.manager import DLQManager
from app.domain.enums.kafka import CONSUMER_GROUP_SUBSCRIPTIONS, GroupId
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.settings import Settings
from beanie import init_beanie
from dishka import make_async_container
from dishka.integrations.faststream import FromDishka, setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from faststream.message import StreamMessage
from pymongo.asynchronous.mongo_client import AsyncMongoClient


def _configure_retry_policies(manager: DLQManager, logger: logging.Logger) -> None:
    """Configure topic-specific retry policies."""
    manager.set_retry_policy(
        "execution-requests",
        RetryPolicy(
            topic="execution-requests",
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=5,
            base_delay_seconds=30,
            max_delay_seconds=300,
            retry_multiplier=2.0,
        ),
    )
    manager.set_retry_policy(
        "pod-events",
        RetryPolicy(
            topic="pod-events",
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=3,
            base_delay_seconds=60,
            max_delay_seconds=600,
            retry_multiplier=3.0,
        ),
    )
    manager.set_retry_policy(
        "resource-allocation",
        RetryPolicy(topic="resource-allocation", strategy=RetryStrategy.IMMEDIATE, max_retries=3),
    )
    manager.set_retry_policy(
        "websocket-events",
        RetryPolicy(
            topic="websocket-events", strategy=RetryStrategy.FIXED_INTERVAL, max_retries=10, base_delay_seconds=10
        ),
    )
    manager.default_retry_policy = RetryPolicy(
        topic="default",
        strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
        max_retries=4,
        base_delay_seconds=60,
        max_delay_seconds=1800,
        retry_multiplier=2.5,
    )


def _configure_filters(manager: DLQManager, testing: bool, logger: logging.Logger) -> None:
    """Configure message filters."""
    if not testing:

        def filter_test_events(message: DLQMessage) -> bool:
            event_id = message.event.event_id or ""
            return not event_id.startswith("test-")

        manager.add_filter(filter_test_events)

    def filter_old_messages(message: DLQMessage) -> bool:
        max_age_days = 7
        age_seconds = (datetime.now(timezone.utc) - message.failed_at).total_seconds()
        return age_seconds < (max_age_days * 24 * 3600)

    manager.add_filter(filter_old_messages)


def main() -> None:
    """Entry point for DLQ processor worker.

    FastStream handles:
    - Signal handling (SIGINT/SIGTERM)
    - Consumer loop
    - Graceful shutdown
    """
    settings = Settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logger.info("Starting DLQ Processor (FastStream)...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.DLQ_PROCESSOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )

    # Create DI container
    container = make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        CoreServicesProvider(),
        BoundaryClientProvider(),
        RedisServicesProvider(),
        MetricsProvider(),
        EventProvider(),
        MessagingProvider(),
        RepositoryProvider(),
        context={Settings: settings},
    )

    # Build topic and group ID from config
    topics = [f"{settings.KAFKA_TOPIC_PREFIX}{t}" for t in CONSUMER_GROUP_SUBSCRIPTIONS[GroupId.DLQ_PROCESSOR]]
    group_id = f"{GroupId.DLQ_PROCESSOR}.{settings.KAFKA_GROUP_SUFFIX}"

    broker = KafkaBroker(
        settings.KAFKA_BOOTSTRAP_SERVERS,
        request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
    )

    @asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        """Initialize infrastructure and start scheduled retry timer."""
        app_logger = await container.get(logging.Logger)
        app_logger.info("DLQ Processor starting...")

        # Initialize MongoDB + Beanie
        mongo_client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
            settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
        )
        await init_beanie(database=mongo_client[settings.DATABASE_NAME], document_models=ALL_DOCUMENTS)

        # Resolve schema registry (initialization handled by provider)
        await container.get(SchemaRegistryManager)

        # Resolve Kafka producer (lifecycle managed by DI - BoundaryClientProvider starts it)
        await container.get(UnifiedProducer)
        app_logger.info("Kafka producer ready")

        # Get DLQ manager and configure policies
        manager = await container.get(DLQManager)
        _configure_retry_policies(manager, app_logger)
        _configure_filters(manager, testing=settings.TESTING, logger=app_logger)
        app_logger.info("DLQ Manager configured")

        # Decoder: JSON message → typed DLQMessage
        def decode_dlq_json(msg: StreamMessage[Any]) -> DLQMessage:
            data = json.loads(msg.body)
            return DLQMessage.model_validate(data)

        # Register subscriber for DLQ messages
        @broker.subscriber(
            *topics,
            group_id=group_id,
            auto_commit=False,
            decoder=decode_dlq_json,
        )
        async def handle_dlq_message(
            message: DLQMessage,
            dlq_manager: FromDishka[DLQManager],
        ) -> None:
            """Handle incoming DLQ messages - invoked by FastStream when message arrives."""
            await dlq_manager.process_message(message)

        # Background task: periodic check for scheduled retries
        async def retry_checker() -> None:
            while True:
                try:
                    await asyncio.sleep(10)
                    await manager.check_scheduled_retries()
                except asyncio.CancelledError:
                    break
                except Exception:
                    app_logger.exception("Error checking scheduled retries")

        retry_task = asyncio.create_task(retry_checker())
        app_logger.info("DLQ Processor ready, starting event processing...")

        try:
            yield
        finally:
            app_logger.info("DLQ Processor shutting down...")
            retry_task.cancel()
            try:
                await retry_task
            except asyncio.CancelledError:
                pass
            await mongo_client.close()
            await container.close()
            app_logger.info("DLQ Processor shutdown complete")

    app = FastStream(broker, lifespan=lifespan)
    setup_dishka(container=container, app=app, auto_inject=True)

    asyncio.run(app.run())


if __name__ == "__main__":
    main()
