import asyncio
import signal
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import auto
from typing import Any, Protocol

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes import watch
from kubernetes.client.rest import ApiException

from app.core.logging import logger
from app.core.metrics.context import get_kubernetes_metrics
from app.core.utils import StringEnum

# Metrics will be passed as parameter to avoid globals
from app.events.core import ProducerConfig, UnifiedProducer
from app.events.schema.schema_registry import create_schema_registry_manager, initialize_event_schemas
from app.infrastructure.kafka.events import BaseEvent
from app.infrastructure.kafka.mappings import get_topic_for_event
from app.services.pod_monitor.config import PodMonitorConfig
from app.services.pod_monitor.event_mapper import PodEventMapper
from app.settings import get_settings

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


class EventPublisher(Protocol):
    """Protocol for event publishing."""

    async def send_event(
            self,
            event: BaseEvent,
            topic: str,
            key: str | None = None
    ) -> bool:
        """Send an event to a topic."""
        ...

    async def is_healthy(self) -> bool:
        """Check if publisher is healthy."""
        ...


class UnifiedProducerAdapter:
    """Adapter to make UnifiedProducer compatible with EventPublisher protocol."""

    def __init__(self, producer: UnifiedProducer) -> None:
        self._producer = producer

    async def send_event(
            self,
            event: BaseEvent,
            topic: str,
            key: str | None = None
    ) -> bool:
        """Send event and return success status."""
        try:
            await self._producer.produce(event_to_produce=event, key=key)
            return True
        except Exception as e:
            logger.error(f"Failed to send event: {e}")
            return False

    async def is_healthy(self) -> bool:
        """Check if producer is healthy."""
        # UnifiedProducer doesn't have is_healthy, assume healthy if initialized
        return self._producer._producer is not None


class PodMonitor:
    """
    Monitors Kubernetes pods and publishes lifecycle events.
    
    This service watches pods with specific labels using the K8s watch API,
    maps Kubernetes events to application events, and publishes them to Kafka.
    """

    def __init__(self, config: PodMonitorConfig, producer: UnifiedProducer) -> None:
        """Initialize the pod monitor."""
        self.config = config or PodMonitorConfig()
        settings = get_settings()

        # Kafka configuration
        self.kafka_servers = (
                self.config.kafka_bootstrap_servers or
                settings.KAFKA_BOOTSTRAP_SERVERS
        )

        # Kubernetes clients (initialized on start)
        self._v1: k8s_client.CoreV1Api | None = None
        self._watch: watch.Watch | None = None

        # Components - producer is required
        self._event_mapper = PodEventMapper()
        self._producer = UnifiedProducerAdapter(producer)

        # State
        self._state = MonitorState.IDLE
        self._tracked_pods: set[PodName] = set()
        self._reconnect_attempts: int = 0
        self._last_resource_version: ResourceVersion | None = None

        # Tasks
        self._watch_task: asyncio.Task[None] | None = None
        self._reconcile_task: asyncio.Task[None] | None = None

        # Metrics
        self._metrics = get_kubernetes_metrics()

    @property
    def state(self) -> MonitorState:
        """Get current monitor state."""
        return self._state

    async def start(self) -> None:
        """Start the pod monitor."""
        if self._state != MonitorState.IDLE:
            logger.warning(f"Cannot start monitor in state: {self._state}")
            return

        logger.info("Starting PodMonitor service...")

        # Initialize components
        self._initialize_kubernetes_client()

        # Start monitoring
        self._state = MonitorState.RUNNING
        self._watch_task = asyncio.create_task(self._watch_pods())

        # Start reconciliation if enabled
        if self.config.enable_state_reconciliation:
            self._reconcile_task = asyncio.create_task(self._reconciliation_loop())

        logger.info("PodMonitor service started successfully")

    async def stop(self) -> None:
        """Stop the pod monitor."""
        if self._state == MonitorState.STOPPED:
            return

        logger.info("Stopping PodMonitor service...")
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

        # Clear state
        self._tracked_pods.clear()
        self._event_mapper.clear_cache()

        self._state = MonitorState.STOPPED
        logger.info("PodMonitor service stopped")

    def _initialize_kubernetes_client(self) -> None:
        """Initialize Kubernetes API clients."""
        try:
            # Load configuration
            match (self.config.in_cluster, self.config.kubeconfig_path):
                case (True, _):
                    logger.info("Using in-cluster Kubernetes configuration")
                    k8s_config.load_incluster_config()
                case (False, path) if path:
                    logger.info(f"Using kubeconfig from {path}")
                    k8s_config.load_kube_config(config_file=path)
                case _:
                    logger.info("Using default kubeconfig")
                    k8s_config.load_kube_config()

            # Get configuration
            configuration = k8s_client.Configuration.get_default_copy()

            # Log configuration
            logger.info(f"Kubernetes API host: {configuration.host}")
            logger.info(f"SSL CA cert configured: {configuration.ssl_ca_cert is not None}")

            # Create API clients
            api_client = k8s_client.ApiClient(configuration)
            self._v1 = k8s_client.CoreV1Api(api_client)
            self._watch = watch.Watch()

            # Test connection
            self._v1.get_api_resources()
            logger.info("Successfully connected to Kubernetes API")
            # Recreate event mapper with k8s API client
            self._event_mapper = PodEventMapper(k8s_api=self._v1)


        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise

    async def _watch_pods(self) -> None:
        """Main watch loop for pods."""
        while self._state == MonitorState.RUNNING:
            try:
                self._reconnect_attempts = 0
                await self._watch_pod_events()

            except ApiException as e:
                match e.status:
                    case 410:  # Gone - resource version too old
                        logger.warning("Resource version expired, resetting watch")
                        self._last_resource_version = None
                        self._metrics.record_pod_monitor_watch_error(
                            str(ErrorType.RESOURCE_VERSION_EXPIRED.value))
                    case _:
                        logger.error(f"API error in watch: {e}")
                        self._metrics.record_pod_monitor_watch_error(str(ErrorType.API_ERROR.value))

                await self._handle_watch_error()

            except Exception as e:
                logger.error(f"Unexpected error in watch: {e}", exc_info=True)
                self._metrics.record_pod_monitor_watch_error(str(ErrorType.UNEXPECTED.value))
                await self._handle_watch_error()

    async def _watch_pod_events(self) -> None:
        """Watch for pod events."""
        # self._v1 and self._watch are guaranteed initialized by start()

        context = WatchContext(
            namespace=self.config.namespace,
            label_selector=self.config.label_selector,
            field_selector=self.config.field_selector,
            timeout_seconds=self.config.watch_timeout_seconds,
            resource_version=self._last_resource_version
        )

        logger.info(
            f"Starting pod watch with selector: {context.label_selector}, "
            f"namespace: {context.namespace}"
        )

        # Create watch stream
        kwargs = {
            "namespace": context.namespace,
            "label_selector": context.label_selector,
            "timeout_seconds": context.timeout_seconds,
        }

        if context.field_selector:
            kwargs["field_selector"] = context.field_selector

        if context.resource_version:
            kwargs["resource_version"] = context.resource_version

        # Watch stream
        if not self._watch or not self._v1:
            raise RuntimeError("Watch or API not initialized")

        stream = self._watch.stream(
            self._v1.list_namespaced_pod,
            **kwargs
        )

        try:
            for event in stream:
                if self._state != MonitorState.RUNNING:
                    break

                await self._process_raw_event(event)

        finally:
            # Store resource version for next watch
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
                event_type=WatchEventType(raw_event['type'].upper()),
                pod=raw_event['object'],
                resource_version=(
                    raw_event['object'].metadata.resource_version
                    if raw_event['object'].metadata
                    else None
                )
            )

            await self._process_pod_event(event)

        except (KeyError, ValueError) as e:
            logger.error(f"Invalid event format: {e}")
            self._metrics.record_pod_monitor_watch_error(str(ErrorType.PROCESSING_ERROR.value))

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
            app_events = self._event_mapper.map_pod_event(
                event.pod,
                event.event_type
            )

            # Publish events
            for app_event in app_events:
                await self._publish_event(app_event, event.pod)

            # Log event
            if app_events:
                logger.info(
                    f"Processed {event.event_type.value} event for pod {pod_name} "
                    f"(phase: {pod_phase or 'Unknown'}), "
                    f"published {len(app_events)} events"
                )

            # Update metrics
            duration = time.time() - start_time
            self._metrics.record_pod_monitor_event_processing_duration(duration, str(event.event_type.value))

        except Exception as e:
            logger.error(f"Error processing pod event: {e}", exc_info=True)
            self._metrics.record_pod_monitor_watch_error(str(ErrorType.PROCESSING_ERROR.value))

    async def _publish_event(
            self,
            event: BaseEvent,
            pod: k8s_client.V1Pod
    ) -> None:
        """Publish event to Kafka."""
        try:
            # Get proper topic from event type mapping

            topic = str(get_topic_for_event(event.event_type))

            # Add correlation ID from pod labels
            if pod.metadata and pod.metadata.labels:
                event.metadata.correlation_id = pod.metadata.labels.get("execution-id")

            # Get execution ID from event if it has one
            execution_id = getattr(event, 'execution_id', None) or event.aggregate_id

            logger.info(
                f"Publishing event {event.event_type} to topic {topic} "
                f"for execution_id: {execution_id}"
            )

            # Check producer health
            if not await self._producer.is_healthy():
                logger.error(f"Producer is not healthy, cannot send event {event.event_type}")
                return

            # Publish event
            key = str(execution_id or pod.metadata.name)
            success = await self._producer.send_event(event=event, topic=topic, key=key)

            if not success:
                logger.error(f"Failed to send event {event.event_type} to topic {topic}")
                return

            # Event published successfully
            phase = pod.status.phase if pod.status else "Unknown"
            self._metrics.record_pod_monitor_event_published(str(event.event_type), phase)
            logger.info(f"Successfully published {event.event_type} event to {topic}")

        except Exception as e:
            logger.error(f"Error publishing event: {e}", exc_info=True)

    async def _handle_watch_error(self) -> None:
        """Handle watch errors with exponential backoff."""
        self._reconnect_attempts += 1

        if self._reconnect_attempts > self.config.max_reconnect_attempts:
            logger.error(
                f"Max reconnect attempts ({self.config.max_reconnect_attempts}) "
                f"exceeded, stopping pod monitor"
            )
            self._state = MonitorState.STOPPING
            return

        # Calculate exponential backoff
        backoff = min(
            self.config.watch_reconnect_delay * (2 ** (self._reconnect_attempts - 1)),
            MAX_BACKOFF_SECONDS
        )

        logger.info(
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
                logger.error(f"Error in reconciliation loop: {e}", exc_info=True)

    async def _reconcile_state(self) -> ReconciliationResult:
        """Reconcile tracked pods with actual state."""
        # self._v1 is guaranteed initialized by start()

        start_time = time.time()

        try:
            logger.info("Starting pod state reconciliation")

            # List all pods matching selector
            if not self._v1:
                logger.warning("K8s API not initialized, skipping reconciliation")
                return ReconciliationResult(
                    missing_pods=set(),
                    extra_pods=set(),
                    duration_seconds=time.time() - start_time,
                    success=False,
                    error="K8s API not initialized"
                )

            pods = await asyncio.to_thread(
                self._v1.list_namespaced_pod,
                namespace=self.config.namespace,
                label_selector=self.config.label_selector
            )

            # Get current pod names
            current_pods = {pod.metadata.name for pod in pods.items}

            # Find differences
            missing_pods = current_pods - self._tracked_pods
            extra_pods = self._tracked_pods - current_pods

            # Process missing pods
            for pod in pods.items:
                if pod.metadata.name in missing_pods:
                    logger.info(f"Reconciling missing pod: {pod.metadata.name}")
                    event = PodEvent(
                        event_type=WatchEventType.ADDED,
                        pod=pod,
                        resource_version=pod.metadata.resource_version
                    )
                    await self._process_pod_event(event)

            # Remove extra pods
            for pod_name in extra_pods:
                logger.info(f"Removing stale pod from tracking: {pod_name}")
                self._tracked_pods.discard(pod_name)

            # Update metrics
            self._metrics.update_pod_monitor_pods_watched(len(self._tracked_pods))
            self._metrics.record_pod_monitor_reconciliation_run("success")

            duration = time.time() - start_time

            return ReconciliationResult(
                missing_pods=missing_pods,
                extra_pods=extra_pods,
                duration_seconds=duration,
                success=True
            )

        except Exception as e:
            logger.error(f"Failed to reconcile state: {e}", exc_info=True)
            self._metrics.record_pod_monitor_reconciliation_run("failed")

            return ReconciliationResult(
                missing_pods=set(),
                extra_pods=set(),
                duration_seconds=time.time() - start_time,
                success=False,
                error=str(e)
            )

    def _log_reconciliation_result(self, result: ReconciliationResult) -> None:
        """Log reconciliation result."""
        if result.success:
            logger.info(
                f"Reconciliation completed in {result.duration_seconds:.2f}s. "
                f"Found {len(result.missing_pods)} missing, "
                f"{len(result.extra_pods)} extra pods"
            )
        else:
            logger.error(
                f"Reconciliation failed after {result.duration_seconds:.2f}s: "
                f"{result.error}"
            )

    async def get_status(self) -> StatusDict:
        """Get monitor status."""
        return {
            "state": self._state.value,
            "tracked_pods": len(self._tracked_pods),
            "reconnect_attempts": self._reconnect_attempts,
            "last_resource_version": self._last_resource_version,
            "config": {
                "namespace": self.config.namespace,
                "label_selector": self.config.label_selector,
                "enable_reconciliation": self.config.enable_state_reconciliation
            }
        }


@asynccontextmanager
async def create_pod_monitor(
        config: PodMonitorConfig,
        producer: UnifiedProducer,
) -> AsyncIterator[PodMonitor]:
    """Create and manage a pod monitor instance."""
    monitor = PodMonitor(config=config, producer=producer)

    try:
        await monitor.start()
        yield monitor
    finally:
        await monitor.stop()


async def run_pod_monitor() -> None:
    """Run the pod monitor service."""
    # Initialize schema registry
    schema_registry_manager = create_schema_registry_manager()
    await initialize_event_schemas(schema_registry_manager)

    # Create producer
    settings = get_settings()
    producer_config = ProducerConfig(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS
    )
    producer = UnifiedProducer(producer_config, schema_registry_manager)
    await producer.start()

    monitor_config = PodMonitorConfig()
    monitor = PodMonitor(config=monitor_config, producer=producer)

    # Setup signal handlers
    loop = asyncio.get_running_loop()

    async def shutdown() -> None:
        """Shutdown handler."""
        logger.info("Initiating graceful shutdown...")
        await monitor.stop()
        await producer.stop()

    # Register signal handlers
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(shutdown()))

    try:
        await monitor.start()

        # Keep running until stopped
        while monitor.state == MonitorState.RUNNING:
            await asyncio.sleep(RECONCILIATION_LOG_INTERVAL)

            # Log status periodically
            status = await monitor.get_status()
            logger.info(f"Pod monitor status: {status}")

    except Exception as e:
        logger.error(f"Pod monitor error: {e}", exc_info=True)
    finally:
        await monitor.stop()
        await producer.stop()


if __name__ == "__main__":
    settings = get_settings()
    asyncio.run(run_pod_monitor())
