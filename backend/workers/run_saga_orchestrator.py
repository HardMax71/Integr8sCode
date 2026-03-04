import structlog
from app.core.container import create_saga_orchestrator_container
from app.events.handlers import register_saga_subscriber
from app.services.saga import SagaOrchestrator
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dishka import AsyncContainer
from faststream.kafka import KafkaBroker

from workers.bootstrap import run_worker

_scheduler = AsyncIOScheduler()


async def _on_startup(
    container: AsyncContainer, broker: KafkaBroker, logger: structlog.stdlib.BoundLogger
) -> None:
    orchestrator = await container.get(SagaOrchestrator)
    _scheduler.add_job(
        orchestrator.check_timeouts,
        trigger="interval",
        seconds=30,
        id="saga_check_timeouts",
        max_instances=1,
        misfire_grace_time=60,
    )
    _scheduler.add_job(
        orchestrator.try_schedule_from_queue,
        trigger="interval",
        seconds=10,
        id="saga_try_schedule",
        max_instances=1,
        misfire_grace_time=30,
    )
    _scheduler.start()
    logger.info("SagaOrchestrator initialized (APScheduler: timeouts=30s, scheduling=10s)")


async def _on_shutdown() -> None:
    _scheduler.shutdown(wait=False)


def main() -> None:
    """Main entry point for saga orchestrator worker"""
    run_worker(
        worker_name="SagaOrchestrator",
        config_override="config.saga-orchestrator.toml",
        container_factory=create_saga_orchestrator_container,
        register_handlers=register_saga_subscriber,
        on_startup=_on_startup,
        on_shutdown=_on_shutdown,
    )


if __name__ == "__main__":
    main()
