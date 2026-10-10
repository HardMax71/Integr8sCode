from collections.abc import Mapping

from app.core.metrics.base import BaseMetrics


class KubernetesMetrics(BaseMetrics):
    """Metrics for Kubernetes and pod operations."""

    def _create_instruments(self) -> None:
        self._active_pod_creations = 0
        self._pods_by_phase: dict[str, int] = {}

        self.pod_creations = self._meter.create_counter(
            name="pod.creations.total", description="Total number of pod creation attempts by status", unit="1"
        )

        self.pod_creation_duration = self._meter.create_histogram(
            name="pod.creation.duration", description="Time taken to create pods in seconds", unit="s"
        )

        self.active_pod_creations = self._meter.create_up_down_counter(
            name="pod.creations.active", description="Number of pods currently being created", unit="1"
        )

        self.pod_lifetime = self._meter.create_histogram(
            name="pod.lifetime",
            description="Seconds from pod creation to the pod monitor seeing it finish",
            unit="s",
        )

        self.pods_by_phase = self._meter.create_up_down_counter(
            name="pods.by.phase", description="Executor pods the pod monitor currently sees, by phase", unit="1"
        )

        self.config_maps_created = self._meter.create_counter(
            name="configmaps.created.total", description="Total number of ConfigMaps created", unit="1"
        )

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
            description="Full pod LISTs the pod monitor ran to resync its watch",
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

    def record_k8s_pod_created(self, status: str, language: str) -> None:
        self.pod_creations.add(1, attributes={"status": status, "language": language})

    def record_k8s_pod_creation_duration(self, duration_seconds: float, language: str) -> None:
        self.pod_creation_duration.record(duration_seconds, attributes={"language": language})

    def update_active_pod_creations(self, count: int) -> None:
        delta = count - self._active_pod_creations
        if delta != 0:
            self.active_pod_creations.add(delta)
        self._active_pod_creations = count

    def record_k8s_config_map_created(self, status: str) -> None:
        self.config_maps_created.add(1, attributes={"status": status})

    def increment_pod_monitor_watch_reconnects(self) -> None:
        self.pod_monitor_watch_reconnects.add(1)

    def record_pod_monitor_event_processing_duration(self, duration_seconds: float, event_type: str) -> None:
        self.pod_monitor_processing_duration.record(duration_seconds, attributes={"event_type": event_type})

    def record_pod_monitor_event_published(self, event_type: str, pod_phase: str) -> None:
        self.pod_monitor_events.add(1, attributes={"event_type": event_type, "pod_phase": pod_phase})

    def record_pod_monitor_reconciliation_run(self) -> None:
        self.pod_monitor_reconciliations.add(1)

    def record_pod_monitor_watch_error(self, error_type: str) -> None:
        self.pod_monitor_watch_errors.add(1, attributes={"error_type": error_type})

    def record_pod_lifetime(self, lifetime_seconds: float, final_phase: str, language: str) -> None:
        self.pod_lifetime.record(lifetime_seconds, attributes={"final_phase": final_phase, "language": language})

    def update_pods_by_phase(self, counts: Mapping[str, int]) -> None:
        for phase in self._pods_by_phase.keys() | counts.keys():
            delta = counts.get(phase, 0) - self._pods_by_phase.get(phase, 0)
            if delta != 0:
                self.pods_by_phase.add(delta, attributes={"phase": phase})
        self._pods_by_phase = dict(counts)
