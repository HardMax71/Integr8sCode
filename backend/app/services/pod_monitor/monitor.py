import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import auto
from typing import Any

import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import watch as k8s_watch
from kubernetes_asyncio.client.rest import ApiException

from app.core.metrics import KubernetesMetrics
from app.core.utils import StringEnum
from app.events import UnifiedProducer
from app.infrastructure.kafka.topics import EXECUTION_TERMINAL_EVENT_TYPES
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper, PodMonitorEvent, WatchEventType


class ErrorType(StringEnum):
    """Error types for metrics."""

    RESOURCE_VERSION_EXPIRED = auto()
    API_ERROR = auto()
    UNEXPECTED = auto()
    PROCESSING_ERROR = auto()


@dataclass(frozen=True, slots=True)
class PodEvent:
    """Immutable pod event data."""

    event_type: WatchEventType
    pod: k8s_client.V1Pod


class PodMonitor:
    """
    Monitors Kubernetes pods and publishes lifecycle events.

    Uses the list-then-watch pattern:
    - On first call (or after 410 Gone), LISTs all pods to get current state
      and a resource_version cursor.
    - Subsequent calls WATCH from that cursor, receiving only new changes.

    Stateless service — all lifecycle (watch scheduling, error handling,
    shutdown) is managed by APScheduler in the DI provider.
    """

    def __init__(
        self,
        config: PodMonitorConfig,
        producer: UnifiedProducer,
        logger: structlog.stdlib.BoundLogger,
        api_client: k8s_client.ApiClient,
        event_mapper: PodEventMapper,
        kubernetes_metrics: KubernetesMetrics,
    ) -> None:
        self.logger = logger
        self.config = config

        # Kubernetes clients created from ApiClient
        self._v1 = k8s_client.CoreV1Api(api_client)
        self._watch = k8s_watch.Watch()

        # Components
        self._event_mapper = event_mapper
        self._producer = producer

        # Watch cursor — set from LIST on first run or after 410 Gone
        self._last_resource_version: str | None = None

        self._pod_phases: dict[str, str] = {}

        # Metrics
        self._metrics = kubernetes_metrics

        self.logger.info("PodMonitor initialized", namespace=config.namespace)

    async def watch_pod_events(self) -> None:
        """Run a single bounded K8s watch stream using list-then-watch.

        On first call (or when _last_resource_version is None), performs a LIST
        to get current state and a resource_version cursor. Then watches from
        that cursor.

        Returns normally when the server-side timeout expires.
        Raises on K8s API errors — the caller (provider) handles retries.
        """
        if not self._last_resource_version:
            await self._list_and_process_existing_pods()

        self.logger.info(
            "Starting pod watch",
            rv=self._last_resource_version,
            selector=self.config.label_selector,
        )

        kwargs: dict[str, Any] = {
            "namespace": self.config.namespace,
            "label_selector": self.config.label_selector,
            "timeout_seconds": self.config.watch_timeout_seconds,
            "resource_version": self._last_resource_version,
        }

        if self.config.field_selector:
            kwargs["field_selector"] = self.config.field_selector

        try:
            async for event in self._watch.stream(self._v1.list_namespaced_pod, **kwargs):
                if event["type"] not in WatchEventType:
                    continue
                await self._process_pod_event(PodEvent(event_type=WatchEventType(event["type"]), pod=event["object"]))
        finally:
            if self._watch.resource_version:
                self._last_resource_version = self._watch.resource_version

    async def _list_and_process_existing_pods(self) -> None:
        """LIST all matching pods to bootstrap state and get a resource_version cursor."""
        kwargs: dict[str, Any] = {
            "namespace": self.config.namespace,
            "label_selector": self.config.label_selector,
        }
        if self.config.field_selector:
            kwargs["field_selector"] = self.config.field_selector

        pod_list = await self._v1.list_namespaced_pod(**kwargs)
        self._metrics.record_pod_monitor_reconciliation_run()
        self._pod_phases.clear()
        self._metrics.update_pods_by_phase(Counter())

        for pod in pod_list.items:
            event = PodEvent(event_type=WatchEventType.ADDED, pod=pod)
            await self._process_pod_event(event)

        # Use the list's resource_version as the authoritative cursor
        self._last_resource_version = pod_list.metadata.resource_version

        self.logger.info(
            "Listed existing pods",
            count=len(pod_list.items),
            rv=self._last_resource_version,
        )

    async def _process_pod_event(self, event: PodEvent) -> None:
        """Process a pod event."""
        start_time = time.time()

        pod_phase = event.pod.status.phase if event.pod.status else None
        self._track_pod_phase(event.event_type, event.pod, pod_phase)

        # Skip ignored phases
        if pod_phase in self.config.ignored_pod_phases:
            return

        try:
            app_events = await self._event_mapper.map_pod_event(event.pod, event.event_type)
            for app_event in app_events:
                await self._publish_event(app_event, event.pod)
        except Exception:
            self.logger.error("Error processing pod event", exc_info=True)
            self._metrics.record_pod_monitor_watch_error(ErrorType.PROCESSING_ERROR)
            return
        finally:
            duration = time.time() - start_time
            self._metrics.record_pod_monitor_event_processing_duration(duration, event.event_type)

        if any(e.event_type in EXECUTION_TERMINAL_EVENT_TYPES for e in app_events):
            self._record_pod_lifetime(event.pod, pod_phase)
            await self._delete_pod(event.pod)

        if app_events:
            pod_name = event.pod.metadata.name if event.pod.metadata else "unknown"
            self.logger.info(
                "Processed pod event",
                event_type=event.event_type,
                pod_name=pod_name,
                phase=pod_phase or "Unknown",
                published=len(app_events),
            )

    def _track_pod_phase(self, event_type: WatchEventType, pod: k8s_client.V1Pod, phase: str | None) -> None:
        """Keep the per-phase pod count current for the pods.by.phase gauge."""
        if not pod.metadata or not pod.metadata.name:
            return
        if event_type == WatchEventType.DELETED:
            self._pod_phases.pop(pod.metadata.name, None)
        else:
            self._pod_phases[pod.metadata.name] = phase or "Unknown"
        self._metrics.update_pods_by_phase(Counter(self._pod_phases.values()))

    def _record_pod_lifetime(self, pod: k8s_client.V1Pod, phase: str | None) -> None:
        """Record seconds from pod creation until the monitor saw the execution finish."""
        created_at = pod.metadata.creation_timestamp if pod.metadata else None
        if created_at is None:
            return
        lifetime = (datetime.now(timezone.utc) - created_at).total_seconds()
        language = (pod.metadata.labels or {}).get("language", "unknown")
        self._metrics.record_pod_lifetime(lifetime, phase or "Unknown", language)

    async def _publish_event(self, event: PodMonitorEvent, pod: k8s_client.V1Pod) -> None:
        """Publish event to Kafka and store in events collection."""
        await self._producer.produce(event_to_produce=event, key=event.execution_id)

        phase = pod.status.phase if pod.status else "Unknown"
        self._metrics.record_pod_monitor_event_published(event.event_type, phase)

    async def _delete_pod(self, pod: k8s_client.V1Pod) -> None:
        """Delete a pod after its data has been fully extracted.

        Frees the Kueue quota slot so gated executor pods can be admitted.
        The ConfigMap is garbage-collected automatically via ownerReference.
        """
        pod_name = pod.metadata.name
        try:
            await self._v1.delete_namespaced_pod(
                name=pod_name,
                namespace=pod.metadata.namespace,
                grace_period_seconds=0,
            )
            self.logger.info("Deleted completed pod", pod_name=pod_name)
        except ApiException as e:
            self.logger.warning("Failed to delete pod", pod_name=pod_name, status=e.status, reason=e.reason)
