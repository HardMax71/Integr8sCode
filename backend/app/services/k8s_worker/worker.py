import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException

from app.core.lifecycle import LifecycleEnabled
from app.core.metrics import ExecutionMetrics, KubernetesMetrics
from app.domain.enums.events import EventType
from app.domain.enums.kafka import KafkaTopic
from app.domain.enums.storage import ExecutionErrorType
from app.events.core import ConsumerConfig, EventDispatcher, UnifiedConsumer, UnifiedProducer
from app.events.event_store import EventStore
from app.events.schema.schema_registry import (
    SchemaRegistryManager,
)
from app.infrastructure.kafka.events.base import BaseEvent
from app.infrastructure.kafka.events.execution import (
    ExecutionFailedEvent,
    ExecutionStartedEvent,
)
from app.infrastructure.kafka.events.pod import PodCreatedEvent
from app.infrastructure.kafka.events.saga import CreatePodCommandEvent, DeletePodCommandEvent
from app.runtime_registry import RUNTIME_REGISTRY
from app.services.idempotency import IdempotencyManager
from app.services.idempotency.middleware import IdempotentConsumerWrapper
from app.services.k8s_worker.config import K8sWorkerConfig
from app.services.k8s_worker.pod_builder import PodBuilder
from app.settings import Settings


class KubernetesWorker(LifecycleEnabled):
    """
    Worker service that creates Kubernetes pods from execution events.

    This service:
    1. Consumes ExecutionStarted events from Kafka
    2. Creates ConfigMaps with script content
    3. Creates Pods to execute the scripts
    4. Creates NetworkPolicies for security
    5. Publishes PodCreated events
    """

    def __init__(
        self,
        config: K8sWorkerConfig,
        producer: UnifiedProducer,
        schema_registry_manager: SchemaRegistryManager,
        settings: Settings,
        event_store: EventStore,
        idempotency_manager: IdempotencyManager,
        logger: logging.Logger,
    ):
        super().__init__()
        self.logger = logger
        self.metrics = KubernetesMetrics()
        self.execution_metrics = ExecutionMetrics()
        self.config = config or K8sWorkerConfig()
        self._settings = settings

        self.kafka_servers = self.config.kafka_bootstrap_servers or self._settings.KAFKA_BOOTSTRAP_SERVERS
        self._event_store = event_store

        # Kubernetes clients
        self.v1: k8s_client.CoreV1Api | None = None
        self.networking_v1: k8s_client.NetworkingV1Api | None = None
        self.apps_v1: k8s_client.AppsV1Api | None = None

        # Components
        self.pod_builder = PodBuilder(namespace=self.config.namespace, config=self.config)
        self.consumer: UnifiedConsumer | None = None
        self.idempotent_consumer: IdempotentConsumerWrapper | None = None
        self.idempotency_manager: IdempotencyManager = idempotency_manager
        self.dispatcher: EventDispatcher | None = None
        self.producer: UnifiedProducer = producer

        # State tracking
        self._active_creations: set[str] = set()
        self._creation_semaphore = asyncio.Semaphore(self.config.max_concurrent_pods)
        self._schema_registry_manager = schema_registry_manager

    async def _on_start(self) -> None:
        """Start the Kubernetes worker."""
        self.logger.info("Starting KubernetesWorker service...")
        self.logger.info("DEBUG: About to initialize Kubernetes client")

        if self.config.namespace == "default":
            raise RuntimeError(
                "KubernetesWorker namespace 'default' is forbidden. Set K8S_NAMESPACE to a dedicated namespace."
            )

        # Initialize Kubernetes client
        self._initialize_kubernetes_client()
        self.logger.info("DEBUG: Kubernetes client initialized")

        self.logger.info("Using provided producer")

        self.logger.info("Idempotency manager provided")

        # Create consumer configuration
        consumer_config = ConsumerConfig(
            bootstrap_servers=self.kafka_servers,
            group_id=f"{self.config.consumer_group}.{self._settings.KAFKA_GROUP_SUFFIX}",
            enable_auto_commit=False,
        )

        # Create dispatcher and register handlers for saga commands
        self.dispatcher = EventDispatcher(logger=self.logger)
        self.dispatcher.register_handler(EventType.CREATE_POD_COMMAND, self._handle_create_pod_command_wrapper)
        self.dispatcher.register_handler(EventType.DELETE_POD_COMMAND, self._handle_delete_pod_command_wrapper)

        # Create consumer with dispatcher
        self.consumer = UnifiedConsumer(
            consumer_config,
            event_dispatcher=self.dispatcher,
            schema_registry=self._schema_registry_manager,
            settings=self._settings,
            logger=self.logger,
        )

        # Wrap consumer with idempotency - use content hash for pod commands
        self.idempotent_consumer = IdempotentConsumerWrapper(
            consumer=self.consumer,
            idempotency_manager=self.idempotency_manager,
            dispatcher=self.dispatcher,
            logger=self.logger,
            default_key_strategy="content_hash",  # Hash execution_id + script for deduplication
            default_ttl_seconds=3600,  # 1 hour TTL for pod creation events
            enable_for_all_handlers=True,  # Enable idempotency for all handlers
        )

        # Start the consumer with idempotency - listen to saga commands topic
        await self.idempotent_consumer.start([KafkaTopic.SAGA_COMMANDS])

        # Create daemonset for image pre-pulling
        asyncio.create_task(self.ensure_image_pre_puller_daemonset())
        self.logger.info("Image pre-puller daemonset task scheduled")

        self.logger.info("KubernetesWorker service started successfully")

    async def _on_stop(self) -> None:
        """Stop the Kubernetes worker."""
        self.logger.info("Stopping KubernetesWorker service...")

        # Wait for active creations to complete
        if self._active_creations:
            self.logger.info(f"Waiting for {len(self._active_creations)} active pod creations to complete...")
            timeout = 30
            start_time = time.time()

            while self._active_creations and (time.time() - start_time) < timeout:
                await asyncio.sleep(1)

            if self._active_creations:
                self.logger.warning(f"Timeout waiting for pod creations, {len(self._active_creations)} still active")

        # Stop the consumer (idempotent wrapper only)
        if self.idempotent_consumer:
            await self.idempotent_consumer.stop()

        # Close idempotency manager
        await self.idempotency_manager.close()

        # Note: producer is managed by DI container, not stopped here

        self.logger.info("KubernetesWorker service stopped")

    def _initialize_kubernetes_client(self) -> None:
        """Initialize Kubernetes API clients"""
        try:
            # Load config
            if self.config.in_cluster:
                self.logger.info("Using in-cluster Kubernetes configuration")
                k8s_config.load_incluster_config()
            elif self.config.kubeconfig_path and os.path.exists(self.config.kubeconfig_path):
                self.logger.info(f"Using kubeconfig from {self.config.kubeconfig_path}")
                k8s_config.load_kube_config(config_file=self.config.kubeconfig_path)
            else:
                # Try default locations
                if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
                    self.logger.info("Detected in-cluster environment")
                    k8s_config.load_incluster_config()
                else:
                    self.logger.info("Using default kubeconfig")
                    k8s_config.load_kube_config()

            # Get the default configuration that was set by load_kube_config
            configuration = k8s_client.Configuration.get_default_copy()

            # The certificate data should already be configured by load_kube_config
            # Log the configuration for debugging
            self.logger.info(f"Kubernetes API host: {configuration.host}")
            self.logger.info(f"SSL CA cert configured: {configuration.ssl_ca_cert is not None}")

            # Create API clients with the configuration
            api_client = k8s_client.ApiClient(configuration)
            self.v1 = k8s_client.CoreV1Api(api_client)
            self.networking_v1 = k8s_client.NetworkingV1Api(api_client)
            self.apps_v1 = k8s_client.AppsV1Api(api_client)

            # Test connection with namespace-scoped operation
            _ = self.v1.list_namespaced_pod(namespace=self.config.namespace, limit=1)
            self.logger.info(f"Successfully connected to Kubernetes API, namespace {self.config.namespace} accessible")

        except Exception as e:
            self.logger.error(f"Failed to initialize Kubernetes client: {e}")
            raise

    async def _handle_create_pod_command_wrapper(self, event: BaseEvent) -> None:
        """Wrapper for handling CreatePodCommandEvent with type safety."""
        assert isinstance(event, CreatePodCommandEvent)
        self.logger.info(f"Processing create_pod_command for execution {event.execution_id} from saga {event.saga_id}")
        await self._handle_create_pod_command(event)

    async def _handle_delete_pod_command_wrapper(self, event: BaseEvent) -> None:
        """Wrapper for handling DeletePodCommandEvent."""
        assert isinstance(event, DeletePodCommandEvent)
        self.logger.info(f"Processing delete_pod_command for execution {event.execution_id} from saga {event.saga_id}")
        await self._handle_delete_pod_command(event)

    async def _handle_create_pod_command(self, command: CreatePodCommandEvent) -> None:
        """Handle create pod command from saga orchestrator"""
        execution_id = command.execution_id

        # Check if already processing
        if execution_id in self._active_creations:
            self.logger.warning(f"Already creating pod for execution {execution_id}")
            return

        # Create pod asynchronously
        asyncio.create_task(self._create_pod_for_execution(command))

    async def _handle_delete_pod_command(self, command: DeletePodCommandEvent) -> None:
        """Handle delete pod command from saga orchestrator (compensation)"""
        execution_id = command.execution_id
        self.logger.info(f"Deleting pod for execution {execution_id} due to: {command.reason}")

        try:
            # Delete the pod
            pod_name = f"executor-{execution_id}"
            if self.v1:
                await asyncio.to_thread(
                    self.v1.delete_namespaced_pod,
                    name=pod_name,
                    namespace=self.config.namespace,
                    grace_period_seconds=30,
                )
                self.logger.info(f"Successfully deleted pod {pod_name}")

            # Delete associated ConfigMap
            configmap_name = f"script-{execution_id}"
            if self.v1:
                await asyncio.to_thread(
                    self.v1.delete_namespaced_config_map, name=configmap_name, namespace=self.config.namespace
                )
                self.logger.info(f"Successfully deleted ConfigMap {configmap_name}")

            # NetworkPolicy cleanup is managed via a static cluster policy; no per-execution NP deletion

        except ApiException as e:
            if e.status == 404:
                self.logger.warning(f"Resources for execution {execution_id} not found (may have already been deleted)")
            else:
                self.logger.error(f"Failed to delete resources for execution {execution_id}: {e}")

    async def _create_pod_for_execution(self, command: CreatePodCommandEvent) -> None:
        """Create pod for execution"""
        async with self._creation_semaphore:
            execution_id = command.execution_id
            self._active_creations.add(execution_id)
            self.metrics.update_k8s_active_creations(len(self._active_creations))

            # Queue depth is owned by the coordinator; do not modify here

            start_time = time.time()

            try:
                # We now have the CreatePodCommandEvent directly from saga
                script_content = command.script
                entrypoint_content = await self._get_entrypoint_script()

                # Create ConfigMap
                config_map = self.pod_builder.build_config_map(
                    command=command, script_content=script_content, entrypoint_content=entrypoint_content
                )

                await self._create_config_map(config_map)

                pod = self.pod_builder.build_pod_manifest(command=command)
                await self._create_pod(pod)

                # Publish PodCreated event
                await self._publish_pod_created(command, pod)

                # Update metrics
                duration = time.time() - start_time
                self.metrics.record_k8s_pod_creation_duration(duration, command.language)
                self.metrics.record_k8s_pod_created("success", command.language)

                self.logger.info(
                    f"Successfully created pod {pod.metadata.name} for execution {execution_id}. "
                    f"Duration: {duration:.2f}s"
                )

            except Exception as e:
                self.logger.error(f"Failed to create pod for execution {execution_id}: {e}", exc_info=True)

                # Update metrics
                self.metrics.record_k8s_pod_created("failed", "unknown")

                # Publish failure event
                await self._publish_pod_creation_failed(command, str(e))

            finally:
                self._active_creations.discard(execution_id)
                self.metrics.update_k8s_active_creations(len(self._active_creations))

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
                self.v1.create_namespaced_config_map, namespace=self.config.namespace, body=config_map
            )
            self.metrics.record_k8s_config_map_created("success")
            self.logger.debug(f"Created ConfigMap {config_map.metadata.name}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                self.logger.warning(f"ConfigMap {config_map.metadata.name} already exists")
                self.metrics.record_k8s_config_map_created("already_exists")
            else:
                self.metrics.record_k8s_config_map_created("failed")
                raise

    async def _create_pod(self, pod: k8s_client.V1Pod) -> None:
        """Create Pod in Kubernetes"""
        if not self.v1:
            raise RuntimeError("Kubernetes client not initialized")
        try:
            await asyncio.to_thread(self.v1.create_namespaced_pod, namespace=self.config.namespace, body=pod)
            self.logger.debug(f"Created Pod {pod.metadata.name}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                self.logger.warning(f"Pod {pod.metadata.name} already exists")
            else:
                raise

    async def _publish_execution_started(self, command: CreatePodCommandEvent, pod: k8s_client.V1Pod) -> None:
        """Publish execution started event"""
        event = ExecutionStartedEvent(
            execution_id=command.execution_id,
            aggregate_id=command.execution_id,  # Set aggregate_id to execution_id
            pod_name=pod.metadata.name,
            node_name=pod.spec.node_name,
            container_id=None,  # Will be set when container actually starts
            metadata=command.metadata,
        )
        if not self.producer:
            self.logger.error("Producer not initialized")
            return
        await self.producer.produce(event_to_produce=event)

    async def _publish_pod_created(self, command: CreatePodCommandEvent, pod: k8s_client.V1Pod) -> None:
        """Publish pod created event"""
        event = PodCreatedEvent(
            execution_id=command.execution_id,
            pod_name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            metadata=command.metadata,
        )

        if not self.producer:
            self.logger.error("Producer not initialized")
            return
        await self.producer.produce(event_to_produce=event)

    async def _publish_pod_creation_failed(self, command: CreatePodCommandEvent, error: str) -> None:
        """Publish pod creation failed event"""
        event = ExecutionFailedEvent(
            execution_id=command.execution_id,
            error_type=ExecutionErrorType.SYSTEM_ERROR,
            exit_code=-1,
            stderr=f"Failed to create pod: {error}",
            resource_usage=None,
            metadata=command.metadata,
            error_message=str(error),
        )

        if not self.producer:
            self.logger.error("Producer not initialized")
            return
        await self.producer.produce(event_to_produce=event)

    async def get_status(self) -> dict[str, Any]:
        """Get worker status"""
        return {
            "running": self.is_running,
            "active_creations": len(self._active_creations),
            "config": {
                "namespace": self.config.namespace,
                "max_concurrent_pods": self.config.max_concurrent_pods,
                "enable_network_policies": True,
            },
        }

    async def ensure_image_pre_puller_daemonset(self) -> None:
        """Ensure the runtime image pre-puller DaemonSet exists"""
        if not self.apps_v1:
            self.logger.warning("Kubernetes AppsV1Api client not initialized. Skipping DaemonSet creation.")
            return

        daemonset_name = "runtime-image-pre-puller"
        namespace = self.config.namespace
        await asyncio.sleep(5)

        try:
            init_containers = []
            all_images = {config.image for lang in RUNTIME_REGISTRY.values() for config in lang.values()}

            for i, image_ref in enumerate(sorted(list(all_images))):
                sanitized_image_ref = image_ref.split("/")[-1].replace(":", "-").replace(".", "-").replace("_", "-")
                self.logger.info(f"DAEMONSET: before: {image_ref} -> {sanitized_image_ref}")
                container_name = f"pull-{i}-{sanitized_image_ref}"
                init_containers.append(
                    {
                        "name": container_name,
                        "image": image_ref,
                        "command": ["/bin/sh", "-c", f'echo "Image {image_ref} pulled."'],
                        "imagePullPolicy": "Always",
                    }
                )

            manifest: dict[str, Any] = {
                "apiVersion": "apps/v1",
                "kind": "DaemonSet",
                "metadata": {"name": daemonset_name, "namespace": namespace},
                "spec": {
                    "selector": {"matchLabels": {"name": daemonset_name}},
                    "template": {
                        "metadata": {"labels": {"name": daemonset_name}},
                        "spec": {
                            "initContainers": init_containers,
                            "containers": [{"name": "pause", "image": "registry.k8s.io/pause:3.9"}],
                            "tolerations": [{"operator": "Exists"}],
                        },
                    },
                    "updateStrategy": {"type": "RollingUpdate"},
                },
            }

            try:
                await asyncio.to_thread(
                    self.apps_v1.read_namespaced_daemon_set, name=daemonset_name, namespace=namespace
                )
                self.logger.info(f"DaemonSet '{daemonset_name}' exists. Replacing to ensure it is up-to-date.")
                await asyncio.to_thread(
                    self.apps_v1.replace_namespaced_daemon_set, name=daemonset_name, namespace=namespace, body=manifest
                )
                self.logger.info(f"DaemonSet '{daemonset_name}' replaced successfully.")
            except ApiException as e:
                if e.status == 404:
                    self.logger.info(f"DaemonSet '{daemonset_name}' not found. Creating...")
                    await asyncio.to_thread(
                        self.apps_v1.create_namespaced_daemon_set, namespace=namespace, body=manifest
                    )
                    self.logger.info(f"DaemonSet '{daemonset_name}' created successfully.")
                else:
                    raise

        except ApiException as e:
            self.logger.error(f"K8s API error applying DaemonSet '{daemonset_name}': {e.reason}", exc_info=True)
        except Exception as e:
            self.logger.error(f"Unexpected error applying image-puller DaemonSet: {e}", exc_info=True)
