import asyncio

from app.core.container import create_result_processor_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.events.handlers import register_result_processor_subscriber
from app.services.idempotency import IdempotencyMiddleware
from app.settings import Settings
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

    broker = KafkaBroker(settings.KAFKA_BOOTSTRAP_SERVERS, logger=logger)
    register_result_processor_subscriber(broker, settings)

    container = create_result_processor_container(settings, broker)
    setup_dishka(container, broker=broker, auto_inject=True)

    app = FastStream(broker)

    @app.on_startup
    async def startup() -> None:
        await container.get(Database)
        middleware = await container.get(IdempotencyMiddleware)
        broker.add_middleware(middleware)
        logger.info("ResultProcessor infrastructure initialized")

    @app.on_shutdown
    async def shutdown() -> None:
        await container.close()
        logger.info("ResultProcessor shutdown complete")

    async def run() -> None:
        await app.run()

    asyncio.run(run())


if __name__ == "__main__":
    main()
