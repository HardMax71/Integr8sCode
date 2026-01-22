"""
Pod Monitor Worker.

Unlike other workers, PodMonitor watches Kubernetes pods directly
(not consuming Kafka messages), so FastStream's subscriber pattern doesn't apply.
"""

import asyncio
import logging
import signal

from app.core.logging import setup_logger
from app.core.providers import (
    BoundaryClientProvider,
    CoreServicesProvider,
    EventProvider,
    KafkaServicesProvider,
    LoggingProvider,
    MessagingProvider,
    MetricsProvider,
    PodMonitorProvider,
    RedisServicesProvider,
    RepositoryProvider,
    SettingsProvider,
)
from app.core.tracing import init_tracing
from app.db.docs import ALL_DOCUMENTS
from app.domain.enums.kafka import GroupId
from app.events.core import UnifiedProducer
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.pod_monitor.monitor import PodMonitor
from app.settings import Settings
from beanie import init_beanie
from dishka import make_async_container
from pymongo.asynchronous.mongo_client import AsyncMongoClient


async def run_pod_monitor(settings: Settings) -> None:
    """Run the pod monitor service."""
    container = make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        CoreServicesProvider(),
        BoundaryClientProvider(),
        RedisServicesProvider(),
        MetricsProvider(),
        EventProvider(),
        MessagingProvider(),
        KafkaServicesProvider(),
        RepositoryProvider(),
        PodMonitorProvider(),
        context={Settings: settings},
    )

    logger = await container.get(logging.Logger)
    logger.info("Starting PodMonitor with DI container...")

    mongo_client: AsyncMongoClient[dict[str, object]] = AsyncMongoClient(
        settings.MONGODB_URL, tz_aware=True, serverSelectionTimeoutMS=5000
    )
    await init_beanie(database=mongo_client[settings.DATABASE_NAME], document_models=ALL_DOCUMENTS)

    await container.get(SchemaRegistryManager)
    await container.get(UnifiedProducer)
    logger.info("Kafka producer ready")

    monitor = await container.get(PodMonitor)

    # Signal cancels current task - monitor.run() handles CancelledError gracefully
    task = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)  # type: ignore[union-attr]

    logger.info("PodMonitor initialized, starting run...")

    try:
        await monitor.run()
    finally:
        logger.info("Initiating graceful shutdown...")
        await mongo_client.close()
        await container.close()
        logger.info("PodMonitor shutdown complete")


def main() -> None:
    """Main entry point for pod monitor worker."""
    settings = Settings()

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

    asyncio.run(run_pod_monitor(settings))


if __name__ == "__main__":
    main()
