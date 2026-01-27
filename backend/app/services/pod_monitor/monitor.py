import asyncio
import logging
import time
from dataclasses import dataclass
from enum import auto
from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio import watch as k8s_watch
from kubernetes_asyncio.client.rest import ApiException

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
RECONCILIATION_LOG_INTERVAL: int = 60  # 1 minute


class WatchEventType(StringEnum):
    """Kubernetes watch event types."""

    ADDED = "ADDED"
    MODIFIED = "MODIFIED"
    DELETED = "DELETED"


class MonitorState(StringEnum):
    """Pod monitor states."""

    IDLE = auto()
    RUNNING = auto()
    STOPPING = auto()
    STOPPED = auto()


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


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Result of state reconciliation."""

    missing_pods: set[PodName]
    extra_pods: set[PodName]
    duration_seconds: float
    success: bool
    error: str | None = None


class PodMonitor:
    """
    Monitors Kubernetes pods and publishes lifecycle events.

    This service watches pods with specific labels using the K8s watch API,
    maps Kubernetes events to application events, and publishes them to Kafka.
    Events are stored in the events collection AND published to Kafka via KafkaEventService.

    Lifecycle is managed by DI provider - call start() to begin monitoring, stop() to end.
    """

    def __init__(
        self,
        config: PodMonitorConfig,
        kafka_event_service: KafkaEventService,
        logger: logging.Logger,
        api_client: k8s_client.ApiClient,
        event_mapper: PodEventMapper,
        kubernetes_metrics: KubernetesMetrics,
    ) -> None:
        """Initialize the pod monitor with all required dependencies."""
        self.logger = logger
        self.config = config

        # Kubernetes clients created from ApiClient
        self._v1 = k8s_client.CoreV1Api(api_client)
        self._watch = k8s_watch.Watch()

        # Components (required, no nullability)
        self._event_mapper = event_mapper
        self._kafka_event_service = kafka_event_service

        # State
        self._state = MonitorState.IDLE
        self._tracked_pods: set[PodName] = set()
        self._reconnect_attempts: int = 0
        self._last_resource_version: ResourceVersion | None = None

        # Tasks
        self._watch_task: asyncio.Task[None] | None = None
        self._reconcile_task: asyncio.Task[None] | None = None

        # Metrics
        self._metrics = kubernetes_metrics

        self.logger.info(f"PodMonitor initialized for namespace {config.namespace}")

    @property
    def state(self) -> MonitorState:
        """Get current monitor state."""
        return self._state

    async def start(self) -> None:
        """Start the pod monitor."""
        self.logger.info("Starting PodMonitor service...")

        # Start monitoring
        self._state = MonitorState.RUNNING
        self._watch_task = asyncio.create_task(self._watch_pods())

        # Start reconciliation if enabled
        if self.config.enable_state_reconciliation:
            self._reconcile_task = asyncio.create_task(self._reconciliation_loop())

        self.logger.info("PodMonitor service started successfully")

    async def stop(self) -> None:
        """Stop the pod monitor."""
        self.logger.info("Stopping PodMonitor service...")
        self._state = MonitorState.STOPPING

        # Cancel tasks
        tasks = [t for t in [self._watch_task, self._reconcile_task] if t]
        for task in tasks:
            task.cancel()

        # Wait for cancellation
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # Close watch
        if self._watch:
            self._watch.stop()
            await self._watch.close()

        # Clear state
        self._tracked_pods.clear()
        self._event_mapper.clear_cache()

        self._state = MonitorState.STOPPED
        self.logger.info("PodMonitor service stopped")

    async def _watch_pods(self) -> None:
        """Main watch loop for pods."""
        while self._state == MonitorState.RUNNING:
            try:
                self._reconnect_attempts = 0
                await self._watch_pod_events()

            except ApiException as e:
                match e.status:
                    case 410:  # Gone - resource version too old
                        self.logger.warning("Resource version expired, resetting watch")
                        self._last_resource_version = None
                        self._metrics.record_pod_monitor_watch_error(ErrorType.RESOURCE_VERSION_EXPIRED)
                    case _:
                        self.logger.error(f"API error in watch: {e}")
                        self._metrics.record_pod_monitor_watch_error(ErrorType.API_ERROR)

                await self._handle_watch_error()

            except Exception as e:
                self.logger.error(f"Unexpected error in watch: {e}", exc_info=True)
                self._metrics.record_pod_monitor_watch_error(ErrorType.UNEXPECTED)
                await self._handle_watch_error()

    async def _watch_pod_events(self) -> None:
        """Watch for pod events."""
        context = WatchContext(
            namespace=self.config.namespace,
            label_selector=self.config.label_selector,
            field_selector=self.config.field_selector,
            timeout_seconds=self.config.watch_timeout_seconds,
            resource_version=self._last_resource_version,
        )

        self.logger.info(f"Starting pod watch with selector: {context.label_selector}, namespace: {context.namespace}")

        # Create watch stream kwargs
        kwargs: dict[str, Any] = {
            "namespace": context.namespace,
            "label_selector": context.label_selector,
            "timeout_seconds": context.timeout_seconds,
        }

        if context.field_selector:
            kwargs["field_selector"] = context.field_selector

        if context.resource_version:
            kwargs["resource_version"] = context.resource_version

        # Watch stream - kubernetes_asyncio Watch is an async iterator
        async for event in self._watch.stream(self._v1.list_namespaced_pod, **kwargs):
            if self._state != MonitorState.RUNNING:
                self._watch.stop()
                break

            await self._process_raw_event(event)

        # Store resource version from watch for next iteration
        if self._watch.resource_version:
            self._last_resource_version = self._watch.resource_version

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
            app_events = await self._event_mapper.map_pod_event(event.pod, event.event_type)

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
                event.metadata.correlation_id = pod.metadata.labels.get("execution-id") or ""

            execution_id = getattr(event, "execution_id", None) or event.aggregate_id
            key = str(execution_id or (pod.metadata.name if pod.metadata else "unknown"))

            await self._kafka_event_service.publish_domain_event(event=event, key=key)

            phase = pod.status.phase if pod.status else "Unknown"
            self._metrics.record_pod_monitor_event_published(event.event_type, phase)

        except Exception as e:
            self.logger.error(f"Error publishing event: {e}", exc_info=True)

    async def _handle_watch_error(self) -> None:
        """Handle watch errors with exponential backoff."""
        self._reconnect_attempts += 1

        if self._reconnect_attempts > self.config.max_reconnect_attempts:
            self.logger.error(
                f"Max reconnect attempts ({self.config.max_reconnect_attempts}) exceeded, stopping pod monitor"
            )
            self._state = MonitorState.STOPPING
            return

        # Calculate exponential backoff
        backoff = min(self.config.watch_reconnect_delay * (2 ** (self._reconnect_attempts - 1)), MAX_BACKOFF_SECONDS)

        self.logger.info(
            f"Reconnecting watch in {backoff}s "
            f"(attempt {self._reconnect_attempts}/{self.config.max_reconnect_attempts})"
        )

        self._metrics.increment_pod_monitor_watch_reconnects()
        await asyncio.sleep(backoff)

    async def _reconciliation_loop(self) -> None:
        """Periodically reconcile state with Kubernetes."""
        while self._state == MonitorState.RUNNING:
            try:
                await asyncio.sleep(self.config.reconcile_interval_seconds)

                if self._state == MonitorState.RUNNING:
                    result = await self._reconcile_state()
                    self._log_reconciliation_result(result)

            except Exception as e:
                self.logger.error(f"Error in reconciliation loop: {e}", exc_info=True)

    async def _reconcile_state(self) -> ReconciliationResult:
        """Reconcile tracked pods with actual state."""
        start_time = time.time()

        try:
            self.logger.info("Starting pod state reconciliation")

            # List all pods matching selector
            pods = await self._v1.list_namespaced_pod(
                namespace=self.config.namespace, label_selector=self.config.label_selector
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

            return ReconciliationResult(
                missing_pods=missing_pods, extra_pods=extra_pods, duration_seconds=duration, success=True
            )

        except Exception as e:
            self.logger.error(f"Failed to reconcile state: {e}", exc_info=True)
            self._metrics.record_pod_monitor_reconciliation_run("failed")

            return ReconciliationResult(
                missing_pods=set(),
                extra_pods=set(),
                duration_seconds=time.time() - start_time,
                success=False,
                error=str(e),
            )

    def _log_reconciliation_result(self, result: ReconciliationResult) -> None:
        """Log reconciliation result."""
        if result.success:
            self.logger.info(
                f"Reconciliation completed in {result.duration_seconds:.2f}s. "
                f"Found {len(result.missing_pods)} missing, "
                f"{len(result.extra_pods)} extra pods"
            )
        else:
            self.logger.error(f"Reconciliation failed after {result.duration_seconds:.2f}s: {result.error}")

    async def get_status(self) -> StatusDict:
        """Get monitor status."""
        return {
            "state": self._state,
            "tracked_pods": len(self._tracked_pods),
            "reconnect_attempts": self._reconnect_attempts,
            "last_resource_version": self._last_resource_version,
            "config": {
                "namespace": self.config.namespace,
                "label_selector": self.config.label_selector,
                "enable_reconciliation": self.config.enable_state_reconciliation,
            },
        }
