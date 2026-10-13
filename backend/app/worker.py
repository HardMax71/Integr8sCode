import asyncio
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from beanie import init_beanie
from dishka import AsyncContainer
from dishka_faststream import setup_dishka
from faststream import FastStream
from faststream.kafka import KafkaBroker
from pymongo import AsyncMongoClient

from app.core.container import create_worker_container
from app.core.logging import setup_log_exporter, setup_logger
from app.core.middlewares import setup_metrics
from app.db.docs import ALL_DOCUMENTS
from app.dlq.manager import DLQManager
from app.events.handlers import k8s_worker_router, result_processor_router, saga_router
from app.services.k8s_worker import KubernetesWorker
from app.services.pod_monitor import PodMonitor
from app.services.saga import SagaOrchestrator
from app.settings import Settings


def main() -> None:
    """Run everything outside the API: the Kafka consumers, the pod watch and the scheduled jobs."""
    settings = Settings(override_path="config.worker.toml")
    logger = setup_logger(settings.LOG_LEVEL)
    setup_log_exporter(settings, logger)
    setup_metrics(settings, logger)
    logger.info("Starting worker...")
    asyncio.run(run(settings, logger))


async def run(settings: Settings, logger: structlog.stdlib.BoundLogger) -> None:
    # A tz-aware client, so MongoDB returns aware datetimes
    client: AsyncMongoClient[dict[str, Any]] = AsyncMongoClient(settings.MONGODB_URL, tz_aware=True)
    await init_beanie(database=client.get_default_database(default=settings.MONGO_DB), document_models=ALL_DOCUMENTS)

    container = create_worker_container(settings)
    broker: KafkaBroker = await container.get(KafkaBroker)
    broker.include_routers(k8s_worker_router(), result_processor_router(), saga_router())
    setup_dishka(container, broker=broker, auto_inject=True)

    scheduler = await start_jobs(container)
    # FastStream stops the scheduler before the broker and closes the container after it
    await FastStream(broker, on_shutdown=[scheduler.shutdown], after_shutdown=[container.close]).run()
    logger.info("Worker shutdown complete")


async def start_jobs(container: AsyncContainer) -> AsyncIOScheduler:
    """Prepare the cluster, then schedule the pod watch, the saga queue and timeouts, and DLQ retries."""
    k8s_worker = await container.get(KubernetesWorker)
    await k8s_worker.ensure_namespace_security()
    await k8s_worker.ensure_image_pre_puller_daemonset()

    monitor = await container.get(PodMonitor)
    orchestrator = await container.get(SagaOrchestrator)
    dlq_manager = await container.get(DLQManager)

    scheduler = AsyncIOScheduler()
    jobs = (
        ("pod_monitor_watch", monitor.watch_cycle, 5, 60),
        ("saga_try_schedule", orchestrator.try_schedule_from_queue, 10, 30),
        ("saga_check_timeouts", orchestrator.check_timeouts, 30, 60),
        ("dlq_monitor_retries", dlq_manager.process_monitoring_cycle, 10, 60),
    )
    for job_id, job, seconds, grace in jobs:
        scheduler.add_job(
            job, trigger="interval", seconds=seconds, id=job_id, max_instances=1, misfire_grace_time=grace
        )
    scheduler.start()
    return scheduler


if __name__ == "__main__":
    main()
