"""Result processor worker entrypoint - stateless event processing.

Consumes execution completion events from Kafka and dispatches to ResultProcessor handlers.
DI container manages all lifecycle - worker just iterates over consumer.
"""

import asyncio
import logging

from aiokafka import AIOKafkaConsumer
from app.core.container import create_result_processor_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.core import UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.settings import Settings
from beanie import init_beanie


async def run_result_processor(settings: Settings) -> None:
    """Run the result processor service."""

    container = create_result_processor_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting ResultProcessor with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    kafka_consumer = await container.get(AIOKafkaConsumer)
    handler = await container.get(UnifiedConsumer)

    logger.info("ResultProcessor started, consuming events...")

    async for msg in kafka_consumer:
        await handler.handle(msg)
        await kafka_consumer.commit()

    logger.info("ResultProcessor shutdown complete")

    await container.close()


def main() -> None:
    """Main entry point for result processor worker"""
    settings = Settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

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

    asyncio.run(run_result_processor(settings))


if __name__ == "__main__":
    main()
