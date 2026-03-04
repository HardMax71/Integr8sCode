
import structlog
from app.core.container import create_k8s_worker_container
from app.events.handlers import register_k8s_worker_subscriber
from app.services.k8s_worker import KubernetesWorker
from dishka import AsyncContainer
from faststream.kafka import KafkaBroker

from workers.bootstrap import run_worker


async def _on_startup(
    container: AsyncContainer, broker: KafkaBroker, logger: structlog.stdlib.BoundLogger
) -> None:
    worker = await container.get(KubernetesWorker)
    await worker.ensure_namespace_security()
    await worker.ensure_image_pre_puller_daemonset()
    logger.info("KubernetesWorker initialized with namespace security and pre-puller daemonset")


def main() -> None:
    """Main entry point for Kubernetes worker"""
    run_worker(
        worker_name="KubernetesWorker",
        config_override="config.k8s-worker.toml",
        container_factory=create_k8s_worker_container,
        register_handlers=register_k8s_worker_subscriber,
        on_startup=_on_startup,
    )


if __name__ == "__main__":
    main()
