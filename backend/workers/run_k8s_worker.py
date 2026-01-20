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
from app.services.k8s_worker.worker_logic import K8sWorkerLogic
from app.settings import Settings
from beanie import init_beanie


async def run_kubernetes_worker(settings: Settings) -> None:
    """Run the Kubernetes worker service."""

    container = create_k8s_worker_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting KubernetesWorker with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    consumer = await container.get(IdempotentConsumerWrapper)
    logic = await container.get(K8sWorkerLogic)

    # Shutdown event - signal handlers just set this
    shutdown_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown_event.set)

    logger.info("KubernetesWorker initialized, starting run...")

    async def run_worker_tasks() -> None:
        """Run consumer and daemonset setup using TaskGroup."""
        async with asyncio.TaskGroup() as tg:
            tg.create_task(consumer.run())
            tg.create_task(logic.ensure_daemonset_task())

    try:
        # Run worker until shutdown signal
        run_task = asyncio.create_task(run_worker_tasks())
        shutdown_task = asyncio.create_task(shutdown_event.wait())

        done, pending = await asyncio.wait(
            [run_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel remaining tasks
        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    finally:
        logger.info("Initiating graceful shutdown...")
        # Wait for active pod creations to complete
        await logic.wait_for_active_creations()
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
