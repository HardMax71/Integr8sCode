import asyncio
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from beanie import init_beanie
from dishka_faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from kubernetes_asyncio.client.rest import ApiException
from pymongo import AsyncMongoClient

from app.core.container import create_worker_container
from app.core.logging import setup_log_exporter, setup_logger
from app.core.metrics import KubernetesMetrics
from app.core.middlewares import setup_metrics
from app.db.docs import ALL_DOCUMENTS
from app.dlq.manager import DLQManager
from app.events.handlers import k8s_worker_router, result_processor_router, saga_router
from app.services.k8s_worker import KubernetesWorker
from app.services.pod_monitor import ErrorType, PodMonitor
from app.services.saga import SagaOrchestrator
from app.settings import Settings


def main() -> None:
    """Run everything outside the API: the Kafka consumers, the pod watch and the scheduled jobs."""
    settings = Settings(override_path="config.worker.toml")

    logger = setup_logger(settings.LOG_LEVEL)
    setup_log_exporter(settings, logger)
    setup_metrics(settings, logger)

    logger.info("Starting worker...")

    async def run() -> None:
        # Initialize Beanie with tz_aware client (so MongoDB returns aware datetimes)
        client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
        await init_beanie(
            database=client.get_default_database(default=settings.MONGO_DB),
            document_models=ALL_DOCUMENTS,
        )
        logger.info("MongoDB initialized via Beanie")

        container = create_worker_container(settings)
        broker: KafkaBroker = await container.get(KafkaBroker)

        # Include the subscribers, then set up DI integration
        broker.include_routers(k8s_worker_router(), result_processor_router(), saga_router())
        setup_dishka(container, broker=broker, auto_inject=True)

        scheduler = AsyncIOScheduler()

        async def start() -> None:
            k8s_worker = await container.get(KubernetesWorker)
            await k8s_worker.ensure_namespace_security()
            await k8s_worker.ensure_image_pre_puller_daemonset()

            monitor = await container.get(PodMonitor)
            kubernetes_metrics = await container.get(KubernetesMetrics)

            async def watch_pods() -> None:
                error_type: ErrorType | None = None
                try:
                    await monitor.watch_pod_events()
                except ApiException as e:
                    if e.status == 410:
                        logger.warning("Resource version expired, resetting watch cursor")
                        monitor._last_resource_version = None
                        error_type = ErrorType.RESOURCE_VERSION_EXPIRED
                    else:
                        logger.error("API error in watch", status=e.status, reason=e.reason)
                        error_type = ErrorType.API_ERROR
                except Exception:
                    logger.error("Unexpected error in watch", exc_info=True)
                    error_type = ErrorType.UNEXPECTED

                if error_type is not None:
                    kubernetes_metrics.record_pod_monitor_watch_error(error_type)
                    kubernetes_metrics.increment_pod_monitor_watch_reconnects()

            orchestrator = await container.get(SagaOrchestrator)
            dlq_manager = await container.get(DLQManager)

            jobs = (
                ("pod_monitor_watch", watch_pods, 5, 60),
                ("saga_try_schedule", orchestrator.try_schedule_from_queue, 10, 30),
                ("saga_check_timeouts", orchestrator.check_timeouts, 30, 60),
                ("dlq_monitor_retries", dlq_manager.process_monitoring_cycle, 10, 60),
            )
            for job_id, job, seconds, grace in jobs:
                scheduler.add_job(
                    job, trigger="interval", seconds=seconds, id=job_id, max_instances=1, misfire_grace_time=grace
                )
            scheduler.start()
            logger.info("Worker started", jobs=[job_id for job_id, *_ in jobs])

        async def stop_scheduler() -> None:
            scheduler.shutdown(wait=False)

        app = FastStream(
            broker,
            on_startup=[start],
            on_shutdown=[stop_scheduler],
            after_shutdown=[container.close],
        )
        await app.run()
        logger.info("Worker shutdown complete")

    asyncio.run(run())


if __name__ == "__main__":
    main()
