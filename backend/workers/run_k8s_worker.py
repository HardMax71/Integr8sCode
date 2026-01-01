import asyncio
import logging
import signal
from contextlib import AsyncExitStack
from typing import Any

from app.core.container import create_k8s_worker_container
from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.k8s_worker.worker import KubernetesWorker
from app.settings import Settings, get_settings
from beanie import init_beanie


async def run_kubernetes_worker(settings: Settings | None = None) -> None:
    """Run the Kubernetes worker service."""
    if settings is None:
        settings = get_settings()

    container = create_k8s_worker_container(settings)
    logger = await container.get(logging.Logger)
    logger.info("Starting KubernetesWorker with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    producer = await container.get(UnifiedProducer)
    worker = await container.get(KubernetesWorker)

    def signal_handler(sig: int, frame: Any) -> None:
        logger.info(f"Received signal {sig}, initiating shutdown...")
        asyncio.create_task(worker.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    async with AsyncExitStack() as stack:
        stack.push_async_callback(container.close)
        await stack.enter_async_context(producer)
        await stack.enter_async_context(worker)

        while worker._running:
            await asyncio.sleep(60)
            status = await worker.get_status()
            logger.info(f"Kubernetes worker status: {status}")


def main() -> None:
    """Main entry point for Kubernetes worker"""
    settings = get_settings()

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    logger.info("Starting KubernetesWorker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.K8S_WORKER,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for KubernetesWorker")

    asyncio.run(run_kubernetes_worker(settings))


if __name__ == "__main__":
    main()
