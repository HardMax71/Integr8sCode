from app.core.metrics.base import BaseMetrics


class EventMetrics(BaseMetrics):
    """Metrics for event processing and Kafka."""

    def _create_instruments(self) -> None:
        # Core event metrics
        self.event_published = self._meter.create_counter(
            name="events.published.total", description="Total number of events published", unit="1"
        )

        self.event_processing_duration = self._meter.create_histogram(
            name="event.processing.duration", description="Time spent processing events in seconds", unit="s"
        )

        self.event_processing_errors = self._meter.create_counter(
            name="event.processing.errors.total", description="Total number of event processing errors", unit="1"
        )

        # Event bus metrics
        self.event_bus_queue_size = self._meter.create_up_down_counter(
            name="event.bus.queue.size", description="Size of event bus message queue", unit="1"
        )

        # Event replay metrics
        self.event_replay_operations = self._meter.create_counter(
            name="event.replay.operations.total", description="Total number of event replay operations", unit="1"
        )

        # Kafka-specific metrics
        self.kafka_messages_produced = self._meter.create_counter(
            name="kafka.messages.produced.total", description="Total number of messages produced to Kafka", unit="1"
        )

        self.kafka_messages_consumed = self._meter.create_counter(
            name="kafka.messages.consumed.total", description="Total number of messages consumed from Kafka", unit="1"
        )

        self.kafka_production_errors = self._meter.create_counter(
            name="kafka.production.errors.total", description="Total number of Kafka production errors", unit="1"
        )

        self.kafka_consumption_errors = self._meter.create_counter(
            name="kafka.consumption.errors.total", description="Total number of Kafka consumption errors", unit="1"
        )

    def record_event_published(self, event_type: str, event_category: str | None = None) -> None:
        if event_category is None:
            event_category = event_type.split(".")[0] if "." in event_type else event_type

        self.event_published.add(1, attributes={"event_type": event_type, "event_category": event_category})

    def record_event_processing_duration(self, duration_seconds: float, event_type: str) -> None:
        self.event_processing_duration.record(duration_seconds, attributes={"event_type": event_type})

    def record_event_replay_operation(self, operation: str, status: str) -> None:
        self.event_replay_operations.add(1, attributes={"operation": operation, "status": status})

    def record_event_stored(self, event_type: str, collection: str) -> None:
        self.event_published.add(1, attributes={"event_type": event_type, "aggregate_type": collection})

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

    def record_event_store_duration(self, duration: float, operation: str, collection: str) -> None:
        self.event_processing_duration.record(duration, attributes={"operation": operation, "collection": collection})

    def record_event_store_failed(self, event_type: str, error_type: str) -> None:
        self.event_processing_errors.add(
            1, attributes={"event_type": event_type, "error_type": error_type, "operation": "store"}
        )

    def record_event_query_duration(self, duration: float, query_type: str, collection: str) -> None:
        self.event_processing_duration.record(
            duration, attributes={"operation": f"query_{query_type}", "collection": collection}
        )

    def record_processing_duration(
        self, duration_seconds: float, topic: str, event_type: str, consumer_group: str
    ) -> None:
        self.event_processing_duration.record(
            duration_seconds, attributes={"topic": topic, "event_type": event_type, "consumer_group": consumer_group}
        )

    def record_kafka_message_produced(self, topic: str, partition: int = -1) -> None:
        self.kafka_messages_produced.add(
            1, attributes={"topic": topic, "partition": str(partition) if partition >= 0 else "auto"}
        )

    def record_kafka_message_consumed(self, topic: str, consumer_group: str) -> None:
        self.kafka_messages_consumed.add(1, attributes={"topic": topic, "consumer_group": consumer_group})

    def record_kafka_production_error(self, topic: str, error_type: str) -> None:
        self.kafka_production_errors.add(1, attributes={"topic": topic, "error_type": error_type})

    def record_kafka_consumption_error(self, topic: str, consumer_group: str, error_type: str) -> None:
        self.kafka_consumption_errors.add(
            1, attributes={"topic": topic, "consumer_group": consumer_group, "error_type": error_type}
        )

    def update_event_bus_queue_size(self, delta: int, queue_name: str = "default") -> None:
        self.event_bus_queue_size.add(delta, attributes={"queue": queue_name})

    def set_event_bus_queue_size(self, size: int, queue_name: str = "default") -> None:
        key = f"_event_bus_size_{queue_name}"
        current_val = getattr(self, key, 0)
        delta = size - current_val
        if delta != 0:
            self.event_bus_queue_size.add(delta, attributes={"queue": queue_name})
        setattr(self, key, size)
