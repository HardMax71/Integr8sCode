from app.core.metrics.base import BaseMetrics


class KubernetesMetrics(BaseMetrics):
    """Metrics for Kubernetes and pod operations."""

    def _create_instruments(self) -> None:
        # Pod creation metrics
        self.pod_creations = self._meter.create_counter(
            name="pod.creations.total", description="Total number of pod creations", unit="1"
        )

        self.pod_creation_failures = self._meter.create_counter(
            name="pod.creation.failures.total", description="Total number of pod creation failures by reason", unit="1"
        )

        self.pod_creation_duration = self._meter.create_histogram(
            name="pod.creation.duration", description="Time taken to create pods in seconds", unit="s"
        )

        self.active_pod_creations = self._meter.create_up_down_counter(
            name="pod.creations.active", description="Number of pods currently being created", unit="1"
        )

        # Pod lifecycle metrics
        self.pod_phase_transitions = self._meter.create_counter(
            name="pod.phase.transitions.total", description="Total number of pod phase transitions", unit="1"
        )

        self.pod_lifetime = self._meter.create_histogram(
            name="pod.lifetime", description="Total lifetime of pods in seconds", unit="s"
        )

        self.pods_by_phase = self._meter.create_up_down_counter(
            name="pods.by.phase", description="Current number of pods by phase", unit="1"
        )

        # ConfigMap metrics
        self.config_maps_created = self._meter.create_counter(
            name="configmaps.created.total", description="Total number of ConfigMaps created", unit="1"
        )

        # Pod monitor metrics
        self.pod_monitor_events = self._meter.create_counter(
            name="pod.monitor.events.total", description="Total number of pod monitor events", unit="1"
        )

        self.pod_monitor_processing_duration = self._meter.create_histogram(
            name="pod.monitor.processing.duration",
            description="Time spent processing pod monitor events in seconds",
            unit="s",
        )

        self.pod_monitor_reconciliations = self._meter.create_counter(
            name="pod.monitor.reconciliations.total",
            description="Total number of pod monitor reconciliations",
            unit="1",
        )

        self.pod_monitor_watch_errors = self._meter.create_counter(
            name="pod.monitor.watch.errors.total", description="Total number of pod monitor watch errors", unit="1"
        )

        self.pod_monitor_watch_reconnects = self._meter.create_counter(
            name="pod.monitor.watch.reconnects.total",
            description="Total number of pod monitor watch reconnects",
            unit="1",
        )

        self.pods_monitored = self._meter.create_up_down_counter(
            name="pods.monitored", description="Number of pods currently being monitored", unit="1"
        )

    def record_pod_creation_failure(self, failure_reason: str) -> None:
        self.pod_creation_failures.add(1, attributes={"failure_reason": failure_reason})

    def record_pod_created(self, status: str, language: str) -> None:
        self.pod_creations.add(1, attributes={"status": status, "language": language})

    def record_pod_creation_duration(self, duration_seconds: float, language: str) -> None:
        self.pod_creation_duration.record(duration_seconds, attributes={"language": language})

    def update_active_pod_creations(self, count: int) -> None:
        key = "_active_pod_creations"
        current_val = getattr(self, key, 0)
        delta = count - current_val
        if delta != 0:
            self.active_pod_creations.add(delta)
        setattr(self, key, count)

    def increment_active_pod_creations(self) -> None:
        self.active_pod_creations.add(1)

    def decrement_active_pod_creations(self) -> None:
        self.active_pod_creations.add(-1)

    def record_config_map_created(self, status: str) -> None:
        self.config_maps_created.add(1, attributes={"status": status})

    def record_k8s_pod_created(self, status: str, language: str) -> None:
        self.record_pod_created(status, language)

    def record_k8s_pod_creation_duration(self, duration_seconds: float, language: str) -> None:
        self.record_pod_creation_duration(duration_seconds, language)

    def record_k8s_config_map_created(self, status: str) -> None:
        self.record_config_map_created(status)

    def increment_pod_monitor_watch_reconnects(self) -> None:
        self.pod_monitor_watch_reconnects.add(1)

    def record_pod_monitor_event_processing_duration(self, duration_seconds: float, event_type: str) -> None:
        self.pod_monitor_processing_duration.record(duration_seconds, attributes={"event_type": event_type})

    def record_pod_monitor_event_published(self, event_type: str, pod_phase: str) -> None:
        self.pod_monitor_events.add(1, attributes={"event_type": event_type, "pod_phase": pod_phase})

    def record_pod_monitor_reconciliation_run(self, status: str) -> None:
        self.pod_monitor_reconciliations.add(1, attributes={"status": status})

    def record_pod_monitor_watch_error(self, error_type: str) -> None:
        self.pod_monitor_watch_errors.add(1, attributes={"error_type": error_type})

    def update_pod_monitor_pods_watched(self, count: int) -> None:
        key = "_pods_monitored"
        current_val = getattr(self, key, 0)
        delta = count - current_val
        if delta != 0:
            self.pods_monitored.add(delta)
        setattr(self, key, count)

    def record_pod_phase_transition(self, from_phase: str, to_phase: str, pod_name: str) -> None:
        self.pod_phase_transitions.add(
            1, attributes={"from_phase": from_phase, "to_phase": to_phase, "pod_name": pod_name}
        )

    def record_pod_lifetime(self, lifetime_seconds: float, final_phase: str, language: str) -> None:
        self.pod_lifetime.record(lifetime_seconds, attributes={"final_phase": final_phase, "language": language})

    def update_pods_by_phase(self, phase: str, count: int) -> None:
        key = f"_pods_phase_{phase}"
        current_val = getattr(self, key, 0)
        delta = count - current_val
        if delta != 0:
            self.pods_by_phase.add(delta, attributes={"phase": phase})
        setattr(self, key, count)
