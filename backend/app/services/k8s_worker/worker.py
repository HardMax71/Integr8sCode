import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.rest import ApiException

from app.core.metrics import EventMetrics, ExecutionMetrics, KubernetesMetrics
from app.domain.enums.storage import ExecutionErrorType
from app.domain.events.typed import (
    CreatePodCommandEvent,
    DeletePodCommandEvent,
    ExecutionFailedEvent,
    ExecutionStartedEvent,
    PodCreatedEvent,
)
from app.events.core import UnifiedProducer
from app.runtime_registry import RUNTIME_REGISTRY
from app.settings import Settings

from .pod_builder import PodBuilder


class KubernetesWorker:
    """
    Worker service that creates Kubernetes pods from execution events.

    This service:
    1. Handles CreatePodCommand events from saga orchestrator
    2. Creates ConfigMaps with script content
    3. Creates Pods to execute the scripts
    4. Publishes PodCreated events

    Lifecycle is managed by DI - consumer is injected already started.
    """

    def __init__(
            self,
            api_client: k8s_client.ApiClient,
            producer: UnifiedProducer,
            settings: Settings,
            logger: logging.Logger,
            event_metrics: EventMetrics,
    ):
        self._event_metrics = event_metrics
        self.logger = logger
        self.metrics = KubernetesMetrics(settings)
        self.execution_metrics = ExecutionMetrics(settings)
        self._settings = settings

        # Validate namespace
        if self._settings.K8S_NAMESPACE == "default":
            raise ValueError(
                "KubernetesWorker namespace 'default' is forbidden. Set K8S_NAMESPACE to a dedicated namespace."
            )

        # Kubernetes clients created from ApiClient
        self.v1 = k8s_client.CoreV1Api(api_client)
        self.networking_v1 = k8s_client.NetworkingV1Api(api_client)
        self.apps_v1 = k8s_client.AppsV1Api(api_client)

        # Components
        self.pod_builder = PodBuilder(settings=settings)
        self.producer = producer

        # State tracking
        self._active_creations: set[str] = set()
        self._creation_semaphore = asyncio.Semaphore(self._settings.K8S_MAX_CONCURRENT_PODS)

        self.logger.info(f"KubernetesWorker initialized for namespace {self._settings.K8S_NAMESPACE}")

    async def handle_create_pod_command(self, command: CreatePodCommandEvent) -> None:
        """Handle create pod command from saga orchestrator"""
        execution_id = command.execution_id

        # Check if already processing
        if execution_id in self._active_creations:
            self.logger.warning(f"Already creating pod for execution {execution_id}")
            return

        await self._create_pod_for_execution(command)

    async def handle_delete_pod_command(self, command: DeletePodCommandEvent) -> None:
        """Handle delete pod command from saga orchestrator (compensation)"""
        execution_id = command.execution_id
        self.logger.info(f"Deleting pod for execution {execution_id} due to: {command.reason}")

        try:
            # Delete the pod
            pod_name = f"executor-{execution_id}"
            await self.v1.delete_namespaced_pod(
                name=pod_name,
                namespace=self._settings.K8S_NAMESPACE,
                grace_period_seconds=30,
            )
            self.logger.info(f"Successfully deleted pod {pod_name}")

            # Delete associated ConfigMap
            configmap_name = f"script-{execution_id}"
            await self.v1.delete_namespaced_config_map(name=configmap_name, namespace=self._settings.K8S_NAMESPACE)
            self.logger.info(f"Successfully deleted ConfigMap {configmap_name}")

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

            start_time = time.time()

            try:
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
                self.metrics.record_k8s_pod_created("failed", "unknown")
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
        try:
            await self.v1.create_namespaced_config_map(namespace=self._settings.K8S_NAMESPACE, body=config_map)
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
        try:
            await self.v1.create_namespaced_pod(namespace=self._settings.K8S_NAMESPACE, body=pod)
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
            aggregate_id=command.execution_id,
            pod_name=pod.metadata.name,
            node_name=pod.spec.node_name,
            container_id=None,
            metadata=command.metadata,
        )
        await self.producer.produce(event_to_produce=event, key=command.execution_id)

    async def _publish_pod_created(self, command: CreatePodCommandEvent, pod: k8s_client.V1Pod) -> None:
        """Publish pod created event"""
        event = PodCreatedEvent(
            execution_id=command.execution_id,
            pod_name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            metadata=command.metadata,
        )
        await self.producer.produce(event_to_produce=event, key=command.execution_id)

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
        await self.producer.produce(event_to_produce=event, key=command.execution_id)

    async def wait_for_active_creations(self, timeout: float = 30.0) -> None:
        """Wait for active pod creations to complete (for graceful shutdown)."""
        if not self._active_creations:
            return

        self.logger.info(f"Waiting for {len(self._active_creations)} active pod creations to complete...")
        start_time = time.time()

        while self._active_creations and (time.time() - start_time) < timeout:
            await asyncio.sleep(1)

        if self._active_creations:
            self.logger.warning(f"Timeout waiting for pod creations, {len(self._active_creations)} still active")

    async def ensure_image_pre_puller_daemonset(self) -> None:
        """Create or replace the image pre-puller DaemonSet (fire-and-forget).

        The DaemonSet pulls all runtime images onto every node in the background.
        This method returns immediately after the DaemonSet is applied — it does
        NOT wait for images to finish pulling.  In CI, the test-critical image
        (python:3.11-slim) is pre-pulled directly into K3s containerd before the
        stack starts, so execution pods never hit a cold pull.
        """
        daemonset_name = "runtime-image-pre-puller"
        namespace = self._settings.K8S_NAMESPACE

        init_containers = []
        all_images = {config.image for lang in RUNTIME_REGISTRY.values() for config in lang.values()}

        for i, image_ref in enumerate(sorted(list(all_images))):
            sanitized_image_ref = image_ref.split("/")[-1].replace(":", "-").replace(".", "-").replace("_", "-")
            container_name = f"pull-{i}-{sanitized_image_ref}"
            init_containers.append(
                {
                    "name": container_name,
                    "image": image_ref,
                    "command": ["/bin/sh", "-c", f'echo "Image {image_ref} pulled."'],
                    "imagePullPolicy": "Always",
                }
            )

        self.logger.info(f"Pre-pulling {len(all_images)} runtime images via DaemonSet")

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
            await self.apps_v1.read_namespaced_daemon_set(name=daemonset_name, namespace=namespace)
            self.logger.info(f"DaemonSet '{daemonset_name}' exists. Replacing to ensure it is up-to-date.")
            await self.apps_v1.replace_namespaced_daemon_set(
                name=daemonset_name, namespace=namespace, body=manifest  # type: ignore[arg-type]
            )
        except ApiException as e:
            if e.status == 404:
                self.logger.info(f"DaemonSet '{daemonset_name}' not found. Creating...")
                await self.apps_v1.create_namespaced_daemon_set(
                    namespace=namespace, body=manifest  # type: ignore[arg-type]
                )
            else:
                raise

        self.logger.info(f"DaemonSet '{daemonset_name}' applied — images will pull in background")
