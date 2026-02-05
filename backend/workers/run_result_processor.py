import asyncio

from app.core.container import create_result_processor_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.handlers import register_result_processor_subscriber
from app.settings import Settings
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker


def main() -> None:
    """Main entry point for result processor worker"""
    settings = Settings(override_path="config.result-processor.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting ResultProcessor worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.RESULT_PROCESSOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for ResultProcessor Service")

    async def run() -> None:
        # Initialize Beanie with connection string (Beanie manages client internally)
        await init_beanie(connection_string=settings.MONGODB_URL, document_models=ALL_DOCUMENTS)
        logger.info("MongoDB initialized via Beanie")

        # Create DI container
        container = create_result_processor_container(settings)

        # Get broker from DI
        broker: KafkaBroker = await container.get(KafkaBroker)

        # Register subscriber and set up DI integration
        register_result_processor_subscriber(broker, settings)
        setup_dishka(container, broker=broker, auto_inject=True)

        app = FastStream(broker, on_shutdown=[container.close])
        await app.run()
        logger.info("ResultProcessor shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
