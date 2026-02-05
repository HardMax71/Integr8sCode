import asyncio

from app.core.container import create_coordinator_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.events.handlers import register_coordinator_subscriber
from app.settings import Settings
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker


def main() -> None:
    """Main entry point for coordinator worker"""
    settings = Settings(override_path="config.coordinator.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting ExecutionCoordinator worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.EXECUTION_COORDINATOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for ExecutionCoordinator")

    # Create DI container (broker is created by BrokerProvider)
    container = create_coordinator_container(settings)

    async def run() -> None:
        # Get broker from DI
        broker: KafkaBroker = await container.get(KafkaBroker)

        # Register subscriber and set up DI integration
        register_coordinator_subscriber(broker, settings)
        setup_dishka(container, broker=broker, auto_inject=True)

        app = FastStream(broker)

        @app.on_startup
        async def startup() -> None:
            await container.get(Database)  # triggers init_beanie inside provider
            logger.info("ExecutionCoordinator infrastructure initialized")

        @app.on_shutdown
        async def shutdown() -> None:
            await container.close()
            logger.info("ExecutionCoordinator shutdown complete")

        await app.run()

    asyncio.run(run())


if __name__ == "__main__":
    main()
