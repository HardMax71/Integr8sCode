"""
Pod Monitor Worker (Simplified).

Note: Unlike other workers, PodMonitor watches Kubernetes pods directly
(not consuming Kafka messages), so FastStream's subscriber pattern doesn't apply.

This version uses a minimal signal handling approach.
"""

import asyncio
import logging
import signal
from contextlib import suppress

from app.core.database_context import Database
from app.core.logging import setup_logger
from app.core.providers import (
    BoundaryClientProvider,
    DatabaseProvider,
    EventProvider,
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
from app.events.schema.schema_registry import SchemaRegistryManager, initialize_event_schemas
from app.services.pod_monitor.monitor import PodMonitor
from app.settings import Settings
from beanie import init_beanie
from dishka import make_async_container


async def run_pod_monitor(settings: Settings) -> None:
    """Run the pod monitor service."""
    container = make_async_container(
        SettingsProvider(),
        LoggingProvider(),
        BoundaryClientProvider(),
        RedisServicesProvider(),
        DatabaseProvider(),
        MetricsProvider(),
        EventProvider(),
        MessagingProvider(),
        RepositoryProvider(),
        PodMonitorProvider(),
        context={Settings: settings},
    )

    logger = await container.get(logging.Logger)
    logger.info("Starting PodMonitor with DI container...")

    db = await container.get(Database)
    await init_beanie(database=db, document_models=ALL_DOCUMENTS)

    schema_registry = await container.get(SchemaRegistryManager)
    await initialize_event_schemas(schema_registry)

    # Resolve Kafka producer (lifecycle managed by DI - BoundaryClientProvider starts it)
    await container.get(UnifiedProducer)
    logger.info("Kafka producer ready")

    monitor = await container.get(PodMonitor)

    # Signal handling with minimal boilerplate
    shutdown = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, shutdown.set)

    logger.info("PodMonitor initialized, starting run...")

    try:
        # Run monitor until shutdown
        monitor_task = asyncio.create_task(monitor.run())
        shutdown_task = asyncio.create_task(shutdown.wait())

        done, pending = await asyncio.wait(
            [monitor_task, shutdown_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    finally:
        logger.info("Initiating graceful shutdown...")
        # Container close stops Kafka producer via DI provider
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
