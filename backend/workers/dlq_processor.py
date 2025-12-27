import asyncio
import signal
from typing import Optional

from app.core.database_context import Database, DBClient
from app.core.logging import logger
from app.dlq import DLQMessage, RetryPolicy, RetryStrategy
from app.dlq.manager import DLQManager, create_dlq_manager
from app.domain.enums.kafka import KafkaTopic
from app.settings import get_settings
from pymongo.asynchronous.mongo_client import AsyncMongoClient


def _configure_retry_policies(manager: DLQManager) -> None:
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


def _configure_filters(manager: DLQManager, testing: bool) -> None:
    if not testing:

        def filter_test_events(message: DLQMessage) -> bool:
            event_id = message.event.event_id or ""
            return not event_id.startswith("test-")

        manager.add_filter(filter_test_events)

    def filter_old_messages(message: DLQMessage) -> bool:
        max_age_days = 7
        return message.age_seconds < (max_age_days * 24 * 3600)

    manager.add_filter(filter_old_messages)


def _configure_callbacks(manager: DLQManager, testing: bool) -> None:
    async def log_before_retry(message: DLQMessage) -> None:
        logger.info(
            f"Retrying message {message.event_id} (type: {message.event_type}, "
            f"topic: {message.original_topic}, retry: {message.retry_count + 1})"
        )

    manager.add_callback("before_retry", log_before_retry)

    async def log_after_retry(message: DLQMessage, success: bool, error: Optional[Exception] = None) -> None:
        if success:
            logger.info(f"Successfully retried message {message.event_id} to topic {message.original_topic}")
        else:
            logger.error(f"Failed to retry message {message.event_id}: {error}")

    manager.add_callback("after_retry", log_after_retry)

    async def alert_on_discard(message: DLQMessage, reason: str) -> None:
        logger.warning(
            f"Message {message.event_id} discarded! Type: {message.event_type}, Topic: {message.original_topic}, "
            f"Reason: {reason}, Original error: {message.error}"
        )
        if not testing:
            pass

    manager.add_callback("on_discard", alert_on_discard)


async def main() -> None:
    settings = get_settings()
    db_client: DBClient = AsyncMongoClient(
        settings.MONGODB_URL,
        tz_aware=True,
        serverSelectionTimeoutMS=5000,
    )
    db_name = settings.DATABASE_NAME
    database: Database = db_client[db_name]
    await db_client.admin.command("ping")
    logger.info(f"Connected to database: {db_name}")

    manager = create_dlq_manager(
        database=database,
        dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE,
        retry_topic_suffix="-retry",
    )

    _configure_retry_policies(manager)
    _configure_filters(manager, testing=settings.TESTING)
    _configure_callbacks(manager, testing=settings.TESTING)

    stop_event = asyncio.Event()

    def signal_handler(signum: int, frame: object | None) -> None:
        logger.info(f"Received signal {signum}, initiating shutdown...")
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    from contextlib import AsyncExitStack

    async with AsyncExitStack() as stack:
        await stack.enter_async_context(manager)
        stack.callback(db_client.close)
        await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main())
