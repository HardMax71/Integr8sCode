import asyncio
import logging
import signal
from contextlib import AsyncExitStack
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from app.core.container import create_dlq_processor_container
from app.core.database_context import Database
from app.core.tracing import EventAttributes
from app.core.tracing.utils import extract_trace_context, get_tracer
from app.db.docs import ALL_DOCUMENTS
from app.dlq import DLQMessage, RetryPolicy, RetryStrategy
from app.dlq.manager import DLQManager
from app.domain.enums.kafka import GroupId, KafkaTopic
from app.settings import Settings
from beanie import init_beanie
from opentelemetry.trace import SpanKind


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


async def _consume_messages(
    consumer: AIOKafkaConsumer,
    manager: DLQManager,
    stop_event: asyncio.Event,
    logger: logging.Logger,
) -> None:
    """Consume DLQ messages and dispatch each to the stateless handler."""
    async for msg in consumer:
        if stop_event.is_set():
            break
        try:
            start = asyncio.get_running_loop().time()
            dlq_msg = manager.parse_kafka_message(msg)

            manager.metrics.record_dlq_message_received(dlq_msg.original_topic, dlq_msg.event.event_type)
            manager.metrics.record_dlq_message_age(
                (datetime.now(timezone.utc) - dlq_msg.failed_at).total_seconds()
            )

            ctx = extract_trace_context(dlq_msg.headers)
            with get_tracer().start_as_current_span(
                name="dlq.consume",
                context=ctx,
                kind=SpanKind.CONSUMER,
                attributes={
                    EventAttributes.KAFKA_TOPIC: manager.dlq_topic,
                    EventAttributes.EVENT_TYPE: dlq_msg.event.event_type,
                    EventAttributes.EVENT_ID: dlq_msg.event.event_id,
                },
            ):
                await manager.handle_message(dlq_msg)

            await consumer.commit()
            manager.metrics.record_dlq_processing_duration(asyncio.get_running_loop().time() - start, "process")
        except Exception as e:
            logger.error(f"Error processing DLQ message: {e}")


async def _monitor_retries(
    manager: DLQManager,
    stop_event: asyncio.Event,
    logger: logging.Logger,
) -> None:
    """Periodically process due retries and update queue metrics."""
    while not stop_event.is_set():
        try:
            await manager.process_due_retries()
            await manager.update_queue_metrics()
            interval = 10
        except Exception as e:
            logger.error(f"Error in DLQ monitor: {e}")
            interval = 60
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
            break  # stop_event was set
        except asyncio.TimeoutError:
            continue


async def main(settings: Settings) -> None:
    """Run the DLQ processor.

    DLQ lifecycle events (received, retried, discarded) are emitted to the
    dlq_events Kafka topic for external observability. Logging is handled
    internally by the DLQ manager.
    """
    container = create_dlq_processor_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting DLQ Processor...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    manager = await container.get(DLQManager)

    _configure_retry_policies(manager, logger)
    _configure_filters(manager, testing=settings.TESTING, logger=logger)

    topic_name = f"{settings.KAFKA_TOPIC_PREFIX}{KafkaTopic.DEAD_LETTER_QUEUE}"
    consumer = AIOKafkaConsumer(
        topic_name,
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=GroupId.DLQ_MANAGER,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
        client_id="dlq-manager-consumer",
        session_timeout_ms=settings.KAFKA_SESSION_TIMEOUT_MS,
        heartbeat_interval_ms=settings.KAFKA_HEARTBEAT_INTERVAL_MS,
        max_poll_interval_ms=settings.KAFKA_MAX_POLL_INTERVAL_MS,
        request_timeout_ms=settings.KAFKA_REQUEST_TIMEOUT_MS,
    )

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def signal_handler() -> None:
        logger.info("Received signal, initiating shutdown...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    async with AsyncExitStack() as stack:
        stack.push_async_callback(container.close)
        await consumer.start()
        stack.push_async_callback(consumer.stop)

        consume_task = asyncio.create_task(_consume_messages(consumer, manager, stop_event, logger))
        monitor_task = asyncio.create_task(_monitor_retries(manager, stop_event, logger))

        logger.info("DLQ Processor running")
        await stop_event.wait()

        consume_task.cancel()
        monitor_task.cancel()
        await asyncio.gather(consume_task, monitor_task, return_exceptions=True)
        logger.info("DLQ Processor stopped")


if __name__ == "__main__":
    asyncio.run(main(Settings(override_path="config.dlq-processor.toml")))
