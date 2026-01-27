"""Saga orchestrator worker entrypoint - stateless event processing.

Consumes execution events from Kafka and dispatches to SagaOrchestrator handlers.
DI container manages all lifecycle - worker just iterates over consumer.
"""

import asyncio
import logging

from aiokafka import AIOKafkaConsumer
from app.core.container import create_saga_orchestrator_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.core import UnifiedConsumer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.settings import Settings
from beanie import init_beanie


async def run_saga_orchestrator(settings: Settings) -> None:
    """Run the saga orchestrator service."""

    container = create_saga_orchestrator_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting SagaOrchestrator with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    kafka_consumer = await container.get(AIOKafkaConsumer)
    handler = await container.get(UnifiedConsumer)

    logger.info("SagaOrchestrator started, consuming events...")

    async for msg in kafka_consumer:
        await handler.handle(msg)
        await kafka_consumer.commit()

    logger.info("SagaOrchestrator shutdown complete")

    await container.close()


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    settings = Settings()

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

    asyncio.run(run_saga_orchestrator(settings))


if __name__ == "__main__":
    main()
