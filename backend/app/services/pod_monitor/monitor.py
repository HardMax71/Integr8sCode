import time
from dataclasses import dataclass
from enum import auto
from typing import Any

import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import watch as k8s_watch

from app.core.metrics import KubernetesMetrics
from app.core.utils import StringEnum
from app.domain.events import DomainEvent
from app.services.kafka_event_service import KafkaEventService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper, WatchEventType

# Type aliases
type ResourceVersion = str
type KubeEvent = dict[str, Any]


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
    resource_version: ResourceVersion | None


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
        kafka_event_service: KafkaEventService,
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
        self._kafka_event_service = kafka_event_service

        # Watch cursor — set from LIST on first run or after 410 Gone
        self._last_resource_version: ResourceVersion | None = None

        # Metrics
        self._metrics = kubernetes_metrics

        self.logger.info(f"PodMonitor initialized for namespace {config.namespace}")

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
            f"Starting pod watch from rv={self._last_resource_version}, "
            f"selector: {self.config.label_selector}"
        )

        kwargs: dict[str, Any] = {
            "namespace": self.config.namespace,
            "label_selector": self.config.label_selector,
            "timeout_seconds": self.config.watch_timeout_seconds,
            "resource_version": self._last_resource_version,
        }

        if self.config.field_selector:
            kwargs["field_selector"] = self.config.field_selector

        async for event in self._watch.stream(self._v1.list_namespaced_pod, **kwargs):
            await self._process_raw_event(event)

        # Store resource version from watch for next iteration
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

        for pod in pod_list.items:
            event = PodEvent(
                event_type=WatchEventType.ADDED,
                pod=pod,
                resource_version=pod.metadata.resource_version if pod.metadata else None,
            )
            await self._process_pod_event(event)

        # Use the list's resource_version as the authoritative cursor
        self._last_resource_version = pod_list.metadata.resource_version

        self.logger.info(
            f"Listed {len(pod_list.items)} existing pods, rv={self._last_resource_version}"
        )

    async def _process_raw_event(self, raw_event: KubeEvent) -> None:
        """Process a raw Kubernetes watch event."""
        try:
            event = PodEvent(
                event_type=WatchEventType(raw_event["type"].upper()),
                pod=raw_event["object"],
                resource_version=(
                    raw_event["object"].metadata.resource_version if raw_event["object"].metadata else None
                ),
            )

            await self._process_pod_event(event)

        except (KeyError, ValueError) as e:
            self.logger.error(f"Invalid event format: {e}")
            self._metrics.record_pod_monitor_watch_error(ErrorType.PROCESSING_ERROR)

    async def _process_pod_event(self, event: PodEvent) -> None:
        """Process a pod event."""
        start_time = time.time()

        try:
            # Update resource version for crash recovery
            if event.resource_version:
                self._last_resource_version = event.resource_version

            # Skip ignored phases
            pod_phase = event.pod.status.phase if event.pod.status else None
            if pod_phase in self.config.ignored_pod_phases:
                return

            pod_name = event.pod.metadata.name

            # Map to application events
            app_events = await self._event_mapper.map_pod_event(event.pod, event.event_type)

            # Publish events
            for app_event in app_events:
                await self._publish_event(app_event, event.pod)

            if app_events:
                self.logger.info(
                    f"Processed {event.event_type} event for pod {pod_name} "
                    f"(phase: {pod_phase or 'Unknown'}), "
                    f"published {len(app_events)} events"
                )

            duration = time.time() - start_time
            self._metrics.record_pod_monitor_event_processing_duration(duration, event.event_type)

        except Exception as e:
            self.logger.error(f"Error processing pod event: {e}", exc_info=True)
            self._metrics.record_pod_monitor_watch_error(ErrorType.PROCESSING_ERROR)

    async def _publish_event(self, event: DomainEvent, pod: k8s_client.V1Pod) -> None:
        """Publish event to Kafka and store in events collection."""
        try:
            execution_id = getattr(event, "execution_id", None) or event.aggregate_id
            key = str(execution_id or (pod.metadata.name if pod.metadata else "unknown"))

            await self._kafka_event_service.publish_event(event=event, key=key)

            phase = pod.status.phase if pod.status else "Unknown"
            self._metrics.record_pod_monitor_event_published(event.event_type, phase)

        except Exception as e:
            self.logger.error(f"Error publishing event: {e}", exc_info=True)
