"""Pod Monitor - stateless event handler.

Monitors Kubernetes pods and publishes lifecycle events. Receives events,
processes them, and publishes results. No lifecycle management.
All state is stored in Redis via PodStateRepository.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any

from kubernetes import client as k8s_client

from app.core.metrics import KubernetesMetrics
from app.core.utils import StringEnum
from app.db.repositories.redis.pod_state_repository import PodStateRepository
from app.domain.events.typed import DomainEvent
from app.events.core import UnifiedProducer
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper


class WatchEventType(StringEnum):
    """Kubernetes watch event types."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


class ErrorType(StringEnum):
    """Error types for metrics."""

    RESOURCE_VERSION_EXPIRED = "resource_version_expired"
    API_ERROR = "api_error"
    UNEXPECTED = "unexpected"
    PROCESSING_ERROR = "processing_error"


@dataclass(frozen=True, slots=True)
class PodEvent:
    """Immutable pod event data."""

    event_type: WatchEventType
    pod: k8s_client.V1Pod
    resource_version: str | None


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Result of state reconciliation."""

    missing_pods: set[str]
    extra_pods: set[str]
    duration_seconds: float
    success: bool
    error: str | None = None


class PodMonitor:
    """Stateless pod monitor - pure event handler.

    No lifecycle methods (start/stop) - receives ready-to-use dependencies from DI.
    All state (tracked pods, resource version) stored in Redis via PodStateRepository.

    Worker entrypoint handles the watch loop:
        watch = Watch()
        for event in watch.stream(...):
            await monitor.handle_raw_event(event)
    """

    def __init__(
        self,
        config: PodMonitorConfig,
        producer: UnifiedProducer,
        pod_state_repo: PodStateRepository,
        v1_client: k8s_client.CoreV1Api,
        event_mapper: PodEventMapper,
        logger: logging.Logger,
        kubernetes_metrics: KubernetesMetrics,
    ) -> None:
        self._config = config
        self._producer = producer
        self._pod_state_repo = pod_state_repo
        self._v1 = v1_client
        self._event_mapper = event_mapper
        self._logger = logger
        self._metrics = kubernetes_metrics

    async def handle_raw_event(self, raw_event: dict[str, Any]) -> None:
        """Process a raw Kubernetes watch event.

        Called by worker entrypoint for each event from watch stream.
        """
        try:
            event = PodEvent(
                event_type=WatchEventType(raw_event["type"].upper()),
                pod=raw_event["object"],
                resource_version=(
                    raw_event["object"].metadata.resource_version
                    if raw_event["object"].metadata
                    else None
                ),
            )

            await self._process_pod_event(event)

        except (KeyError, ValueError) as e:
            self._logger.error(f"Invalid event format: {e}")
            self._metrics.record_pod_monitor_watch_error(ErrorType.PROCESSING_ERROR)

    async def _process_pod_event(self, event: PodEvent) -> None:
        """Process a pod event."""
        start_time = time.time()

        try:
            # Update resource version in Redis
            if event.resource_version:
                await self._pod_state_repo.set_resource_version(event.resource_version)

            # Skip ignored phases
            pod_phase = event.pod.status.phase if event.pod.status else None
            if pod_phase in self._config.ignored_pod_phases:
                return

            # Get pod info
            pod_name = event.pod.metadata.name
            execution_id = (
                event.pod.metadata.labels.get("execution-id")
                if event.pod.metadata and event.pod.metadata.labels
                else None
            )

            # Update tracked pods in Redis
            match event.event_type:
                case WatchEventType.ADDED | WatchEventType.MODIFIED:
                    if execution_id:
                        await self._pod_state_repo.track_pod(
                            pod_name=pod_name,
                            execution_id=execution_id,
                            status=pod_phase or "Unknown",
                        )
                case WatchEventType.DELETED:
                    await self._pod_state_repo.untrack_pod(pod_name)

            # Update metrics
            tracked_count = await self._pod_state_repo.get_tracked_pods_count()
            self._metrics.update_pod_monitor_pods_watched(tracked_count)

            # Map to application events
            app_events = self._event_mapper.map_pod_event(event.pod, event.event_type)

            # Publish events
            for app_event in app_events:
                await self._publish_event(app_event, event.pod)

            # Log event
            if app_events:
                self._logger.info(
                    f"Processed {event.event_type} event for pod {pod_name} "
                    f"(phase: {pod_phase or 'Unknown'}), "
                    f"published {len(app_events)} events"
                )

            # Update metrics
            duration = time.time() - start_time
            self._metrics.record_pod_monitor_event_processing_duration(duration, event.event_type)

        except Exception as e:
            self._logger.error(f"Error processing pod event: {e}", exc_info=True)
            self._metrics.record_pod_monitor_watch_error(ErrorType.PROCESSING_ERROR)

    async def _publish_event(self, event: DomainEvent, pod: k8s_client.V1Pod) -> None:
        """Publish event to Kafka."""
        try:
            # Add correlation ID from pod labels
            if pod.metadata and pod.metadata.labels:
                event.metadata.correlation_id = pod.metadata.labels.get("execution-id")

            execution_id = getattr(event, "execution_id", None) or event.aggregate_id
            key = str(execution_id or (pod.metadata.name if pod.metadata else "unknown"))

            await self._producer.produce(event_to_produce=event, key=key)

            phase = pod.status.phase if pod.status else "Unknown"
            self._metrics.record_pod_monitor_event_published(event.event_type, phase)

        except Exception as e:
            self._logger.error(f"Error publishing event: {e}", exc_info=True)

    async def reconcile_state(self) -> ReconciliationResult:
        """Reconcile tracked pods with actual Kubernetes state.

        Should be called periodically from worker entrypoint if reconciliation
        is enabled in config.
        """
        start_time = time.time()

        try:
            self._logger.info("Starting pod state reconciliation")

            # List all pods matching selector
            pods = await asyncio.to_thread(
                self._v1.list_namespaced_pod,
                namespace=self._config.namespace,
                label_selector=self._config.label_selector,
            )

            # Get current pod names from K8s
            current_pods = {pod.metadata.name for pod in pods.items}

            # Get tracked pods from Redis
            tracked_pods = await self._pod_state_repo.get_tracked_pod_names()

            # Find differences
            missing_pods = current_pods - tracked_pods
            extra_pods = tracked_pods - current_pods

            # Process missing pods (add them to tracking)
            for pod in pods.items:
                if pod.metadata.name in missing_pods:
                    self._logger.info(f"Reconciling missing pod: {pod.metadata.name}")
                    event = PodEvent(
                        event_type=WatchEventType.ADDED,
                        pod=pod,
                        resource_version=pod.metadata.resource_version,
                    )
                    await self._process_pod_event(event)

            # Remove stale pods from Redis
            for pod_name in extra_pods:
                self._logger.info(f"Removing stale pod from tracking: {pod_name}")
                await self._pod_state_repo.untrack_pod(pod_name)

            # Update metrics
            tracked_count = await self._pod_state_repo.get_tracked_pods_count()
            self._metrics.update_pod_monitor_pods_watched(tracked_count)
            self._metrics.record_pod_monitor_reconciliation_run("success")

            duration = time.time() - start_time

            return ReconciliationResult(
                missing_pods=missing_pods,
                extra_pods=extra_pods,
                duration_seconds=duration,
                success=True,
            )

        except Exception as e:
            self._logger.error(f"Failed to reconcile state: {e}", exc_info=True)
            self._metrics.record_pod_monitor_reconciliation_run("failed")

            return ReconciliationResult(
                missing_pods=set(),
                extra_pods=set(),
                duration_seconds=time.time() - start_time,
                success=False,
                error=str(e),
            )
