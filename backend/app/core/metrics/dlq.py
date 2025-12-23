from app.core.metrics.base import BaseMetrics


class DLQMetrics(BaseMetrics):
    """Metrics for Dead Letter Queue operations."""

    def _create_instruments(self) -> None:
        # DLQ message metrics
        self.dlq_messages_received = self._meter.create_counter(
            name="dlq.messages.received.total", description="Total number of messages received in DLQ", unit="1"
        )

        self.dlq_messages_retried = self._meter.create_counter(
            name="dlq.messages.retried.total", description="Total number of DLQ messages retried", unit="1"
        )

        self.dlq_messages_discarded = self._meter.create_counter(
            name="dlq.messages.discarded.total", description="Total number of DLQ messages discarded", unit="1"
        )

        # DLQ processing metrics
        self.dlq_processing_duration = self._meter.create_histogram(
            name="dlq.processing.duration", description="Time spent processing DLQ messages in seconds", unit="s"
        )

        self.dlq_message_age = self._meter.create_histogram(
            name="dlq.message.age", description="Age of messages in DLQ in seconds", unit="s"
        )

        # DLQ queue metrics
        self.dlq_queue_size = self._meter.create_up_down_counter(
            name="dlq.queue.size", description="Current size of DLQ by topic", unit="1"
        )

        self.dlq_retry_attempts = self._meter.create_histogram(
            name="dlq.retry.attempts", description="Number of retry attempts for DLQ messages", unit="1"
        )

        # DLQ error metrics
        self.dlq_processing_errors = self._meter.create_counter(
            name="dlq.processing.errors.total", description="Total number of DLQ processing errors", unit="1"
        )

        # DLQ throughput metrics
        self.dlq_throughput_rate = self._meter.create_histogram(
            name="dlq.throughput.rate", description="Messages processed per second from DLQ", unit="msg/s"
        )

    def record_dlq_message_received(self, original_topic: str, event_type: str) -> None:
        self.dlq_messages_received.add(1, attributes={"original_topic": original_topic, "event_type": event_type})

    def record_dlq_message_retried(self, original_topic: str, event_type: str, result: str) -> None:
        self.dlq_messages_retried.add(
            1, attributes={"original_topic": original_topic, "event_type": event_type, "result": result}
        )

    def record_dlq_message_discarded(self, original_topic: str, event_type: str, reason: str) -> None:
        self.dlq_messages_discarded.add(
            1, attributes={"original_topic": original_topic, "event_type": event_type, "reason": reason}
        )

    def record_dlq_processing_duration(self, duration_seconds: float, operation: str) -> None:
        self.dlq_processing_duration.record(duration_seconds, attributes={"operation": operation})

    def update_dlq_queue_size(self, original_topic: str, size: int) -> None:
        # Track the delta for gauge-like behavior
        key = f"_dlq_size_{original_topic}"
        current_val = getattr(self, key, 0)
        delta = size - current_val
        if delta != 0:
            self.dlq_queue_size.add(delta, attributes={"original_topic": original_topic})
        setattr(self, key, size)

    def record_dlq_message_age(self, age_seconds: float) -> None:
        self.dlq_message_age.record(age_seconds)

    def record_dlq_retry_attempt(self, original_topic: str, event_type: str, attempt_number: int) -> None:
        self.dlq_retry_attempts.record(
            attempt_number, attributes={"original_topic": original_topic, "event_type": event_type}
        )

    def record_dlq_processing_error(self, original_topic: str, event_type: str, error_type: str) -> None:
        self.dlq_processing_errors.add(
            1, attributes={"original_topic": original_topic, "event_type": event_type, "error_type": error_type}
        )

    def record_dlq_throughput(self, messages_per_second: float, original_topic: str) -> None:
        self.dlq_throughput_rate.record(messages_per_second, attributes={"original_topic": original_topic})

    def increment_dlq_queue_size(self, original_topic: str) -> None:
        self.dlq_queue_size.add(1, attributes={"original_topic": original_topic})

    def decrement_dlq_queue_size(self, original_topic: str) -> None:
        self.dlq_queue_size.add(-1, attributes={"original_topic": original_topic})
