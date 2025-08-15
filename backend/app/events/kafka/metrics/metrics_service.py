from app.core.logging import logger
from app.events.kafka.metrics.metrics_collector import KafkaMetricsCollector, MetricsCollectorManager


class KafkaMetricsService:
    """Service for managing Kafka metrics collection using dependency injection"""

    def __init__(self) -> None:
        """Initialize the metrics service with a new manager instance"""
        self.manager = MetricsCollectorManager()
        logger.info("Kafka metrics service initialized")

    async def initialize(self) -> KafkaMetricsCollector:
        """Initialize Kafka metrics collection"""
        collector = await self.manager.get_collector()
        logger.info("Kafka metrics collector started")
        return collector  # type: ignore[no-any-return]

    async def shutdown(self) -> None:
        """Shutdown Kafka metrics collection"""
        await self.manager.close_collector()
        logger.info("Kafka metrics collector stopped")

    @property
    def is_running(self) -> bool:
        """Check if metrics collector is running"""
        return self.manager.is_running  # type: ignore[no-any-return]
