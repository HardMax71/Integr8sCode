"""Kubernetes Worker - stateless event handler.

Creates Kubernetes pods from execution events. Receives events,
processes them, and publishes results. No lifecycle management.
All state is stored in Redis repositories.
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.core.metrics import EventMetrics, ExecutionMetrics, KubernetesMetrics
from app.db.repositories.pod_state_repository import PodStateRepository
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


class KubernetesWorker:
    """Stateless Kubernetes worker - pure event handler.

    No lifecycle methods (start/stop) - receives ready-to-use dependencies from DI.
    All state (active creations) stored in Redis via PodStateRepository.
    """

    def __init__(
        self,
        config: K8sWorkerConfig,
        producer: UnifiedProducer,
        pod_state_repo: PodStateRepository,
        v1_client: k8s_client.CoreV1Api,
        networking_v1_client: k8s_client.NetworkingV1Api,
        apps_v1_client: k8s_client.AppsV1Api,
        logger: logging.Logger,
        kubernetes_metrics: KubernetesMetrics,
        execution_metrics: ExecutionMetrics,
        event_metrics: EventMetrics,
    ) -> None:
        self._config = config
        self._producer = producer
        self._pod_state_repo = pod_state_repo
        self._v1 = v1_client
        self._networking_v1 = networking_v1_client
        self._apps_v1 = apps_v1_client
        self._logger = logger
        self._metrics = kubernetes_metrics
        self._execution_metrics = execution_metrics
        self._event_metrics = event_metrics
        self._pod_builder = PodBuilder(namespace=config.namespace, config=config)

    async def handle_create_pod_command(self, command: CreatePodCommandEvent) -> None:
        """Handle create pod command from saga orchestrator."""
        execution_id = command.execution_id
        self._logger.info(f"Processing create_pod_command for execution {execution_id} from saga {command.saga_id}")

        # Try to claim this creation atomically in Redis
        claimed = await self._pod_state_repo.try_claim_creation(execution_id, ttl_seconds=300)
        if not claimed:
            self._logger.warning(f"Already creating pod for execution {execution_id}, skipping")
            return

        await self._create_pod_for_execution(command)

    async def handle_delete_pod_command(self, command: DeletePodCommandEvent) -> None:
        """Handle delete pod command from saga orchestrator (compensation)."""
        execution_id = command.execution_id
        self._logger.info(f"Deleting pod for execution {execution_id} due to: {command.reason}")

        try:
            # Delete the pod
            pod_name = f"executor-{execution_id}"
            await asyncio.to_thread(
                self._v1.delete_namespaced_pod,
                name=pod_name,
                namespace=self._config.namespace,
                grace_period_seconds=30,
            )
            self._logger.info(f"Successfully deleted pod {pod_name}")

            # Delete associated ConfigMap
            configmap_name = f"script-{execution_id}"
            await asyncio.to_thread(
                self._v1.delete_namespaced_config_map,
                name=configmap_name,
                namespace=self._config.namespace,
            )
            self._logger.info(f"Successfully deleted ConfigMap {configmap_name}")

        except ApiException as e:
            if e.status == 404:
                self._logger.warning(
                    f"Resources for execution {execution_id} not found (may have already been deleted)"
                )
            else:
                self._logger.error(f"Failed to delete resources for execution {execution_id}: {e}")

    async def _create_pod_for_execution(self, command: CreatePodCommandEvent) -> None:
        """Create pod for execution."""
        execution_id = command.execution_id
        start_time = time.time()

        try:
            # Update metrics for active creations
            active_count = await self._pod_state_repo.get_active_creations_count()
            self._metrics.update_k8s_active_creations(active_count)

            # Build and create ConfigMap
            script_content = command.script
            entrypoint_content = await self._get_entrypoint_script()

            config_map = self._pod_builder.build_config_map(
                command=command,
                script_content=script_content,
                entrypoint_content=entrypoint_content,
            )
            await self._create_config_map(config_map)

            # Build and create Pod
            pod = self._pod_builder.build_pod_manifest(command=command)
            await self._create_pod(pod)

            # Publish PodCreated event
            await self._publish_pod_created(command, pod)

            # Update metrics
            duration = time.time() - start_time
            self._metrics.record_k8s_pod_creation_duration(duration, command.language)
            self._metrics.record_k8s_pod_created("success", command.language)

            self._logger.info(
                f"Successfully created pod {pod.metadata.name} for execution {execution_id}. "
                f"Duration: {duration:.2f}s"
            )

        except Exception as e:
            self._logger.error(f"Failed to create pod for execution {execution_id}: {e}", exc_info=True)
            self._metrics.record_k8s_pod_created("failed", "unknown")

            # Publish failure event
            await self._publish_pod_creation_failed(command, str(e))

        finally:
            # Release the creation claim
            await self._pod_state_repo.release_creation(execution_id)

            # Update metrics
            active_count = await self._pod_state_repo.get_active_creations_count()
            self._metrics.update_k8s_active_creations(active_count)

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
                self._v1.create_namespaced_config_map,
                namespace=self._config.namespace,
                body=config_map,
            )
            self._metrics.record_k8s_config_map_created("success")
            self._logger.debug(f"Created ConfigMap {config_map.metadata.name}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                self._logger.warning(f"ConfigMap {config_map.metadata.name} already exists")
                self._metrics.record_k8s_config_map_created("already_exists")
            else:
                self._metrics.record_k8s_config_map_created("failed")
                raise

    async def _create_pod(self, pod: k8s_client.V1Pod) -> None:
        """Create Pod in Kubernetes."""
        try:
            await asyncio.to_thread(
                self._v1.create_namespaced_pod,
                namespace=self._config.namespace,
                body=pod,
            )
            self._logger.debug(f"Created Pod {pod.metadata.name}")
        except ApiException as e:
            if e.status == 409:  # Already exists
                self._logger.warning(f"Pod {pod.metadata.name} already exists")
            else:
                raise

    async def _publish_execution_started(self, command: CreatePodCommandEvent, pod: k8s_client.V1Pod) -> None:
        """Publish execution started event."""
        event = ExecutionStartedEvent(
            execution_id=command.execution_id,
            aggregate_id=command.execution_id,
            pod_name=pod.metadata.name,
            node_name=pod.spec.node_name,
            container_id=None,
            metadata=command.metadata,
        )
        await self._producer.produce(event_to_produce=event)

    async def _publish_pod_created(self, command: CreatePodCommandEvent, pod: k8s_client.V1Pod) -> None:
        """Publish pod created event."""
        event = PodCreatedEvent(
            execution_id=command.execution_id,
            pod_name=pod.metadata.name,
            namespace=pod.metadata.namespace,
            metadata=command.metadata,
        )
        await self._producer.produce(event_to_produce=event)

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
        await self._producer.produce(event_to_produce=event, key=command.execution_id)

    async def get_status(self) -> dict[str, object]:
        """Get worker status."""
        active_count = await self._pod_state_repo.get_active_creations_count()
        return {
            "active_creations": active_count,
            "config": {
                "namespace": self._config.namespace,
                "max_concurrent_pods": self._config.max_concurrent_pods,
                "enable_network_policies": True,
            },
        }

    async def ensure_image_pre_puller_daemonset(self) -> None:
        """Ensure the runtime image pre-puller DaemonSet exists.

        This should be called once at startup from the worker entrypoint,
        not as a background task.
        """
        daemonset_name = "runtime-image-pre-puller"
        namespace = self._config.namespace

        try:
            init_containers = []
            all_images = {config.image for lang in RUNTIME_REGISTRY.values() for config in lang.values()}

            for i, image_ref in enumerate(sorted(list(all_images))):
                sanitized_image_ref = image_ref.split("/")[-1].replace(":", "-").replace(".", "-").replace("_", "-")
                self._logger.info(f"DAEMONSET: before: {image_ref} -> {sanitized_image_ref}")
                container_name = f"pull-{i}-{sanitized_image_ref}"
                init_containers.append(
                    {
                        "name": container_name,
                        "image": image_ref,
                        "command": ["/bin/sh", "-c", f'echo "Image {image_ref} pulled."'],
                        "imagePullPolicy": "Always",
                    }
                )

            manifest: dict[str, object] = {
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
                    self._apps_v1.read_namespaced_daemon_set,
                    name=daemonset_name,
                    namespace=namespace,
                )
                self._logger.info(f"DaemonSet '{daemonset_name}' exists. Replacing to ensure it is up-to-date.")
                await asyncio.to_thread(
                    self._apps_v1.replace_namespaced_daemon_set,
                    name=daemonset_name,
                    namespace=namespace,
                    body=manifest,
                )
                self._logger.info(f"DaemonSet '{daemonset_name}' replaced successfully.")
            except ApiException as e:
                if e.status == 404:
                    self._logger.info(f"DaemonSet '{daemonset_name}' not found. Creating...")
                    await asyncio.to_thread(
                        self._apps_v1.create_namespaced_daemon_set,
                        namespace=namespace,
                        body=manifest,
                    )
                    self._logger.info(f"DaemonSet '{daemonset_name}' created successfully.")
                else:
                    raise

        except ApiException as e:
            self._logger.error(f"K8s API error applying DaemonSet '{daemonset_name}': {e.reason}", exc_info=True)
        except Exception as e:
            self._logger.error(f"Unexpected error applying image-puller DaemonSet: {e}", exc_info=True)
