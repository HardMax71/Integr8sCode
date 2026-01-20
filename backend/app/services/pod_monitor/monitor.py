import asyncio
import logging
import time
from dataclasses import dataclass
from enum import auto
from typing import Any

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.core.k8s_clients import K8sClients
from app.core.metrics import KubernetesMetrics
from app.core.utils import StringEnum
from app.domain.events.typed import DomainEvent
from app.services.kafka_event_service import KafkaEventService
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper

# Type aliases
type PodName = str
type ResourceVersion = str
type EventType = str
type KubeEvent = dict[str, Any]
type StatusDict = dict[str, Any]

# Constants
MAX_BACKOFF_SECONDS: int = 300  # 5 minutes


class WatchEventType(StringEnum):
    """Kubernetes watch event types."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


class ErrorType(StringEnum):
    """Error types for metrics."""

    RESOURCE_VERSION_EXPIRED = auto()
    API_ERROR = auto()
    UNEXPECTED = auto()
    PROCESSING_ERROR = auto()


@dataclass(frozen=True, slots=True)
class WatchContext:
    """Immutable context for watch operations."""

    namespace: str
    label_selector: str
    field_selector: str | None
    timeout_seconds: int
    resource_version: ResourceVersion | None


@dataclass(frozen=True, slots=True)
class PodEvent:
    """Immutable pod event data."""

    event_type: WatchEventType
    pod: k8s_client.V1Pod
    resource_version: ResourceVersion | None


class PodMonitor:
    """
    Monitors Kubernetes pods and publishes lifecycle events.

    Watches pods with specific labels using the K8s watch API,
    maps Kubernetes events to application events, and publishes them to Kafka.
    Reconciles state when watch restarts (every watch_timeout_seconds or on error).

    Usage:
        monitor = PodMonitor(...)
        await monitor.run()  # Blocks until cancelled
    """

    def __init__(
        self,
        config: PodMonitorConfig,
        kafka_event_service: KafkaEventService,
        logger: logging.Logger,
        k8s_clients: K8sClients,
        event_mapper: PodEventMapper,
        kubernetes_metrics: KubernetesMetrics,
    ) -> None:
        """Store dependencies. All work happens in run()."""
        self.logger = logger
        self.config = config

        # Kubernetes clients
        self._clients = k8s_clients
        self._v1 = k8s_clients.v1
        self._watch = k8s_clients.watch

        # Components
        self._event_mapper = event_mapper
        self._kafka_event_service = kafka_event_service

        # State
        self._tracked_pods: set[PodName] = set()
        self._reconnect_attempts: int = 0
        self._last_resource_version: ResourceVersion | None = None

        # Metrics
        self._metrics = kubernetes_metrics

    async def run(self) -> None:
        """Run the monitor. Blocks until cancelled.

        Verifies K8s connectivity, runs watch loop, cleans up on exit.
        """
        self.logger.info("PodMonitor starting...")

        # Verify K8s connectivity
        await asyncio.to_thread(self._v1.get_api_resources)
        self.logger.info("Successfully connected to Kubernetes API")

        try:
            await self._watch_loop()
        except asyncio.CancelledError:
            self.logger.info("PodMonitor cancelled")
        finally:
            if self._watch:
                self._watch.stop()
            self._tracked_pods.clear()
            self._event_mapper.clear_cache()
            self.logger.info("PodMonitor stopped")

    async def _watch_loop(self) -> None:
        """Main watch loop - reconciles on each restart."""
        while True:
            try:
                # Reconcile before starting watch (catches missed events)
                if self.config.enable_state_reconciliation:
                    await self._reconcile()

                self._reconnect_attempts = 0
                await self._run_watch()

            except ApiException as e:
                if e.status == 410:  # Resource version expired
                    self.logger.warning("Resource version expired, resetting watch")
                    self._last_resource_version = None
                    self._metrics.record_pod_monitor_watch_error(ErrorType.RESOURCE_VERSION_EXPIRED)
                else:
                    self.logger.error(f"API error in watch: {e}")
                    self._metrics.record_pod_monitor_watch_error(ErrorType.API_ERROR)
                await self._backoff()

            except asyncio.CancelledError:
                raise

            except Exception as e:
                self.logger.error(f"Unexpected error in watch: {e}", exc_info=True)
                self._metrics.record_pod_monitor_watch_error(ErrorType.UNEXPECTED)
                await self._backoff()

    async def _run_watch(self) -> None:
        """Run a single watch session."""
        self.logger.info(
            f"Starting pod watch: selector={self.config.label_selector}, namespace={self.config.namespace}"
        )

        kwargs: dict[str, Any] = {
            "namespace": self.config.namespace,
            "label_selector": self.config.label_selector,
            "timeout_seconds": self.config.watch_timeout_seconds,
        }
        if self.config.field_selector:
            kwargs["field_selector"] = self.config.field_selector
        if self._last_resource_version:
            kwargs["resource_version"] = self._last_resource_version

        stream = self._watch.stream(self._v1.list_namespaced_pod, **kwargs)

        try:
            for event in stream:
                await self._process_raw_event(event)
        finally:
            self._update_resource_version(stream)

    def _update_resource_version(self, stream: Any) -> None:
        """Update last resource version from stream."""
        try:
            if stream._stop_event and stream._stop_event.resource_version:
                self._last_resource_version = stream._stop_event.resource_version
        except AttributeError:
            pass

    async def _process_raw_event(self, raw_event: KubeEvent) -> None:
        """Process a raw Kubernetes watch event."""
        try:
            # Parse event
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
            # Update resource version
            if event.resource_version:
                self._last_resource_version = event.resource_version

            # Skip ignored phases
            pod_phase = event.pod.status.phase if event.pod.status else None
            if pod_phase in self.config.ignored_pod_phases:
                return

            # Update tracked pods
            pod_name = event.pod.metadata.name
            match event.event_type:
                case WatchEventType.ADDED | WatchEventType.MODIFIED:
                    self._tracked_pods.add(pod_name)
                case WatchEventType.DELETED:
                    self._tracked_pods.discard(pod_name)

            # Update metrics
            self._metrics.update_pod_monitor_pods_watched(len(self._tracked_pods))

            # Map to application events
            app_events = self._event_mapper.map_pod_event(event.pod, event.event_type)

            # Publish events
            for app_event in app_events:
                await self._publish_event(app_event, event.pod)

            # Log event
            if app_events:
                self.logger.info(
                    f"Processed {event.event_type} event for pod {pod_name} "
                    f"(phase: {pod_phase or 'Unknown'}), "
                    f"published {len(app_events)} events"
                )

            # Update metrics
            duration = time.time() - start_time
            self._metrics.record_pod_monitor_event_processing_duration(duration, event.event_type)

        except Exception as e:
            self.logger.error(f"Error processing pod event: {e}", exc_info=True)
            self._metrics.record_pod_monitor_watch_error(ErrorType.PROCESSING_ERROR)

    async def _publish_event(self, event: DomainEvent, pod: k8s_client.V1Pod) -> None:
        """Publish event to Kafka and store in events collection."""
        try:
            # Add correlation ID from pod labels
            if pod.metadata and pod.metadata.labels:
                event.metadata.correlation_id = pod.metadata.labels.get("execution-id")

            execution_id = getattr(event, "execution_id", None) or event.aggregate_id
            key = str(execution_id or (pod.metadata.name if pod.metadata else "unknown"))

            await self._kafka_event_service.publish_domain_event(event=event, key=key)

            phase = pod.status.phase if pod.status else "Unknown"
            self._metrics.record_pod_monitor_event_published(event.event_type, phase)

        except Exception as e:
            self.logger.error(f"Error publishing event: {e}", exc_info=True)

    async def _backoff(self) -> None:
        """Handle watch errors with exponential backoff."""
        self._reconnect_attempts += 1

        if self._reconnect_attempts > self.config.max_reconnect_attempts:
            self.logger.error(
                f"Max reconnect attempts ({self.config.max_reconnect_attempts}) exceeded"
            )
            raise RuntimeError("Max reconnect attempts exceeded")

        # Calculate exponential backoff
        backoff = min(self.config.watch_reconnect_delay * (2 ** (self._reconnect_attempts - 1)), MAX_BACKOFF_SECONDS)

        self.logger.info(
            f"Reconnecting watch in {backoff}s "
            f"(attempt {self._reconnect_attempts}/{self.config.max_reconnect_attempts})"
        )

        self._metrics.increment_pod_monitor_watch_reconnects()
        await asyncio.sleep(backoff)

    async def _reconcile(self) -> None:
        """Reconcile tracked pods with actual state."""
        start_time = time.time()

        try:
            self.logger.info("Starting pod state reconciliation")

            # List all pods matching selector
            pods = await asyncio.to_thread(
                self._v1.list_namespaced_pod, namespace=self.config.namespace, label_selector=self.config.label_selector
            )

            # Get current pod names
            current_pods = {pod.metadata.name for pod in pods.items}

            # Find differences
            missing_pods = current_pods - self._tracked_pods
            extra_pods = self._tracked_pods - current_pods

            # Process missing pods
            for pod in pods.items:
                if pod.metadata.name in missing_pods:
                    self.logger.info(f"Reconciling missing pod: {pod.metadata.name}")
                    event = PodEvent(
                        event_type=WatchEventType.ADDED, pod=pod, resource_version=pod.metadata.resource_version
                    )
                    await self._process_pod_event(event)

            # Remove extra pods
            for pod_name in extra_pods:
                self.logger.info(f"Removing stale pod from tracking: {pod_name}")
                self._tracked_pods.discard(pod_name)

            # Update metrics
            self._metrics.update_pod_monitor_pods_watched(len(self._tracked_pods))
            self._metrics.record_pod_monitor_reconciliation_run("success")

            duration = time.time() - start_time
            self.logger.info(
                f"Reconciliation completed in {duration:.2f}s. "
                f"Found {len(missing_pods)} missing, {len(extra_pods)} extra pods"
            )

        except Exception as e:
            self.logger.error(f"Failed to reconcile state: {e}", exc_info=True)
            self._metrics.record_pod_monitor_reconciliation_run("failed")

    async def get_status(self) -> StatusDict:
        """Get monitor status."""
        return {
            "tracked_pods": len(self._tracked_pods),
            "reconnect_attempts": self._reconnect_attempts,
            "last_resource_version": self._last_resource_version,
            "config": {
                "namespace": self.config.namespace,
                "label_selector": self.config.label_selector,
                "enable_reconciliation": self.config.enable_state_reconciliation,
            },
        }
