import asyncio
import logging
import time
from pathlib import Path
from typing import Any

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

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
from app.services.k8s_worker.config import K8sWorkerConfig
from app.services.k8s_worker.pod_builder import PodBuilder
from app.settings import Settings


class K8sWorkerLogic:
    """
    Business logic for Kubernetes pod management.

    Handles:
    - Pod creation from command events
    - Pod deletion (compensation)
    - Image pre-puller daemonset management
    - Event publishing (PodCreated, ExecutionFailed)

    All dependencies including K8s clients are injected via constructor.
    """

    def __init__(
        self,
        config: K8sWorkerConfig,
        producer: UnifiedProducer,
        settings: Settings,
        logger: logging.Logger,
        event_metrics: EventMetrics,
        kubernetes_metrics: KubernetesMetrics,
        execution_metrics: ExecutionMetrics,
        k8s_v1: k8s_client.CoreV1Api,
        k8s_apps_v1: k8s_client.AppsV1Api,
    ):
        self._event_metrics = event_metrics
        self.logger = logger
        self.metrics = kubernetes_metrics
        self.execution_metrics = execution_metrics
        self.config = config
        self._settings = settings

        # Kubernetes clients via DI
        self.v1 = k8s_v1
        self.apps_v1 = k8s_apps_v1

        # Components
        self.pod_builder = PodBuilder(namespace=self.config.namespace, config=self.config)
        self.producer = producer

        # State tracking
        self._active_creations: set[str] = set()
        self._creation_semaphore = asyncio.Semaphore(self.config.max_concurrent_pods)

    async def handle_create_pod_command(self, command: CreatePodCommandEvent) -> None:
        """Handle create pod command from saga orchestrator."""
        execution_id = command.execution_id

        # Check if already processing
        if execution_id in self._active_creations:
            self.logger.warning(f"Already creating pod for execution {execution_id}")
            return

        # Create pod asynchronously
        asyncio.create_task(self._create_pod_for_execution(command))

    async def handle_delete_pod_command(self, command: DeletePodCommandEvent) -> None:
        """Handle delete pod command from saga orchestrator (compensation)."""
        execution_id = command.execution_id
        self.logger.info(f"Deleting pod for execution {execution_id} due to: {command.reason}")

        try:
            # Delete the pod
            pod_name = f"executor-{execution_id}"
            await asyncio.to_thread(
                self.v1.delete_namespaced_pod,
                name=pod_name,
                namespace=self.config.namespace,
                grace_period_seconds=30,
            )
            self.logger.info(f"Successfully deleted pod {pod_name}")

            # Delete associated ConfigMap
            configmap_name = f"script-{execution_id}"
            await asyncio.to_thread(
                self.v1.delete_namespaced_config_map, name=configmap_name, namespace=self.config.namespace
            )
            self.logger.info(f"Successfully deleted ConfigMap {configmap_name}")

            # NetworkPolicy cleanup is managed via a static cluster policy; no per-execution NP deletion

        except ApiException as e:
            if e.status == 404:
                self.logger.warning(
                    f"Resources for execution {execution_id} not found (may have already been deleted)"
                )
            else:
                self.logger.error(f"Failed to delete resources for execution {execution_id}: {e}")

    async def _create_pod_for_execution(self, command: CreatePodCommandEvent) -> None:
        """Create pod for execution."""
        async with self._creation_semaphore:
            execution_id = command.execution_id
            self._active_creations.add(execution_id)
            self.metrics.update_k8s_active_creations(len(self._active_creations))

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
        """Get entrypoint script content."""
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
        """Create ConfigMap in Kubernetes."""
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
        """Create Pod in Kubernetes."""
        try:
            await asyncio.to_thread(self.v1.create_namespaced_pod, namespace=self.config.namespace, body=pod)
            self.logger.debug(f"Created Pod {pod.metadata.name}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                self.logger.warning(f"Pod {pod.metadata.name} already exists")
            else:
                raise

    async def _publish_execution_started(self, command: CreatePodCommandEvent, pod: k8s_client.V1Pod) -> None:
        """Publish execution started event."""
        event = ExecutionStartedEvent(
            execution_id=command.execution_id,
            aggregate_id=command.execution_id,  # Set aggregate_id to execution_id
            pod_name=pod.metadata.name,
            node_name=pod.spec.node_name,
            container_id=None,  # Will be set when container actually starts
            metadata=command.metadata,
        )
        await self.producer.produce(event_to_produce=event)

    async def _publish_pod_created(self, command: CreatePodCommandEvent, pod: k8s_client.V1Pod) -> None:
        """Publish pod created event."""
        event = PodCreatedEvent(
            execution_id=command.execution_id,
            pod_name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            metadata=command.metadata,
        )
        await self.producer.produce(event_to_produce=event)

    async def _publish_pod_creation_failed(self, command: CreatePodCommandEvent, error: str) -> None:
        """Publish pod creation failed event."""
        event = ExecutionFailedEvent(
            execution_id=command.execution_id,
            error_type=ExecutionErrorType.SYSTEM_ERROR,
            exit_code=-1,
            stderr=f"Failed to create pod: {error}",
            resource_usage=None,
            metadata=command.metadata,
            error_message=str(error),
        )
        await self.producer.produce(event_to_produce=event)

    async def ensure_daemonset_task(self) -> None:
        """Ensure daemonset exists, then complete (not a loop)."""
        await self.ensure_image_pre_puller_daemonset()
        self.logger.info("Image pre-puller daemonset task completed")
        # This task completes immediately after ensuring the daemonset
        # The TaskGroup will keep running because the consumer task is still running

    async def ensure_image_pre_puller_daemonset(self) -> None:
        """Ensure the runtime image pre-puller DaemonSet exists."""
        daemonset_name = "runtime-image-pre-puller"
        namespace = self.config.namespace
        await asyncio.sleep(5)

        try:
            init_containers = []
            all_images = {config.image for lang in RUNTIME_REGISTRY.values() for config in lang.values()}

            for i, image_ref in enumerate(sorted(list(all_images))):
                sanitized_image_ref = (
                    image_ref.split("/")[-1].replace(":", "-").replace(".", "-").replace("_", "-")
                )
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
                    self.apps_v1.replace_namespaced_daemon_set,
                    name=daemonset_name,
                    namespace=namespace,
                    body=manifest,
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

    async def wait_for_active_creations(self, timeout: float = 30) -> None:
        """Wait for active pod creations to complete."""
        if self._active_creations:
            self.logger.info(f"Waiting for {len(self._active_creations)} active pod creations...")
            start_time = time.time()
            while self._active_creations and (time.time() - start_time) < timeout:
                await asyncio.sleep(1)
            if self._active_creations:
                self.logger.warning(f"Timeout, {len(self._active_creations)} pod creations still active")

