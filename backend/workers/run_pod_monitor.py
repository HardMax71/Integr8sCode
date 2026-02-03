import asyncio
import logging

from app.core.container import create_pod_monitor_container
from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.events.broker import create_broker
from app.events.schema.schema_registry import SchemaRegistryManager
from app.services.pod_monitor.monitor import PodMonitor
from app.settings import Settings
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream


def main() -> None:
    """Main entry point for pod monitor worker"""
    settings = Settings(override_path="config.pod-monitor.toml")

    logger = setup_logger(settings.LOG_LEVEL)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

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

    # Create Kafka broker (PodMonitor publishes events via KafkaEventService)
    schema_registry = SchemaRegistryManager(settings, logger)
    broker = create_broker(settings, schema_registry, logger)

    # Create DI container with broker in context
    container = create_pod_monitor_container(settings, broker)
    setup_dishka(container, broker=broker, auto_inject=True)

    app = FastStream(broker)

    @app.on_startup
    async def startup() -> None:
        # Resolving PodMonitor triggers Database init (via dependency),
        # starts the K8s watch loop, and starts the reconciliation scheduler
        await container.get(PodMonitor)
        logger.info("PodMonitor infrastructure initialized")

    @app.on_shutdown
    async def shutdown() -> None:
        await container.close()
        logger.info("PodMonitor shutdown complete")

    asyncio.run(app.run())


if __name__ == "__main__":
    main()
