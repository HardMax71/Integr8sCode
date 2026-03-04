import structlog
from app.core.container import create_dlq_processor_container
from app.dlq.manager import DLQManager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dishka import AsyncContainer
from faststream.kafka import KafkaBroker

from workers.bootstrap import run_worker

_scheduler = AsyncIOScheduler()


async def _on_startup(
    container: AsyncContainer, broker: KafkaBroker, logger: structlog.stdlib.BoundLogger
) -> None:
    manager = await container.get(DLQManager)
    _scheduler.add_job(
        manager.process_monitoring_cycle,
        trigger="interval",
        seconds=10,
        id="dlq_monitor_retries",
        max_instances=1,
        misfire_grace_time=60,
    )
    _scheduler.start()
    logger.info("DLQ Processor initialized (APScheduler interval=10s)")


async def _on_shutdown() -> None:
    _scheduler.shutdown(wait=False)


def main() -> None:
    """Main entry point for DLQ processor worker."""
    run_worker(
        worker_name="DLQ Processor",
        config_override="config.dlq-processor.toml",
        container_factory=create_dlq_processor_container,
        on_startup=_on_startup,
        on_shutdown=_on_shutdown,
    )


if __name__ == "__main__":
    main()
