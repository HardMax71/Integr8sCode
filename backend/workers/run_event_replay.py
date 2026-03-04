import structlog
from app.core.container import create_event_replay_container
from app.services.event_replay import EventReplayService
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dishka import AsyncContainer
from faststream.kafka import KafkaBroker

from workers.bootstrap import run_worker

_scheduler = AsyncIOScheduler()


async def _on_startup(
    container: AsyncContainer, broker: KafkaBroker, logger: structlog.stdlib.BoundLogger
) -> None:
    service = await container.get(EventReplayService)
    _scheduler.add_job(
        service.cleanup_old_sessions,
        trigger="interval",
        hours=6,
        kwargs={"older_than_hours": 48},
        id="replay_cleanup_old_sessions",
        max_instances=1,
        misfire_grace_time=300,
    )
    _scheduler.start()
    logger.info("Event replay service initialized (APScheduler interval=6h)")


async def _on_shutdown() -> None:
    _scheduler.shutdown(wait=False)


def main() -> None:
    """Main entry point for event replay service"""
    run_worker(
        worker_name="EventReplayService",
        config_override="config.event-replay.toml",
        container_factory=create_event_replay_container,
        on_startup=_on_startup,
        on_shutdown=_on_shutdown,
    )


if __name__ == "__main__":
    main()
