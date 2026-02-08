import asyncio
from typing import Any

from app.core.container import create_pod_monitor_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums import GroupId
from app.services.pod_monitor.monitor import PodMonitor
from app.settings import Settings
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from pymongo import AsyncMongoClient


def main() -> None:
    """Main entry point for pod monitor worker"""
    settings = Settings(override_path="config.pod-monitor.toml")

    logger = setup_logger(settings.LOG_LEVEL)

    logger.info("Starting PodMonitor worker...")

    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.POD_MONITOR,
            settings=settings,
            logger=logger,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE,
        )
        logger.info("Tracing initialized for PodMonitor Service")

    async def run() -> None:
        # Initialize Beanie with tz_aware client (so MongoDB returns aware datetimes)
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
        await init_beanie(
            database=client.get_default_database(default=settings.DATABASE_NAME),
            document_models=ALL_DOCUMENTS,
        )
        logger.info("MongoDB initialized via Beanie")

        # Create DI container
        container = create_pod_monitor_container(settings)

        # Get broker from DI (PodMonitor publishes events via KafkaEventService)
        broker: KafkaBroker = await container.get(KafkaBroker)

        # Set up DI integration (no subscribers for pod monitor - it only publishes)
        setup_dishka(container, broker=broker, auto_inject=True)

        # Resolving PodMonitor starts K8s watch loop and reconciliation scheduler (via provider)
        async def init_monitor() -> None:
            await container.get(PodMonitor)
            logger.info("PodMonitor initialized")

        app = FastStream(broker, on_startup=[init_monitor], on_shutdown=[container.close])
        await app.run()
        logger.info("PodMonitor shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
