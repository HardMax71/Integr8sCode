import asyncio
import logging
import signal
from contextlib import AsyncExitStack
from datetime import datetime, timezone

from app.core.container import create_dlq_processor_container
from app.core.database_context import Database
from app.db.docs import ALL_DOCUMENTS
from app.dlq import DLQMessage, RetryPolicy, RetryStrategy
from app.dlq.manager import DLQManager
from app.settings import Settings
from beanie import init_beanie


def _configure_retry_policies(manager: DLQManager, logger: logging.Logger) -> None:
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


async def main(settings: Settings) -> None:
    """Run the DLQ processor.

    DLQ lifecycle events (received, retried, discarded) are emitted to the
    dlq_events Kafka topic for external observability. Logging is handled
    internally by the DLQ manager.
    """
    container = create_dlq_processor_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting DLQ Processor with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    manager = await container.get(DLQManager)

    _configure_retry_policies(manager, logger)
    _configure_filters(manager, testing=settings.TESTING, logger=logger)

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        logger.info("Received signal, initiating shutdown...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    async with AsyncExitStack() as stack:
        stack.push_async_callback(container.close)
        await stop_event.wait()


if __name__ == "__main__":
    asyncio.run(main(Settings(override_path="config.dlq-processor.toml")))
