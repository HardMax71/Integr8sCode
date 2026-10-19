from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import auto
from typing import Any

import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import watch as k8s_watch
from kubernetes_asyncio.client.rest import ApiException
from opentelemetry import trace

from app.core.utils import StringEnum
from app.events import UnifiedProducer
from app.infrastructure.kafka.topics import EXECUTION_TERMINAL_EVENT_TYPES
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper, WatchEventType

_POD_PHASES = ("Pending", "Running", "Succeeded", "Failed", "Unknown")


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

    The worker's scheduler runs watch_cycle every 5 seconds.
    """

    def __init__(
        self,
        config: PodMonitorConfig,
        producer: UnifiedProducer,
        logger: structlog.stdlib.BoundLogger,
        api_client: k8s_client.ApiClient,
        event_mapper: PodEventMapper,
        tracer: trace.Tracer,
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
        self._tracer = tracer

        self.logger.info("PodMonitor initialized", namespace=config.namespace)

    async def watch_pod_events(self) -> None:
        """Run a single bounded K8s watch stream using list-then-watch.

        On first call (or when _last_resource_version is None), performs a LIST
        to get current state and a resource_version cursor. Then watches from
        that cursor.

        Returns normally when the server-side timeout expires.
        Raises on K8s API errors; watch_cycle counts them and resets the cursor on a 410.
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

    async def watch_cycle(self) -> None:
        """Run one watch, note the error that ended it, then report how many pods are in each phase.

        A 410 Gone means the cursor expired, so the next cycle lists again before watching.
        """
        with self._tracer.start_as_current_span("pod_monitor.watch") as span:
            try:
                await self.watch_pod_events()
            except ApiException as e:
                if e.status == 410:
                    self.logger.warning("Resource version expired, resetting watch cursor")
                    self._last_resource_version = None
                    span.set_attribute("pod_monitor.error_type", ErrorType.RESOURCE_VERSION_EXPIRED)
                else:
                    self.logger.error("API error in watch", status=e.status, reason=e.reason)
                    span.set_attribute("pod_monitor.error_type", ErrorType.API_ERROR)
            except Exception:
                self.logger.error("Unexpected error in watch", exc_info=True)
                span.set_attribute("pod_monitor.error_type", ErrorType.UNEXPECTED)
            counts = Counter(self._pod_phases.values())
            for phase in _POD_PHASES:
                self._tracer.start_span(
                    "pod_monitor.pods", attributes={"pod.phase": phase, "pod_monitor.pods": counts[phase]}
                ).end()

    async def _list_and_process_existing_pods(self) -> None:
        """LIST all matching pods to bootstrap state and get a resource_version cursor."""
        kwargs: dict[str, Any] = {
            "namespace": self.config.namespace,
            "label_selector": self.config.label_selector,
        }
        if self.config.field_selector:
            kwargs["field_selector"] = self.config.field_selector

        with self._tracer.start_as_current_span("pod_monitor.list"):
            pod_list = await self._v1.list_namespaced_pod(**kwargs)
        self._pod_phases.clear()

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
        pod_phase = event.pod.status.phase if event.pod.status else None
        self._track_pod_phase(event.event_type, event.pod, pod_phase)

        # Skip ignored phases
        if pod_phase in self.config.ignored_pod_phases:
            return

        attributes = {"pod_monitor.watch_event": event.event_type, "pod.phase": pod_phase or "Unknown"}
        with self._tracer.start_as_current_span("pod_monitor.event", attributes=attributes) as span:
            try:
                app_events = await self._event_mapper.map_pod_event(event.pod, event.event_type)
                for app_event in app_events:
                    await self._producer.produce(event_to_produce=app_event, key=app_event.execution_id)
            except Exception:
                self.logger.error("Error processing pod event", exc_info=True)
                span.set_attribute("pod_monitor.error_type", ErrorType.PROCESSING_ERROR)
                return
            span.set_attribute("pod_monitor.published", len(app_events))

            terminal = any(e.event_type in EXECUTION_TERMINAL_EVENT_TYPES for e in app_events)
            metadata = event.pod.metadata
            if terminal and metadata and metadata.creation_timestamp:
                span.set_attributes(
                    {
                        "pod.lifetime_seconds": (
                            datetime.now(timezone.utc) - metadata.creation_timestamp
                        ).total_seconds(),
                        "pod.language": (metadata.labels or {}).get("language", "unknown"),
                    }
                )

        if terminal:
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

    async def _delete_pod(self, pod: k8s_client.V1Pod) -> None:
        """Delete a pod after its data has been fully extracted.

        Frees its share of the namespace's ResourceQuota.
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
