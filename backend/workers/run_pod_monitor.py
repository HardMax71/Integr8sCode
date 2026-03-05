import structlog
from app.core.container import create_pod_monitor_container
from app.core.metrics import KubernetesMetrics
from app.services.pod_monitor import ErrorType, PodMonitor
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dishka import AsyncContainer
from faststream.kafka import KafkaBroker
from kubernetes_asyncio.client.rest import ApiException

from workers.bootstrap import run_worker

_scheduler = AsyncIOScheduler()


async def _on_startup(
    container: AsyncContainer, broker: KafkaBroker, logger: structlog.stdlib.BoundLogger
) -> None:
    monitor = await container.get(PodMonitor)
    kubernetes_metrics = await container.get(KubernetesMetrics)

    async def _watch_cycle() -> None:
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

    _scheduler.add_job(
        _watch_cycle,
        trigger="interval",
        seconds=5,
        id="pod_monitor_watch",
        max_instances=1,
        misfire_grace_time=60,
    )
    _scheduler.start()
    logger.info("PodMonitor initialized (APScheduler interval=5s)")


async def _on_shutdown() -> None:
    _scheduler.shutdown(wait=False)


def main() -> None:
    """Main entry point for pod monitor worker"""
    run_worker(
        worker_name="PodMonitor",
        config_override="config.pod-monitor.toml",
        container_factory=create_pod_monitor_container,
        on_startup=_on_startup,
        on_shutdown=_on_shutdown,
    )


if __name__ == "__main__":
    main()
