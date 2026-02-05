import asyncio

from app.core.container import create_dlq_processor_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.dlq.manager import DLQManager
from app.domain.enums.kafka import GroupId
from app.events.handlers import register_dlq_subscriber
from app.settings import Settings
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker


def main() -> None:
    """Main entry point for DLQ processor worker."""
    settings = Settings(override_path="config.dlq-processor.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting DLQ Processor worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.DLQ_MANAGER,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for DLQ Processor")

    # Create Kafka broker and register DLQ subscriber
    broker = KafkaBroker(settings.KAFKA_BOOTSTRAP_SERVERS, logger=logger)
    register_dlq_subscriber(broker, settings)

    # Create DI container with broker in context
    container = create_dlq_processor_container(settings, broker)
    setup_dishka(container, broker=broker, auto_inject=True)

    app = FastStream(broker)

    @app.on_startup
    async def startup() -> None:
        # Resolving DLQManager triggers Database init (via dependency),
        # configures retry policies/filters, and starts APScheduler retry monitor
        await container.get(DLQManager)
        logger.info("DLQ Processor infrastructure initialized")

    @app.on_shutdown
    async def shutdown() -> None:
        await container.close()
        logger.info("DLQ Processor shutdown complete")

    async def run() -> None:
        await app.run()

    asyncio.run(run())


if __name__ == "__main__":
    main()
