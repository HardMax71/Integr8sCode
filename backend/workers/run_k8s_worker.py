import asyncio
from typing import Any

from app.core.container import create_k8s_worker_container
from app.core.logging import setup_log_exporter, setup_logger
from app.db.docs import ALL_DOCUMENTS
from app.events.handlers import register_k8s_worker_subscriber
from app.services.k8s_worker import KubernetesWorker
from app.settings import Settings
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from pymongo import AsyncMongoClient


def main() -> None:
    """Main entry point for Kubernetes worker"""
    settings = Settings(override_path="config.k8s-worker.toml")

    logger = setup_logger(settings.LOG_LEVEL)
    setup_log_exporter(settings, logger)

    logger.info("Starting KubernetesWorker...")

    async def run() -> None:
        # Initialize Beanie with tz_aware client (so MongoDB returns aware datetimes)
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
        await init_beanie(
            database=client.get_default_database(default=settings.DATABASE_NAME),
            document_models=ALL_DOCUMENTS,
        )
        logger.info("MongoDB initialized via Beanie")

        # Create DI container
        container = create_k8s_worker_container(settings)

        # Get broker from DI
        broker: KafkaBroker = await container.get(KafkaBroker)

        # Register subscriber and set up DI integration
        register_k8s_worker_subscriber(broker)
        setup_dishka(container, broker=broker, auto_inject=True)

        async def init_k8s_worker() -> None:
            worker = await container.get(KubernetesWorker)
            await worker.ensure_image_pre_puller_daemonset()
            logger.info("KubernetesWorker initialized with pre-puller daemonset")

        app = FastStream(broker, on_startup=[init_k8s_worker], on_shutdown=[container.close])
        await app.run()
        logger.info("KubernetesWorker shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
