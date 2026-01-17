from app.core.metrics.base import BaseMetrics


class EventMetrics(BaseMetrics):
    """Metrics for event processing and Kafka.

    This class tracks metrics related to event processing, event buffers,
    and Kafka message production/consumption. Metrics are provided via
    dependency injection (DI) through the MetricsProvider.

    Usage (via DI):
        class MyService:
            def __init__(self, event_metrics: EventMetrics):
                self.metrics = event_metrics

            def my_method(self):
                self.metrics.record_event_published("execution.requested")
    """

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

        # Pod event metrics
        self.pod_event_published = self._meter.create_counter(
            name="pod.events.published.total", description="Total number of pod events published", unit="1"
        )

        # Event replay metrics
        self.event_replay_operations = self._meter.create_counter(
            name="event.replay.operations.total", description="Total number of event replay operations", unit="1"
        )

        # Event buffer metrics
        self.event_buffer_size = self._meter.create_up_down_counter(
            name="event.buffer.size", description="Current number of events in buffer", unit="1"
        )

        self.event_buffer_dropped = self._meter.create_counter(
            name="event.buffer.dropped.total", description="Total number of events dropped from buffer", unit="1"
        )

        self.event_buffer_processed = self._meter.create_counter(
            name="event.buffer.processed.total", description="Total number of events processed from buffer", unit="1"
        )

        self.event_buffer_latency = self._meter.create_histogram(
            name="event.buffer.latency", description="Time between event creation and processing in seconds", unit="s"
        )

        self.event_buffer_backpressure = self._meter.create_up_down_counter(
            name="event.buffer.backpressure.active",
            description="Whether backpressure is currently active (1=active, 0=inactive)",
            unit="1",
        )

        self.event_buffer_memory_usage = self._meter.create_histogram(
            name="event.buffer.memory.usage", description="Memory usage of event buffer in MB", unit="MB"
        )

        # Kafka-specific metrics
        self.kafka_messages_produced = self._meter.create_counter(
            name="kafka.messages.produced.total", description="Total number of messages produced to Kafka", unit="1"
        )

        self.kafka_messages_consumed = self._meter.create_counter(
            name="kafka.messages.consumed.total", description="Total number of messages consumed from Kafka", unit="1"
        )

        self.kafka_consumer_lag = self._meter.create_histogram(
            name="kafka.consumer.lag", description="Consumer lag in number of messages", unit="1"
        )

        self.kafka_production_errors = self._meter.create_counter(
            name="kafka.production.errors.total", description="Total number of Kafka production errors", unit="1"
        )

        self.kafka_consumption_errors = self._meter.create_counter(
            name="kafka.consumption.errors.total", description="Total number of Kafka consumption errors", unit="1"
        )

    def record_event_published(self, event_type: str, event_category: str | None = None) -> None:
        """
        Record that an event was published.

        Args:
            event_type: Full event type (e.g., "execution.requested")
            event_category: Event category (e.g., "execution"). If None, extracted from event_type.
        """
        if event_category is None:
            # Extract category from event type (e.g., "execution" from "execution.requested")
            event_category = event_type.split(".")[0] if "." in event_type else event_type

        self.event_published.add(1, attributes={"event_type": event_type, "event_category": event_category})

    def record_event_processing_duration(self, duration_seconds: float, event_type: str) -> None:
        self.event_processing_duration.record(duration_seconds, attributes={"event_type": event_type})

    def record_pod_event_published(self, event_type: str) -> None:
        self.pod_event_published.add(1, attributes={"event_type": event_type})

    def record_event_replay_operation(self, operation: str, status: str) -> None:
        self.event_replay_operations.add(1, attributes={"operation": operation, "status": status})

    def update_event_buffer_size(self, delta: int) -> None:
        self.event_buffer_size.add(delta)

    def record_event_buffer_dropped(self) -> None:
        self.event_buffer_dropped.add(1)

    def record_event_buffer_processed(self) -> None:
        self.event_buffer_processed.add(1)

    def record_event_buffer_latency(self, latency_seconds: float) -> None:
        self.event_buffer_latency.record(latency_seconds)

    def set_event_buffer_backpressure(self, active: bool) -> None:
        self.event_buffer_backpressure.add(-1 if not active else 0)
        self.event_buffer_backpressure.add(1 if active else 0)

    def record_event_buffer_memory_usage(self, memory_mb: float) -> None:
        self.event_buffer_memory_usage.record(memory_mb)

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
        """Record event store operation duration."""
        self.event_processing_duration.record(duration, attributes={"operation": operation, "collection": collection})

    def record_event_store_failed(self, event_type: str, error_type: str) -> None:
        """Record event store failure."""
        self.event_processing_errors.add(
            1, attributes={"event_type": event_type, "error_type": error_type, "operation": "store"}
        )

    def record_event_query_duration(self, duration: float, query_type: str, collection: str) -> None:
        """Record event query duration."""
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

    def record_kafka_consumer_lag(self, lag: int, topic: str, consumer_group: str, partition: int) -> None:
        self.kafka_consumer_lag.record(
            lag, attributes={"topic": topic, "consumer_group": consumer_group, "partition": str(partition)}
        )

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
