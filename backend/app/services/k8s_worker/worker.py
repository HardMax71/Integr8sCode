"""KubernetesWorker service - creates pods from execution events"""

import asyncio
import os
import signal
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

from app.config import get_settings
from app.core.logging import logger
from app.core.metrics import Counter, Gauge, Histogram
from app.events.core.consumer import ConsumerConfig, UnifiedConsumer
from app.events.core.producer import UnifiedProducer, get_producer
from app.events.store.event_store import get_event_store
from app.schemas_avro.event_schemas import (
    EventType,
    ExecutionErrorType,
    ExecutionFailedEvent,
    ExecutionStartedEvent,
    PodCreatedEvent,
)
from app.services.idempotency import IdempotentConsumerWrapper
from app.services.k8s_worker.config import K8sWorkerConfig
from app.services.k8s_worker.pod_builder import EventDrivenPodBuilder


class KubernetesWorker:
    """
    Worker service that creates Kubernetes pods from execution events.
    
    This service:
    1. Consumes ExecutionStarted events from Kafka
    2. Creates ConfigMaps with script content
    3. Creates Pods to execute the scripts
    4. Creates NetworkPolicies for security
    5. Publishes PodCreated events
    """

    def __init__(self, config: Optional[K8sWorkerConfig] = None):
        self.config = config or K8sWorkerConfig()
        settings = get_settings()

        # Kafka configuration
        self.kafka_servers = self.config.kafka_bootstrap_servers or settings.KAFKA_BOOTSTRAP_SERVERS

        # Kubernetes clients
        self.v1: Optional[k8s_client.CoreV1Api] = None
        self.networking_v1: Optional[k8s_client.NetworkingV1Api] = None

        # Components
        self.pod_builder = EventDrivenPodBuilder(namespace=self.config.namespace)
        self.consumer: Optional[IdempotentConsumerWrapper] = None
        self.producer: Optional[UnifiedProducer] = None

        # State tracking
        self._running = False
        self._active_creations: Set[str] = set()
        self._creation_semaphore = asyncio.Semaphore(self.config.max_concurrent_pods)

        # Metrics
        self.pods_created = Counter(
            "k8s_worker_pods_created_total",
            "Total pods created",
            ["status", "language"]
        )
        self.pod_creation_duration = Histogram(
            "k8s_worker_pod_creation_duration_seconds",
            "Time taken to create pod",
            ["language"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0]
        )
        self.active_creations_gauge = Gauge(
            "k8s_worker_active_creations",
            "Number of pods being created"
        )
        self.config_maps_created = Counter(
            "k8s_worker_config_maps_created_total",
            "Total config maps created",
            ["status"]
        )
        self.network_policies_created = Counter(
            "k8s_worker_network_policies_created_total",
            "Total network policies created",
            ["status"]
        )

    async def start(self) -> None:
        """Start the Kubernetes worker"""
        if self._running:
            logger.warning("KubernetesWorker already running")
            return

        logger.info("Starting KubernetesWorker service...")

        # Initialize Kubernetes client
        self._initialize_kubernetes_client()

        # Get producer
        self.producer = await get_producer()

        # Create consumer
        consumer_config = ConsumerConfig(
            bootstrap_servers=self.kafka_servers,
            group_id=self.config.consumer_group,
            topics=self.config.topics,
            enable_auto_commit=False
        )

        consumer = UnifiedConsumer(consumer_config)

        # Wrap with idempotency
        self.consumer = IdempotentConsumerWrapper(
            consumer=consumer,
            default_key_strategy="event_based",
            default_ttl_seconds=3600,  # 1 hour
            enable_for_all_handlers=False
        )

        # Subscribe handler with idempotency
        # Use execution_id as idempotency key to prevent duplicate pod creation
        self.consumer.subscribe_idempotent_handler(
            str(EventType.EXECUTION_STARTED),
            self._handle_execution_started,
            key_strategy="custom",
            custom_key_func=lambda e: f"pod_creation:{e.execution_id if hasattr(e, 'execution_id') else 'unknown'}",
            ttl_seconds=3600,
            cache_result=False
        )

        # Start consumer
        await self.consumer.consumer.start()
        self._running = True

        logger.info("KubernetesWorker service started successfully")

    async def stop(self) -> None:
        """Stop the Kubernetes worker"""
        if not self._running:
            return

        logger.info("Stopping KubernetesWorker service...")
        self._running = False

        # Wait for active creations to complete
        if self._active_creations:
            logger.info(f"Waiting for {len(self._active_creations)} active pod creations to complete...")
            timeout = 30
            start_time = time.time()

            while self._active_creations and (time.time() - start_time) < timeout:
                await asyncio.sleep(1)

            if self._active_creations:
                logger.warning(f"Timeout waiting for pod creations, {len(self._active_creations)} still active")

        # Stop consumer
        if self.consumer:
            await self.consumer.stop()

        logger.info("KubernetesWorker service stopped")

    def _initialize_kubernetes_client(self) -> None:
        """Initialize Kubernetes API clients"""
        try:
            # Load config
            if self.config.in_cluster:
                logger.info("Using in-cluster Kubernetes configuration")
                k8s_config.load_incluster_config()
            elif self.config.kubeconfig_path and os.path.exists(self.config.kubeconfig_path):
                logger.info(f"Using kubeconfig from {self.config.kubeconfig_path}")
                k8s_config.load_kube_config(config_file=self.config.kubeconfig_path)
            else:
                # Try default locations
                if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
                    logger.info("Detected in-cluster environment")
                    k8s_config.load_incluster_config()
                else:
                    logger.info("Using default kubeconfig")
                    k8s_config.load_kube_config()

            # Get the default configuration that was set by load_kube_config
            configuration = k8s_client.Configuration.get_default_copy()

            # The certificate data should already be configured by load_kube_config
            # Log the configuration for debugging
            logger.info(f"Kubernetes API host: {configuration.host}")
            logger.info(f"SSL CA cert configured: {configuration.ssl_ca_cert is not None}")

            # Create API clients with the configuration
            api_client = k8s_client.ApiClient(configuration)
            self.v1 = k8s_client.CoreV1Api(api_client)
            self.networking_v1 = k8s_client.NetworkingV1Api(api_client)

            # Test connection
            version = self.v1.get_api_resources()
            logger.info(f"Successfully connected to Kubernetes API, version: {version}")

        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise

    async def _handle_execution_started(
            self,
            event: ExecutionStartedEvent,
            record: Any
    ) -> None:
        """Handle execution started event by creating pod"""
        execution_id = event.execution_id

        # Check if already processing
        if execution_id in self._active_creations:
            logger.warning(f"Already creating pod for execution {execution_id}")
            return

        # Create pod asynchronously
        asyncio.create_task(self._create_pod_for_execution(event))

    async def _create_pod_for_execution(self, event: ExecutionStartedEvent) -> None:
        """Create pod for execution"""
        async with self._creation_semaphore:
            execution_id = event.execution_id
            self._active_creations.add(execution_id)
            self.active_creations_gauge.set(len(self._active_creations))

            start_time = time.time()

            try:
                # Get execution requested event from event store
                event_store = get_event_store()
                if not event_store:
                    raise ValueError("Event store not available")

                requested_events = await event_store.get_execution_events(
                    execution_id,
                    [EventType.EXECUTION_REQUESTED]
                )

                if not requested_events or len(requested_events) == 0:
                    raise ValueError(f"ExecutionRequestedEvent not found for execution {execution_id}")

                requested_event = requested_events[0]

                # Extract script content and runtime info
                if hasattr(requested_event, 'payload') and isinstance(requested_event.payload, dict):
                    script_content = requested_event.payload.get('script')
                    runtime_image = requested_event.payload.get('runtime_image')
                    language = requested_event.payload.get('language')
                    timeout_seconds = requested_event.payload.get('timeout_seconds')
                else:
                    script_content = getattr(requested_event, 'script', None)
                    runtime_image = getattr(requested_event, 'runtime_image', None)
                    language = getattr(requested_event, 'language', None)
                    timeout_seconds = getattr(requested_event, 'timeout_seconds', None)

                if not script_content:
                    raise ValueError(f"Script content not found for execution {execution_id}")

                if not runtime_image:
                    raise ValueError(f"Runtime image not found for execution {execution_id}")

                if not timeout_seconds:
                    raise ValueError(f"Timeout seconds not found for execution {execution_id}")

                # Get entrypoint script
                entrypoint_content = await self._get_entrypoint_script()

                # Parse language from container image
                language, version = self.pod_builder._parse_container_image(runtime_image)

                # Create ConfigMap
                config_map = self.pod_builder.build_config_map(
                    execution_id=execution_id,
                    script_content=script_content,
                    entrypoint_content=entrypoint_content,
                    language=language
                )

                await self._create_config_map(config_map)

                # Build pod configuration
                pod_config = {
                    "execution_id": execution_id,
                    "timeout_seconds": timeout_seconds,  # Use timeout from requested event
                    "container_image": runtime_image,  # Pass runtime image
                    "file_extension": self._get_file_extension(language),
                    "default_cpu_request": self.config.default_cpu_request,
                    "default_memory_request": self.config.default_memory_request,
                    "enable_security_context": self.config.enable_security_context,
                    "run_as_non_root": self.config.run_as_non_root,
                    "read_only_root_filesystem": self.config.read_only_root_filesystem,
                }

                # Create Pod
                pod = self.pod_builder.build_pod_manifest(
                    event=event,
                    script_content=script_content,
                    config=pod_config
                )

                await self._create_pod(pod)

                # Create NetworkPolicy if enabled
                if self.config.enable_network_policies:
                    network_policy = self.pod_builder.build_network_policy(
                        execution_id=execution_id,
                        pod_name=event.pod_name,
                        allow_egress=True
                    )
                    await self._create_network_policy(network_policy)

                # Publish PodCreated event
                await self._publish_pod_created(event, pod)

                # Update metrics
                duration = time.time() - start_time
                self.pod_creation_duration.labels(language=language).observe(duration)
                self.pods_created.labels(status="success", language=language).inc()

                logger.info(
                    f"Successfully created pod {event.pod_name} for execution {execution_id}. "
                    f"Duration: {duration:.2f}s"
                )

            except Exception as e:
                logger.error(
                    f"Failed to create pod for execution {execution_id}: {e}",
                    exc_info=True
                )

                # Update metrics
                self.pods_created.labels(status="failed", language="unknown").inc()

                # Publish failure event
                await self._publish_pod_creation_failed(event, str(e))

            finally:
                self._active_creations.discard(execution_id)
                self.active_creations_gauge.set(len(self._active_creations))

    async def _get_script_content(self, execution_id: str) -> Optional[str]:
        """Get script content from event store"""
        event_store = get_event_store()
        if not event_store:
            logger.error("Event store not available")
            return None

        # Get execution requested event
        try:
            events = await event_store.get_execution_events(
                execution_id,
                [EventType.EXECUTION_REQUESTED]
            )

            if events and len(events) > 0:
                event = events[0]
                if hasattr(event, 'payload') and isinstance(event.payload, dict):
                    return event.payload.get('script')
                elif hasattr(event, 'script'):
                    return str(event.script)

            logger.error(f"No ExecutionRequestedEvent found for execution {execution_id}")
            return None
        except Exception as e:
            logger.error(f"Error retrieving script content: {e}")
            return None

    async def _get_entrypoint_script(self) -> str:
        """Get entrypoint script content"""
        entrypoint_path = Path("app/scripts/entrypoint.sh")
        if entrypoint_path.exists():
            return await asyncio.to_thread(entrypoint_path.read_text)

        # Default entrypoint if file not found
        return """#!/bin/bash
set -e

# Set up output directory
OUTPUT_DIR="${OUTPUT_PATH:-/output}"
mkdir -p "$OUTPUT_DIR"

# Redirect output
exec > >(tee -a "$OUTPUT_DIR/stdout.log")
exec 2> >(tee -a "$OUTPUT_DIR/stderr.log" >&2)

# Execute the script
cd /script
exec "$@"
"""

    async def _create_config_map(self, config_map: k8s_client.V1ConfigMap) -> None:
        """Create ConfigMap in Kubernetes"""
        if not self.v1:
            raise RuntimeError("Kubernetes client not initialized")
        try:
            await asyncio.to_thread(
                self.v1.create_namespaced_config_map,
                namespace=self.config.namespace,
                body=config_map
            )
            self.config_maps_created.labels(status="success").inc()
            logger.debug(f"Created ConfigMap {config_map.metadata.name}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                logger.warning(f"ConfigMap {config_map.metadata.name} already exists")
                self.config_maps_created.labels(status="already_exists").inc()
            else:
                self.config_maps_created.labels(status="failed").inc()
                raise

    async def _create_pod(self, pod: k8s_client.V1Pod) -> None:
        """Create Pod in Kubernetes"""
        if not self.v1:
            raise RuntimeError("Kubernetes client not initialized")
        try:
            await asyncio.to_thread(
                self.v1.create_namespaced_pod,
                namespace=self.config.namespace,
                body=pod
            )
            logger.debug(f"Created Pod {pod.metadata.name}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                logger.warning(f"Pod {pod.metadata.name} already exists")
            else:
                raise

    async def _create_network_policy(self, policy: k8s_client.V1NetworkPolicy) -> None:
        """Create NetworkPolicy in Kubernetes"""
        if not self.networking_v1:
            raise RuntimeError("Kubernetes networking client not initialized")
        try:
            await asyncio.to_thread(
                self.networking_v1.create_namespaced_network_policy,
                namespace=self.config.namespace,
                body=policy
            )
            self.network_policies_created.labels(status="success").inc()
            logger.debug(f"Created NetworkPolicy {policy.metadata.name}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                logger.warning(f"NetworkPolicy {policy.metadata.name} already exists")
                self.network_policies_created.labels(status="already_exists").inc()
            else:
                self.network_policies_created.labels(status="failed").inc()
                # Don't fail pod creation if network policy fails
                logger.error(f"Failed to create NetworkPolicy: {e}")

    async def _publish_pod_created(
            self,
            execution_event: ExecutionStartedEvent,
            pod: k8s_client.V1Pod
    ) -> None:
        """Publish pod created event"""
        event = PodCreatedEvent(
            execution_id=execution_event.execution_id,
            pod_name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            metadata=execution_event.metadata
        )

        if not self.producer:
            logger.error("Producer not initialized")
            return
        await self.producer.send_event(event, EventType.POD_CREATED)

    async def _publish_pod_creation_failed(
            self,
            execution_event: ExecutionStartedEvent,
            error: str
    ) -> None:
        """Publish pod creation failed event"""
        event = ExecutionFailedEvent(
            execution_id=execution_event.execution_id,
            error_type=ExecutionErrorType.SYSTEM_ERROR,
            error=f"Failed to create pod: {error}",
            exit_code=None,
            output=None,
            metadata=execution_event.metadata
        )

        if not self.producer:
            logger.error("Producer not initialized")
            return
        await self.producer.send_event(event, EventType.EXECUTION_FAILED)

    def _get_file_extension(self, language: str) -> str:
        """Get file extension for language"""
        extensions = {
            "python": ".py",
            "javascript": ".js",
            "go": ".go",
            "rust": ".rs",
            "java": ".java",
            "cpp": ".cpp",
            "r": ".r"
        }
        return extensions.get(language.lower(), ".txt")

    async def get_status(self) -> Dict[str, Any]:
        """Get worker status"""
        return {
            "running": self._running,
            "active_creations": len(self._active_creations),
            "config": {
                "namespace": self.config.namespace,
                "max_concurrent_pods": self.config.max_concurrent_pods,
                "enable_network_policies": self.config.enable_network_policies
            }
        }


async def run_kubernetes_worker() -> None:
    """Run the Kubernetes worker service"""
    from app.config import get_settings
    from app.db.mongodb import DatabaseManager
    from app.events.store.event_store import EventStore, set_event_store
    from app.services.idempotency.idempotency_manager import IdempotencyManagerSingleton

    # Initialize database and idempotency manager
    logger.info("Initializing database connection...")
    settings = get_settings()
    db_manager = DatabaseManager(settings)
    await db_manager.connect_to_database()

    logger.info("Initializing idempotency manager...")
    await IdempotencyManagerSingleton.get_instance(db_manager)

    logger.info("Initializing event store...")
    if db_manager.db is None:
        raise RuntimeError("Database connection not established")
    event_store = EventStore(db_manager.db)
    await event_store.initialize()
    set_event_store(event_store)

    config = K8sWorkerConfig()
    worker = KubernetesWorker(config)

    # Setup signal handlers
    def signal_handler(sig: int, frame: Any) -> None:
        logger.info(f"Received signal {sig}, initiating shutdown...")
        asyncio.create_task(worker.stop())

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        await worker.start()

        # Keep running until stopped
        while worker._running:
            await asyncio.sleep(60)

            # Log status periodically
            status = await worker.get_status()
            logger.info(f"Kubernetes worker status: {status}")

    except Exception as e:
        logger.error(f"Kubernetes worker error: {e}", exc_info=True)
    finally:
        await worker.stop()
        await IdempotencyManagerSingleton.close_instance()
        await db_manager.close_database_connection()


if __name__ == "__main__":
    # Run worker as standalone service
    asyncio.run(run_kubernetes_worker())
