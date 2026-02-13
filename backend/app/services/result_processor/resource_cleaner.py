from datetime import datetime, timezone
from typing import Any

import structlog
from kubernetes_asyncio import client as k8s_client
from kubernetes_asyncio.client.rest import ApiException

# Python 3.12 type aliases
type ResourceDict = dict[str, list[str]]


class ResourceCleaner:
    """Service for cleaning up Kubernetes resources.

    Accepts ApiClient via dependency injection for proper configuration management.
    """

    def __init__(self, api_client: k8s_client.ApiClient, logger: structlog.stdlib.BoundLogger) -> None:
        self.v1 = k8s_client.CoreV1Api(api_client)
        self.networking_v1 = k8s_client.NetworkingV1Api(api_client)
        self.logger = logger

    async def _delete_pod(self, pod_name: str, namespace: str) -> None:
        """Delete a pod"""
        try:
            await self.v1.read_namespaced_pod(pod_name, namespace)
            await self.v1.delete_namespaced_pod(pod_name, namespace, grace_period_seconds=30)
            self.logger.info(f"Deleted pod: {pod_name}")

        except ApiException as e:
            if e.status == 404:
                self.logger.info(f"Pod {pod_name} already deleted")
            else:
                self.logger.error(f"Failed to delete pod: {e}")
                raise

    async def _delete_configmaps(self, execution_id: str, namespace: str) -> None:
        """Delete ConfigMaps for an execution"""
        await self._delete_labeled_resources(
            execution_id,
            namespace,
            self.v1.list_namespaced_config_map,
            self.v1.delete_namespaced_config_map,
            "ConfigMap",
        )

    async def _delete_pvcs(self, execution_id: str, namespace: str) -> None:
        """Delete PersistentVolumeClaims for an execution"""
        await self._delete_labeled_resources(
            execution_id,
            namespace,
            self.v1.list_namespaced_persistent_volume_claim,
            self.v1.delete_namespaced_persistent_volume_claim,
            "PVC",
        )

    async def _delete_labeled_resources(
        self, execution_id: str, namespace: str, list_func: Any, delete_func: Any, resource_type: str
    ) -> None:
        """Generic function to delete labeled resources"""
        try:
            label_selector = f"execution-id={execution_id}"
            resources = await list_func(namespace, label_selector=label_selector)

            for resource in resources.items:
                await delete_func(resource.metadata.name, namespace)
                self.logger.info(f"Deleted {resource_type}: {resource.metadata.name}")

        except ApiException as e:
            self.logger.error(f"Failed to delete {resource_type}s: {e}")

    async def _cleanup_orphaned_pods(
        self, namespace: str, cutoff_time: datetime, cleaned: ResourceDict, dry_run: bool
    ) -> None:
        """Clean up orphaned pods"""
        pods = await self.v1.list_namespaced_pod(namespace, label_selector="app=integr8s")

        terminal_phases = {"Succeeded", "Failed", "Unknown"}

        for pod in pods.items:
            if (
                pod.metadata.creation_timestamp.replace(tzinfo=timezone.utc) < cutoff_time
                and pod.status.phase in terminal_phases
            ):
                cleaned["pods"].append(pod.metadata.name)

                if not dry_run:
                    try:
                        await self._delete_pod(pod.metadata.name, namespace)
                    except Exception as e:
                        self.logger.error(f"Failed to delete orphaned pod {pod.metadata.name}: {e}")

    async def _cleanup_orphaned_configmaps(
        self, namespace: str, cutoff_time: datetime, cleaned: ResourceDict, dry_run: bool
    ) -> None:
        """Clean up orphaned ConfigMaps"""
        configmaps = await self.v1.list_namespaced_config_map(namespace, label_selector="app=integr8s")

        for cm in configmaps.items:
            if cm.metadata.creation_timestamp.replace(tzinfo=timezone.utc) < cutoff_time:
                cleaned["configmaps"].append(cm.metadata.name)

                if not dry_run:
                    try:
                        await self.v1.delete_namespaced_config_map(cm.metadata.name, namespace)
                    except Exception as e:
                        self.logger.error(f"Failed to delete orphaned ConfigMap {cm.metadata.name}: {e}")

