import asyncio
import logging
from datetime import datetime, timedelta, timezone
from functools import partial
from typing import Any

from kubernetes import client as k8s_client
from kubernetes.client.rest import ApiException

from app.core.k8s_clients import K8sClients
from app.domain.exceptions import InfrastructureError

# Python 3.12 type aliases
type ResourceDict = dict[str, list[str]]
type CountDict = dict[str, int]


class ResourceCleaner:
    """Service for cleaning up Kubernetes resources.

    Accepts K8sClients via dependency injection for proper configuration management.
    """

    def __init__(self, k8s_clients: K8sClients, logger: logging.Logger) -> None:
        self.v1: k8s_client.CoreV1Api = k8s_clients.v1
        self.networking_v1: k8s_client.NetworkingV1Api = k8s_clients.networking_v1
        self.logger = logger

    async def cleanup_pod_resources(
        self,
        pod_name: str,
        namespace: str = "integr8scode",
        execution_id: str | None = None,
        timeout: int = 60,
        delete_pvcs: bool = False,
    ) -> None:
        """Clean up all resources associated with a pod"""
        self.logger.info(f"Cleaning up resources for pod: {pod_name}")

        try:
            tasks = [
                self._delete_pod(pod_name, namespace),
                *(
                    [
                        self._delete_configmaps(execution_id, namespace),
                        *([self._delete_pvcs(execution_id, namespace)] if delete_pvcs else []),
                    ]
                    if execution_id
                    else []
                ),
            ]

            await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)

            self.logger.info(f"Successfully cleaned up resources for pod: {pod_name}")

        except asyncio.TimeoutError as e:
            self.logger.error(f"Timeout cleaning up resources for pod: {pod_name}")
            raise InfrastructureError("Resource cleanup timed out") from e
        except Exception as e:
            self.logger.error(f"Failed to cleanup resources: {e}")
            raise InfrastructureError(f"Resource cleanup failed: {e}") from e

    async def _delete_pod(self, pod_name: str, namespace: str) -> None:
        """Delete a pod"""
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self.v1.read_namespaced_pod, pod_name, namespace)

            await loop.run_in_executor(
                None, partial(self.v1.delete_namespaced_pod, pod_name, namespace, grace_period_seconds=30)
            )

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
            loop = asyncio.get_running_loop()
            label_selector = f"execution-id={execution_id}"

            resources = await loop.run_in_executor(None, partial(list_func, namespace, label_selector=label_selector))

            for resource in resources.items:
                await loop.run_in_executor(None, delete_func, resource.metadata.name, namespace)
                self.logger.info(f"Deleted {resource_type}: {resource.metadata.name}")

        except ApiException as e:
            self.logger.error(f"Failed to delete {resource_type}s: {e}")

    async def cleanup_orphaned_resources(
        self,
        namespace: str = "integr8scode",
        max_age_hours: int = 24,
        dry_run: bool = False,
    ) -> ResourceDict:
        """Clean up orphaned resources older than specified age"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cleaned: ResourceDict = {
            "pods": [],
            "configmaps": [],
            "pvcs": [],
        }

        try:
            await self._cleanup_orphaned_pods(namespace, cutoff_time, cleaned, dry_run)
            await self._cleanup_orphaned_configmaps(namespace, cutoff_time, cleaned, dry_run)

            return cleaned

        except Exception as e:
            self.logger.error(f"Failed to cleanup orphaned resources: {e}")
            raise InfrastructureError(f"Orphaned resource cleanup failed: {e}") from e

    async def _cleanup_orphaned_pods(
        self, namespace: str, cutoff_time: datetime, cleaned: ResourceDict, dry_run: bool
    ) -> None:
        """Clean up orphaned pods"""
        loop = asyncio.get_running_loop()
        pods = await loop.run_in_executor(
            None, partial(self.v1.list_namespaced_pod, namespace, label_selector="app=integr8s")
        )

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
        loop = asyncio.get_running_loop()
        configmaps = await loop.run_in_executor(
            None, partial(self.v1.list_namespaced_config_map, namespace, label_selector="app=integr8s")
        )

        for cm in configmaps.items:
            if cm.metadata.creation_timestamp.replace(tzinfo=timezone.utc) < cutoff_time:
                cleaned["configmaps"].append(cm.metadata.name)

                if not dry_run:
                    try:
                        await loop.run_in_executor(
                            None, self.v1.delete_namespaced_config_map, cm.metadata.name, namespace
                        )
                    except Exception as e:
                        self.logger.error(f"Failed to delete orphaned ConfigMap {cm.metadata.name}: {e}")

    async def get_resource_usage(self, namespace: str = "default") -> CountDict:
        """Get current resource usage counts"""
        loop = asyncio.get_running_loop()
        label_selector = "app=integr8s"

        default_counts = {"pods": 0, "configmaps": 0, "network_policies": 0}

        try:
            # Get pods count
            try:
                pods = await loop.run_in_executor(
                    None, partial(self.v1.list_namespaced_pod, namespace, label_selector=label_selector)
                )
                pod_count = len(pods.items)
            except Exception as e:
                self.logger.warning(f"Failed to get pods: {e}")
                pod_count = 0

            # Get configmaps count
            try:
                configmaps = await loop.run_in_executor(
                    None, partial(self.v1.list_namespaced_config_map, namespace, label_selector=label_selector)
                )
                configmap_count = len(configmaps.items)
            except Exception as e:
                self.logger.warning(f"Failed to get configmaps: {e}")
                configmap_count = 0

            # Get network policies count
            try:
                policies = await loop.run_in_executor(
                    None,
                    partial(
                        self.networking_v1.list_namespaced_network_policy, namespace, label_selector=label_selector
                    ),
                )
                policy_count = len(policies.items)
            except Exception as e:
                self.logger.warning(f"Failed to get network policies: {e}")
                policy_count = 0

            return {
                "pods": pod_count,
                "configmaps": configmap_count,
                "network_policies": policy_count,
            }

        except Exception as e:
            self.logger.error(f"Failed to get resource usage: {e}")
            return default_counts
