import asyncio
import time
from pathlib import Path
from typing import Any

import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.rest import ApiException

from app.core.metrics import ExecutionMetrics, KubernetesMetrics
from app.domain.enums import ExecutionErrorType
from app.domain.events import (
    CreatePodCommandEvent,
    DeletePodCommandEvent,
    ExecutionFailedEvent,
    PodCreatedEvent,
)
from app.events import UnifiedProducer
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
            logger: structlog.stdlib.BoundLogger,
    ):
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
        self.apps_v1 = k8s_client.AppsV1Api(api_client)
        self.networking_v1 = k8s_client.NetworkingV1Api(api_client)

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
        """Handle delete pod command from saga orchestrator (compensation).

        Deleting the pod is sufficient — the ConfigMap has an ownerReference pointing
        to the pod, so K8s garbage-collects it automatically.
        """
        execution_id = command.execution_id
        self.logger.info(f"Deleting pod for execution {execution_id} due to: {command.reason}")

        try:
            pod_name = f"executor-{execution_id}"
            await self.v1.delete_namespaced_pod(
                name=pod_name,
                namespace=self._settings.K8S_NAMESPACE,
                grace_period_seconds=30,
            )
            self.logger.info(f"Successfully deleted pod {pod_name} (ConfigMap will be GC'd by K8s)")

        except ApiException as e:
            if e.status == 404:
                self.logger.warning(f"Pod for execution {execution_id} not found (may have already been deleted)")
            else:
                self.logger.error(f"Failed to delete pod for execution {execution_id}: {e}")

    async def _create_pod_for_execution(self, command: CreatePodCommandEvent) -> None:
        """Create pod for execution"""
        async with self._creation_semaphore:
            execution_id = command.execution_id
            self._active_creations.add(execution_id)
            self.metrics.update_active_pod_creations(len(self._active_creations))

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
                created_pod = await self._create_pod(pod)

                # Set ownerReference so K8s garbage-collects the ConfigMap when the pod is deleted
                if created_pod and created_pod.metadata and created_pod.metadata.uid:
                    await self._set_configmap_owner(config_map, created_pod)

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
                self.metrics.update_active_pod_creations(len(self._active_creations))

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

    async def _create_pod(self, pod: k8s_client.V1Pod) -> k8s_client.V1Pod | None:
        """Create Pod in Kubernetes. Returns the created pod (with UID) or None if it already existed."""
        try:
            created: k8s_client.V1Pod = await self.v1.create_namespaced_pod(
                namespace=self._settings.K8S_NAMESPACE, body=pod
            )
            self.logger.debug(f"Created Pod {pod.metadata.name}")
            return created
        except ApiException as e:
            if e.status == 409:  # Already exists
                self.logger.warning(f"Pod {pod.metadata.name} already exists")
                return None
            else:
                raise

    async def _set_configmap_owner(
        self, config_map: k8s_client.V1ConfigMap, owner_pod: k8s_client.V1Pod
    ) -> None:
        """Patch the ConfigMap with an ownerReference pointing to the pod.

        This makes K8s garbage-collect the ConfigMap automatically when the pod is deleted.
        """
        owner_ref = k8s_client.V1OwnerReference(
            api_version="v1",
            kind="Pod",
            name=owner_pod.metadata.name,
            uid=owner_pod.metadata.uid,
            block_owner_deletion=False,
        )
        patch_body = {"metadata": {"ownerReferences": [owner_ref]}}
        try:
            await self.v1.patch_namespaced_config_map(
                name=config_map.metadata.name,
                namespace=self._settings.K8S_NAMESPACE,
                body=patch_body,
            )
            self.logger.debug(
                f"Set ownerReference on ConfigMap {config_map.metadata.name} -> Pod {owner_pod.metadata.name}"
            )
        except ApiException as e:
            self.logger.warning(f"Failed to set ownerReference on ConfigMap: {e.reason}")

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
        )
        await self.producer.produce(event_to_produce=event, key=command.execution_id)

    async def ensure_namespace_security(self) -> None:
        """Apply security controls to the executor namespace at startup.

        Creates:
        - Default-deny NetworkPolicy for executor pods (blocks lateral movement and exfiltration)
        - ResourceQuota to cap aggregate pod/resource consumption
        - Pod Security Admission labels (Restricted profile)
        """
        namespace = self._settings.K8S_NAMESPACE
        await self._ensure_executor_network_policy(namespace)
        await self._ensure_executor_resource_quota(namespace)
        await self._apply_psa_labels(namespace)

    async def _ensure_executor_network_policy(self, namespace: str) -> None:
        """Create default-deny NetworkPolicy for executor pods."""
        policy_name = "executor-deny-all"

        policy = k8s_client.V1NetworkPolicy(
            api_version="networking.k8s.io/v1",
            kind="NetworkPolicy",
            metadata=k8s_client.V1ObjectMeta(
                name=policy_name,
                namespace=namespace,
                labels={"app": "integr8s", "component": "security"},
            ),
            spec=k8s_client.V1NetworkPolicySpec(
                pod_selector=k8s_client.V1LabelSelector(
                    match_labels={"component": "executor"},
                ),
                policy_types=["Ingress", "Egress"],
                ingress=[],
                egress=[],
            ),
        )

        try:
            await self.networking_v1.read_namespaced_network_policy(name=policy_name, namespace=namespace)
            await self.networking_v1.replace_namespaced_network_policy(
                name=policy_name, namespace=namespace, body=policy,
            )
            self.logger.info(f"NetworkPolicy '{policy_name}' updated in namespace {namespace}")
        except ApiException as e:
            if e.status == 404:
                await self.networking_v1.create_namespaced_network_policy(namespace=namespace, body=policy)
                self.logger.info(f"NetworkPolicy '{policy_name}' created in namespace {namespace}")
            else:
                self.logger.error(f"Failed to apply NetworkPolicy '{policy_name}': {e.reason}")

    async def _ensure_executor_resource_quota(self, namespace: str) -> None:
        """Create ResourceQuota to cap aggregate executor pod consumption."""
        quota_name = "executor-quota"

        quota = k8s_client.V1ResourceQuota(
            api_version="v1",
            kind="ResourceQuota",
            metadata=k8s_client.V1ObjectMeta(
                name=quota_name,
                namespace=namespace,
                labels={"app": "integr8s", "component": "security"},
            ),
            spec=k8s_client.V1ResourceQuotaSpec(
                hard={
                    "pods": str(self._settings.K8S_MAX_CONCURRENT_PODS),
                    "requests.cpu": f"{self._settings.K8S_MAX_CONCURRENT_PODS}",
                    "requests.memory": f"{self._settings.K8S_MAX_CONCURRENT_PODS * 128}Mi",
                    "limits.cpu": f"{self._settings.K8S_MAX_CONCURRENT_PODS}",
                    "limits.memory": f"{self._settings.K8S_MAX_CONCURRENT_PODS * 128}Mi",
                },
            ),
        )

        try:
            await self.v1.read_namespaced_resource_quota(name=quota_name, namespace=namespace)
            await self.v1.replace_namespaced_resource_quota(name=quota_name, namespace=namespace, body=quota)
            self.logger.info(f"ResourceQuota '{quota_name}' updated in namespace {namespace}")
        except ApiException as e:
            if e.status == 404:
                await self.v1.create_namespaced_resource_quota(namespace=namespace, body=quota)
                self.logger.info(f"ResourceQuota '{quota_name}' created in namespace {namespace}")
            else:
                self.logger.error(f"Failed to apply ResourceQuota '{quota_name}': {e.reason}")

    async def _apply_psa_labels(self, namespace: str) -> None:
        """Apply Pod Security Admission labels to the executor namespace."""
        psa_labels = {
            "pod-security.kubernetes.io/enforce": "restricted",
            "pod-security.kubernetes.io/enforce-version": "latest",
            "pod-security.kubernetes.io/warn": "restricted",
            "pod-security.kubernetes.io/audit": "restricted",
        }

        patch_body = {"metadata": {"labels": psa_labels}}
        try:
            await self.v1.patch_namespace(name=namespace, body=patch_body)
            self.logger.info(f"Pod Security Admission labels applied to namespace {namespace}")
        except ApiException as e:
            self.logger.error(f"Failed to apply PSA labels to namespace {namespace}: {e.reason}")

    async def ensure_image_pre_puller_daemonset(self) -> None:
        """Ensure the runtime image pre-puller DaemonSet exists."""
        daemonset_name = "runtime-image-pre-puller"
        namespace = self._settings.K8S_NAMESPACE

        try:
            init_containers = []
            all_images = {config.image for lang in RUNTIME_REGISTRY.values() for config in lang.values()}

            for i, image_ref in enumerate(sorted(all_images)):
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
                await self.apps_v1.read_namespaced_daemon_set(name=daemonset_name, namespace=namespace)
                self.logger.info(f"DaemonSet '{daemonset_name}' exists. Replacing to ensure it is up-to-date.")
                await self.apps_v1.replace_namespaced_daemon_set(
                    name=daemonset_name, namespace=namespace, body=manifest  # type: ignore[arg-type]
                )
                self.logger.info(f"DaemonSet '{daemonset_name}' replaced successfully.")
            except ApiException as e:
                if e.status == 404:
                    self.logger.info(f"DaemonSet '{daemonset_name}' not found. Creating...")
                    await self.apps_v1.create_namespaced_daemon_set(
                        namespace=namespace, body=manifest  # type: ignore[arg-type]
                    )
                    self.logger.info(f"DaemonSet '{daemonset_name}' created successfully.")
                else:
                    raise

        except ApiException as e:
            self.logger.error(f"K8s API error applying DaemonSet '{daemonset_name}': {e.reason}", exc_info=True)
        except Exception as e:
            self.logger.error(f"Unexpected error applying image-puller DaemonSet: {e}", exc_info=True)
