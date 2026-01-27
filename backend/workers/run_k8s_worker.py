import asyncio
import logging
import signal

from app.core.container import create_k8s_worker_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.services.k8s_worker.worker import KubernetesWorker
from app.settings import Settings
from beanie import init_beanie


async def run_kubernetes_worker(settings: Settings) -> None:
    """Run the Kubernetes worker service."""

    container = create_k8s_worker_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting KubernetesWorker with DI container...")

    # Bootstrap database
    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    # Initialize schemas
    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Get worker (triggers dispatcher creation and handler registration)
    worker = await container.get(KubernetesWorker)

    # Get consumer (triggers consumer creation and start)
    # Consumer runs in background via its internal consume loop
    await container.get(IdempotentConsumerWrapper)

    # Bootstrap: ensure image pre-puller DaemonSet exists
    asyncio.create_task(worker.ensure_image_pre_puller_daemonset())
    logger.info("Image pre-puller daemonset task scheduled")

    # Shutdown event
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info("KubernetesWorker started and running")

    try:
        # Wait for shutdown signal
        await shutdown_event.wait()
    finally:
        logger.info("Initiating graceful shutdown...")
        await container.close()


def main() -> None:
    """Main entry point for Kubernetes worker"""
    settings = Settings()

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

    asyncio.run(run_kubernetes_worker(settings))


if __name__ == "__main__":
    main()
