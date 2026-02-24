import asyncio
from typing import Any

from app.core.container import create_pod_monitor_container
from app.core.logging import setup_log_exporter, setup_logger
from app.core.metrics import KubernetesMetrics
from app.db.docs import ALL_DOCUMENTS
from app.services.pod_monitor import ErrorType, PodMonitor
from app.settings import Settings
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from beanie import init_beanie
from dishka.integrations.faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from kubernetes_asyncio.client.rest import ApiException
from pymongo import AsyncMongoClient


def main() -> None:
    """Main entry point for pod monitor worker"""
    settings = Settings(override_path="config.pod-monitor.toml")

    logger = setup_logger(settings.LOG_LEVEL)
    setup_log_exporter(settings, logger)

    logger.info("Starting PodMonitor worker...")

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

        scheduler = AsyncIOScheduler()

        async def init_monitor() -> None:
            monitor = await container.get(PodMonitor)
            kubernetes_metrics = await container.get(KubernetesMetrics)

            async def _watch_cycle() -> None:
                try:
                    await monitor.watch_pod_events()
                except ApiException as e:
                    if e.status == 410:
                        logger.warning("Resource version expired, resetting watch cursor")
                        monitor._last_resource_version = None
                        kubernetes_metrics.record_pod_monitor_watch_error(ErrorType.RESOURCE_VERSION_EXPIRED)
                    else:
                        logger.error(f"API error in watch: {e}")
                        kubernetes_metrics.record_pod_monitor_watch_error(ErrorType.API_ERROR)
                    kubernetes_metrics.increment_pod_monitor_watch_reconnects()
                except Exception as e:
                    logger.error(f"Unexpected error in watch: {e}", exc_info=True)
                    kubernetes_metrics.record_pod_monitor_watch_error(ErrorType.UNEXPECTED)
                    kubernetes_metrics.increment_pod_monitor_watch_reconnects()

            scheduler.add_job(
                _watch_cycle,
                trigger="interval",
                seconds=5,
                id="pod_monitor_watch",
                max_instances=1,
                misfire_grace_time=60,
            )
            scheduler.start()
            logger.info("PodMonitor initialized (APScheduler interval=5s)")

        async def shutdown() -> None:
            scheduler.shutdown(wait=False)
            await container.close()

        app = FastStream(broker, on_startup=[init_monitor], on_shutdown=[shutdown])
        await app.run()
        logger.info("PodMonitor shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
