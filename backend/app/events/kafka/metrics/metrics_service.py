from typing import ClassVar, Optional

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


class KafkaMetricsServiceSingleton:
    """Singleton service for Kafka metrics (alternative approach)"""
    _instance: ClassVar[Optional['KafkaMetricsServiceSingleton']] = None
    _initialized: ClassVar[bool] = False

    def __new__(cls) -> 'KafkaMetricsServiceSingleton':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not KafkaMetricsServiceSingleton._initialized:
            self.manager = MetricsCollectorManager()
            KafkaMetricsServiceSingleton._initialized = True
            logger.info("Kafka metrics singleton service initialized")

    async def get_collector(self) -> KafkaMetricsCollector:
        """Get metrics collector instance"""
        return await self.manager.get_collector()  # type: ignore[no-any-return]

    async def shutdown(self) -> None:
        """Shutdown metrics collector"""
        await self.manager.close_collector()


def get_metrics_manager() -> MetricsCollectorManager:
    """Get metrics manager instance (for backward compatibility)
    
    This function now returns a manager from the singleton service.
    """
    service = KafkaMetricsServiceSingleton()
    return service.manager  # type: ignore[no-any-return]
