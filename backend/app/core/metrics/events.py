from app.core.metrics.base import BaseMetrics


class EventMetrics(BaseMetrics):
    """Metrics for domain-level event publishing.

    Kafka publish and consume metrics, consume failures included, come from
    KafkaTelemetryMiddleware on the broker.
    """

    def _create_instruments(self) -> None:
        self.event_published = self._meter.create_counter(
            name="events.published.total", description="Total number of events published", unit="1"
        )

        self.event_processing_duration = self._meter.create_histogram(
            name="event.processing.duration", description="Time spent processing events in seconds", unit="s"
        )

    def record_event_published(self, event_type: str, event_category: str | None = None) -> None:
        if event_category is None:
            event_category = event_type.split(".")[0] if "." in event_type else event_type

        self.event_published.add(1, attributes={"event_type": event_type, "event_category": event_category})

    def record_event_processing_duration(self, duration_seconds: float, event_type: str) -> None:
        self.event_processing_duration.record(duration_seconds, attributes={"event_type": event_type})
