from app.core.metrics.base import BaseMetrics


class ReplayMetrics(BaseMetrics):
    """Metrics for event replay operations."""

    def _create_instruments(self) -> None:
        # Core replay metrics
        self.replay_sessions_created = self._meter.create_counter(
            name="replay.sessions.created.total", description="Total number of replay sessions created", unit="1"
        )

        self.replay_sessions_active = self._meter.create_up_down_counter(
            name="replay.sessions.active", description="Number of currently active replay sessions", unit="1"
        )

        self.replay_events_processed = self._meter.create_counter(
            name="replay.events.processed.total", description="Total number of events replayed", unit="1"
        )

        self.replay_events_failed = self._meter.create_counter(
            name="replay.events.failed.total", description="Total number of failed replay events", unit="1"
        )

        self.replay_events_skipped = self._meter.create_counter(
            name="replay.events.skipped.total", description="Total number of skipped replay events", unit="1"
        )

        # Performance metrics
        self.replay_duration = self._meter.create_histogram(
            name="replay.duration", description="Duration of replay sessions in seconds", unit="s"
        )

        self.replay_event_processing_time = self._meter.create_histogram(
            name="replay.event.processing.time",
            description="Time to process individual replay events in seconds",
            unit="s",
        )

        self.replay_throughput = self._meter.create_histogram(
            name="replay.throughput", description="Events replayed per second", unit="event/s"
        )

        self.replay_batch_size = self._meter.create_histogram(
            name="replay.batch.size", description="Size of replay batches", unit="1"
        )

        # Status tracking
        self.replay_status_changes = self._meter.create_counter(
            name="replay.status.changes.total", description="Total replay session status changes", unit="1"
        )

        self.replay_sessions_by_status = self._meter.create_up_down_counter(
            name="replay.sessions.by.status", description="Number of replay sessions by status", unit="1"
        )

        # Target metrics
        self.replay_by_target = self._meter.create_counter(
            name="replay.by.target.total", description="Total replays by target type", unit="1"
        )

        self.replay_target_errors = self._meter.create_counter(
            name="replay.target.errors.total", description="Errors by replay target", unit="1"
        )

        # Speed control metrics
        self.replay_speed_multiplier = self._meter.create_histogram(
            name="replay.speed.multiplier", description="Speed multiplier used for replay sessions", unit="x"
        )

        self.replay_delay_applied = self._meter.create_histogram(
            name="replay.delay.applied", description="Delay applied between replay events in seconds", unit="s"
        )

        # Filter metrics
        self.replay_events_filtered = self._meter.create_counter(
            name="replay.events.filtered.total", description="Total events filtered during replay", unit="1"
        )

        self.replay_filter_effectiveness = self._meter.create_histogram(
            name="replay.filter.effectiveness", description="Percentage of events passing filters", unit="%"
        )

        # Memory and resource metrics
        self.replay_memory_usage = self._meter.create_histogram(
            name="replay.memory.usage", description="Memory usage during replay in MB", unit="MB"
        )

        self.replay_queue_size = self._meter.create_up_down_counter(
            name="replay.queue.size", description="Size of replay event queue", unit="1"
        )

    def record_session_created(self, replay_type: str, target: str) -> None:
        self.replay_sessions_created.add(1, attributes={"replay_type": replay_type, "target": target})

    def update_active_replays(self, count: int) -> None:
        # Track the delta for gauge-like behavior
        key = "_active_replays"
        current_val = getattr(self, key, 0)
        delta = count - current_val
        if delta != 0:
            self.replay_sessions_active.add(delta)
        setattr(self, key, count)

    def increment_active_replays(self) -> None:
        self.replay_sessions_active.add(1)

    def decrement_active_replays(self) -> None:
        self.replay_sessions_active.add(-1)

    def record_events_replayed(self, replay_type: str, event_type: str, status: str, count: int = 1) -> None:
        if status == "success":
            self.replay_events_processed.add(count, attributes={"replay_type": replay_type, "event_type": event_type})
        elif status == "failed":
            self.replay_events_failed.add(count, attributes={"replay_type": replay_type, "event_type": event_type})
        elif status == "skipped":
            self.replay_events_skipped.add(count, attributes={"replay_type": replay_type, "event_type": event_type})

    def record_event_replayed(self, replay_type: str, event_type: str, status: str) -> None:
        self.record_events_replayed(replay_type, event_type, status, 1)

    def record_replay_duration(self, duration_seconds: float, replay_type: str, total_events: int = 0) -> None:
        self.replay_duration.record(duration_seconds, attributes={"replay_type": replay_type})

        # Calculate and record throughput if events were processed
        if total_events > 0 and duration_seconds > 0:
            throughput = total_events / duration_seconds
            self.replay_throughput.record(throughput, attributes={"replay_type": replay_type})

    def record_event_processing_time(self, duration_seconds: float, event_type: str) -> None:
        self.replay_event_processing_time.record(duration_seconds, attributes={"event_type": event_type})

    def record_replay_error(self, error_type: str, replay_type: str = "unknown") -> None:
        self.replay_events_failed.add(1, attributes={"error_type": error_type, "replay_type": replay_type})

    def record_status_change(self, session_id: str, from_status: str, to_status: str) -> None:
        self.replay_status_changes.add(1, attributes={"from_status": from_status, "to_status": to_status})

        # Update sessions by status
        self.update_sessions_by_status(from_status, -1)
        self.update_sessions_by_status(to_status, 1)

    def update_sessions_by_status(self, status: str, delta: int) -> None:
        if delta != 0:
            self.replay_sessions_by_status.add(delta, attributes={"status": status})

    def record_replay_by_target(self, target: str, success: bool) -> None:
        self.replay_by_target.add(1, attributes={"target": target, "success": str(success)})

        if not success:
            self.replay_target_errors.add(1, attributes={"target": target})

    def record_speed_multiplier(self, multiplier: float, replay_type: str) -> None:
        self.replay_speed_multiplier.record(multiplier, attributes={"replay_type": replay_type})

    def record_delay_applied(self, delay_seconds: float) -> None:
        self.replay_delay_applied.record(delay_seconds)

    def record_batch_size(self, size: int, replay_type: str) -> None:
        self.replay_batch_size.record(size, attributes={"replay_type": replay_type})

    def record_events_filtered(self, filter_type: str, count: int) -> None:
        self.replay_events_filtered.add(count, attributes={"filter_type": filter_type})

    def record_filter_effectiveness(self, passed: int, total: int, filter_type: str) -> None:
        if total > 0:
            effectiveness = (passed / total) * 100
            self.replay_filter_effectiveness.record(effectiveness, attributes={"filter_type": filter_type})

    def record_replay_memory_usage(self, memory_mb: float, session_id: str) -> None:
        self.replay_memory_usage.record(memory_mb, attributes={"session_id": session_id})

    def update_replay_queue_size(self, session_id: str, size: int) -> None:
        # Track the delta for gauge-like behavior
        key = f"_queue_{session_id}"
        current_val = getattr(self, key, 0)
        delta = size - current_val
        if delta != 0:
            self.replay_queue_size.add(delta, attributes={"session_id": session_id})
        setattr(self, key, size)
