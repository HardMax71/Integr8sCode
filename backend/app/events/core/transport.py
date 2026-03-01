import structlog
from faststream.kafka import KafkaBroker

from app.domain.events import DomainEvent


class KafkaEventTransport:
    """Publishes events to Kafka.

    Transport-level metrics (produced count, error count, latency) are
    recorded automatically by KafkaTelemetryMiddleware on the broker.
    """

    def __init__(
        self,
        broker: KafkaBroker,
        logger: structlog.stdlib.BoundLogger,
    ):
        self._broker = broker
        self._logger = logger

    async def publish(self, event: DomainEvent, topic: str, key: str) -> None:
        """Publish event to Kafka."""
        await self._broker.publish(
            message=event,
            topic=topic,
            key=key.encode(),
        )
        self._logger.debug("Event sent to topic", event_type=event.event_type, topic=topic)
