import asyncio
import logging

from app.core.container import create_saga_orchestrator_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.broker import create_broker
from app.events.handlers import register_saga_subscriber
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.saga import SagaOrchestrator
from app.settings import Settings
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    settings = Settings(override_path="config.saga-orchestrator.toml")

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting Saga Orchestrator worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.SAGA_ORCHESTRATOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for Saga Orchestrator Service")

    # Create Kafka broker and register subscriber
    schema_registry = SchemaRegistryManager(settings, logger)
    broker = create_broker(settings, schema_registry, logger)
    register_saga_subscriber(broker, settings)

    # Create DI container with broker in context
    container = create_saga_orchestrator_container(settings, broker)
    setup_dishka(container, broker=broker, auto_inject=True)

    _timeout_task: asyncio.Task[None] | None = None

    app = FastStream(broker)

    @app.on_startup
    async def startup() -> None:
        db = await container.get(Database)
        await init_beanie(database=db, document_models=ALL_DOCUMENTS)
        await initialize_event_schemas(schema_registry)
        logger.info("SagaOrchestrator infrastructure initialized")

    @app.after_startup
    async def start_timeout_checker() -> None:
        nonlocal _timeout_task
        orchestrator = await container.get(SagaOrchestrator)

        async def timeout_loop() -> None:
            while True:
                await asyncio.sleep(30)
                try:
                    await orchestrator.check_timeouts()
                except Exception as exc:
                    logger.error(f"Error checking saga timeouts: {exc}")

        _timeout_task = asyncio.create_task(timeout_loop())
        logger.info("Saga orchestrator timeout checker started")

    @app.on_shutdown
    async def shutdown() -> None:
        if _timeout_task:
            _timeout_task.cancel()
        await container.close()
        logger.info("SagaOrchestrator shutdown complete")

    asyncio.run(app.run())


if __name__ == "__main__":
    main()
