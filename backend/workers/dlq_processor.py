import asyncio
import signal
import sys
from typing import Any, Optional

from app.core.logging import logger
from app.dlq.manager import DLQManager, DLQMessage, RetryPolicy, RetryStrategy, create_dlq_manager
from app.domain.enums.kafka import KafkaTopic
from app.settings import get_settings
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase


class DLQProcessor:
    """DLQ processor worker"""

    def __init__(self) -> None:
        self.dlq_manager: Optional[DLQManager] = None
        self._shutdown_event = asyncio.Event()
        self.settings = get_settings()
        self.database: Optional[AsyncIOMotorDatabase] = None

    async def start(self) -> None:
        """Start DLQ processor"""
        logger.info("Starting DLQ processor...")

        # Create database connection
        db_client: AsyncIOMotorClient = AsyncIOMotorClient(
            self.settings.MONGODB_URL,
            tz_aware=True,
            serverSelectionTimeoutMS=5000
        )
        db_name = self.settings.PROJECT_NAME + "_test" if self.settings.TESTING else self.settings.PROJECT_NAME
        self.database = db_client[db_name]

        # Verify connection
        await db_client.admin.command("ping")
        logger.info(f"Connected to database: {db_name}")

        # Initialize DLQ manager with database and metrics
        self.dlq_manager = create_dlq_manager(
            database=self.database,
            dlq_topic=KafkaTopic.DEAD_LETTER_QUEUE,
            retry_topic_suffix="-retry"
        )

        # Configure retry policies for different topics
        self._configure_retry_policies()

        # Add custom filters
        self._configure_filters()

        # Add callbacks
        self._configure_callbacks()

        # Start DLQ manager
        await self.dlq_manager.start()

        logger.info("DLQ processor started successfully")

        # Wait for shutdown
        await self._shutdown_event.wait()

    async def stop(self) -> None:
        """Stop DLQ processor"""
        logger.info("Stopping DLQ processor...")

        if self.dlq_manager:
            await self.dlq_manager.stop()

        self._shutdown_event.set()

        logger.info("DLQ processor stopped")

    def _configure_retry_policies(self) -> None:
        """Configure retry policies for different topics"""
        if not self.dlq_manager:
            return

        # Execution requests - aggressive retry
        self.dlq_manager.set_retry_policy(
            "execution-requests",
            RetryPolicy(
                topic="execution-requests",
                strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
                max_retries=5,
                base_delay_seconds=30,
                max_delay_seconds=300,  # 5 minutes max
                retry_multiplier=2.0
            )
        )

        # Pod events - less aggressive
        self.dlq_manager.set_retry_policy(
            "pod-events",
            RetryPolicy(
                topic="pod-events",
                strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
                max_retries=3,
                base_delay_seconds=60,
                max_delay_seconds=600,  # 10 minutes max
                retry_multiplier=3.0
            )
        )

        # Resource allocation - immediate retry with limit
        self.dlq_manager.set_retry_policy(
            "resource-allocation",
            RetryPolicy(
                topic="resource-allocation",
                strategy=RetryStrategy.IMMEDIATE,
                max_retries=3
            )
        )

        # WebSocket events - fixed interval
        self.dlq_manager.set_retry_policy(
            "websocket-events",
            RetryPolicy(
                topic="websocket-events",
                strategy=RetryStrategy.FIXED_INTERVAL,
                max_retries=10,
                base_delay_seconds=10
            )
        )

        # Default policy for other topics
        self.dlq_manager.default_retry_policy = RetryPolicy(
            topic="default",
            strategy=RetryStrategy.EXPONENTIAL_BACKOFF,
            max_retries=4,
            base_delay_seconds=60,
            max_delay_seconds=1800,  # 30 minutes max
            retry_multiplier=2.5
        )

    def _configure_filters(self) -> None:
        """Configure message filters"""
        if not self.dlq_manager:
            return

        # Filter out test events in production
        if not self.settings.TESTING:
            def filter_test_events(message: DLQMessage) -> bool:
                event_id = message.event.event_id or ""
                return not event_id.startswith("test-")

            self.dlq_manager.add_filter(filter_test_events)

        # Filter out old messages (> 7 days)
        def filter_old_messages(message: DLQMessage) -> bool:
            max_age_days = 7
            return message.age_seconds < (max_age_days * 24 * 3600)

        self.dlq_manager.add_filter(filter_old_messages)

    def _configure_callbacks(self) -> None:
        """Configure DLQ callbacks"""
        if not self.dlq_manager:
            return

        # Log before retry
        async def log_before_retry(message: DLQMessage) -> None:
            logger.info(
                f"Retrying message {message.event_id} "
                f"(type: {message.event_type}, "
                f"topic: {message.original_topic}, "
                f"retry: {message.retry_count + 1})"
            )

        self.dlq_manager.add_callback("before_retry", log_before_retry)

        # Log after retry
        async def log_after_retry(message: DLQMessage, success: bool, error: Optional[Exception] = None) -> None:
            if success:
                logger.info(
                    f"Successfully retried message {message.event_id} "
                    f"to topic {message.original_topic}"
                )
            else:
                logger.error(
                    f"Failed to retry message {message.event_id}: {error}"
                )

        self.dlq_manager.add_callback("after_retry", log_after_retry)

        # Alert on discard
        async def alert_on_discard(message: DLQMessage, reason: str) -> None:
            logger.warning(
                f"Message {message.event_id} discarded! "
                f"Type: {message.event_type}, "
                f"Topic: {message.original_topic}, "
                f"Reason: {reason}, "
                f"Original error: {message.error}"
            )

            # In production, this could send alerts to monitoring systems
            if not self.settings.TESTING:
                # Example: Send to alerting system
                pass

        self.dlq_manager.add_callback("on_discard", alert_on_discard)

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful shutdown"""

        def signal_handler(signum: int, frame: Any) -> None:
            logger.info(f"Received signal {signum}, initiating shutdown...")
            asyncio.create_task(self.stop())

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def main() -> None:
    processor = DLQProcessor()
    processor._setup_signal_handlers()

    try:
        await processor.start()
    except Exception as e:
        logger.error(f"DLQ processor failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
