"""Run KubernetesWorker as a standalone worker service"""

import asyncio
import logging

from app.core.logging import setup_logger
from app.core.tracing import init_tracing
from app.domain.enums.kafka import GroupId
from app.services.k8s_worker.worker import run_kubernetes_worker
from app.settings import get_settings


def main() -> None:
    """Main entry point for Kubernetes worker"""
    # Setup logging
    setup_logger()

    # Configure root logger for worker
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    logger = logging.getLogger(__name__)
    logger.info("Starting KubernetesWorker...")

    # Initialize tracing
    settings = get_settings()
    if settings.ENABLE_TRACING:
        init_tracing(
            service_name=GroupId.K8S_WORKER,
            service_version=settings.TRACING_SERVICE_VERSION,
            enable_console_exporter=False,
            sampling_rate=settings.TRACING_SAMPLING_RATE
        )
        logger.info("Tracing initialized for KubernetesWorker")

    try:
        # Run worker
        asyncio.run(run_kubernetes_worker())
    except KeyboardInterrupt:
        logger.info("Kubernetes worker interrupted by user")
    except Exception as e:
        logger.error(f"Kubernetes worker failed: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    main()
