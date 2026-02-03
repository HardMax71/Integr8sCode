import asyncio
import logging

from app.core.container import create_k8s_worker_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.broker import create_broker
from app.events.handlers import register_k8s_worker_subscriber
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.k8s_worker import KubernetesWorker
from app.settings import Settings
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream


def main() -> None:
    """Main entry point for Kubernetes worker"""
    settings = Settings(override_path="config.k8s-worker.toml")

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting KubernetesWorker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.K8S_WORKER,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for KubernetesWorker")

    # Create Kafka broker and register subscriber
    schema_registry = SchemaRegistryManager(settings, logger)
    broker = create_broker(settings, schema_registry, logger)
    register_k8s_worker_subscriber(broker, settings)

    # Create DI container with broker in context
    container = create_k8s_worker_container(settings, broker)
    setup_dishka(container, broker=broker, auto_inject=True)

    app = FastStream(broker)

    @app.on_startup
    async def startup() -> None:
        db = await container.get(Database)
        await init_beanie(database=db, document_models=ALL_DOCUMENTS)
        await initialize_event_schemas(schema_registry)
        logger.info("KubernetesWorker infrastructure initialized")

    @app.after_startup
    async def bootstrap() -> None:
        worker = await container.get(KubernetesWorker)
        asyncio.create_task(worker.ensure_image_pre_puller_daemonset())
        logger.info("Image pre-puller daemonset task scheduled")

    @app.on_shutdown
    async def shutdown() -> None:
        await container.close()
        logger.info("KubernetesWorker shutdown complete")

    asyncio.run(app.run())


if __name__ == "__main__":
    main()
