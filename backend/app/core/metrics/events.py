from app.core.metrics.base import BaseMetrics


class EventMetrics(BaseMetrics):
    """Metrics for domain-level event processing.

    Transport-level Kafka metrics (produced/consumed/errors) are handled
    automatically by KafkaTelemetryMiddleware on the broker.
    """

    def _create_instruments(self) -> None:
        self.event_published = self._meter.create_counter(
            name="events.published.total", description="Total number of events published", unit="1"
        )

        self.event_processing_duration = self._meter.create_histogram(
            name="event.processing.duration", description="Time spent processing events in seconds", unit="s"
        )

        self.event_processing_errors = self._meter.create_counter(
            name="event.processing.errors.total", description="Total number of event processing errors", unit="1"
        )

    def record_event_published(self, event_type: str, event_category: str | None = None) -> None:
        if event_category is None:
            event_category = event_type.split(".")[0] if "." in event_type else event_type

        self.event_published.add(1, attributes={"event_type": event_type, "event_category": event_category})

    def record_event_processing_duration(self, duration_seconds: float, event_type: str) -> None:
        self.event_processing_duration.record(duration_seconds, attributes={"event_type": event_type})

    def record_events_processing_failed(
        self, topic: str, event_type: str, consumer_group: str, error_type: str
    ) -> None:
        self.event_processing_errors.add(
            1,
            attributes={
                "topic": topic,
                "event_type": event_type,
                "consumer_group": consumer_group,
                "error_type": error_type,
            },
        )
