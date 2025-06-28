import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Set

from app.config import get_settings
from app.core.logging import logger
from app.services.circuit_breaker import CircuitBreaker
from app.services.pod_manifest_builder import PodManifestBuilder
from fastapi import Depends, Request
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


class KubernetesServiceError(Exception):
    pass


class KubernetesPodError(KubernetesServiceError):
    pass


class KubernetesConfigError(KubernetesServiceError):
    pass


_K8S_CLIENT_NOT_INITIALIZED_MSG: str = "Kubernetes client not initialized."


class KubernetesServiceManager:
    def __init__(self) -> None:
        self.services: Set["KubernetesService"] = set()

    def register(self, service: "KubernetesService") -> None:
        self.services.add(service)

    def unregister(self, service: "KubernetesService") -> None:
        self.services.discard(service)

    async def shutdown_all(self) -> None:
        for service in self.services:
            try:
                await service.graceful_shutdown()
            except Exception as e:
                logger.error(f"Error shutting down K8s service: {str(e)}")
            self.services.discard(service)


class KubernetesService:
    NAMESPACE = "default"
    POD_RETRY_ATTEMPTS = 60
    POD_RETRY_INTERVAL = 1
    POD_SUCCESS_STATES = {"Succeeded", "Failed"}
    SHUTDOWN_TIMEOUT = 30
    HEALTH_CHECK_INTERVAL = 60
    CONTAINER_KUBECONFIG_PATH = "/app/kubeconfig.yaml"

    def __init__(self, manager: KubernetesServiceManager):
        self.settings = get_settings()
        self.manager = manager
        self._initialize_kubernetes_client()

        self.circuit_breaker = CircuitBreaker()
        self._active_pods: Dict[str, datetime] = {}
        self._is_healthy = True
        self._last_health_check = datetime.now(timezone.utc)

        self.manager.register(self)

    def __del__(self) -> None:
        self.manager.unregister(self)

    async def check_health(self) -> bool:
        try:
            if (datetime.now(timezone.utc) - self._last_health_check).seconds < self.HEALTH_CHECK_INTERVAL:
                return self._is_healthy
            await asyncio.to_thread(self.version_api.get_code)
            self._is_healthy = True
            self.circuit_breaker.record_success()
            self._last_health_check = datetime.now(timezone.utc)
            return True
        except Exception as e:
            logger.error(f"Kubernetes health check failed: {str(e)}")
            self._is_healthy = False
            self.circuit_breaker.record_failure()
            self._last_health_check = datetime.now(timezone.utc)
            return False

    async def graceful_shutdown(self) -> None:
        shutdown_deadline = datetime.now(timezone.utc) + timedelta(seconds=self.SHUTDOWN_TIMEOUT)
        # Make a copy of keys to avoid modification during iteration issues
        for pod_name in list(self._active_pods.keys()):
            if datetime.now(timezone.utc) > shutdown_deadline:
                logger.warning("Shutdown timeout reached, forcing pod termination")
                break
            try:
                await self._cleanup_pod_resources(pod_name)
            except Exception as e:
                logger.error(f"Error during pod cleanup on shutdown: {str(e)}")

    def _initialize_kubernetes_client(self) -> None:
        try:
            self._setup_kubernetes_config()
            self.v1 = k8s_client.CoreV1Api()
            self.version_api = k8s_client.VersionApi()
            self._test_api_connection()
            logger.info("Kubernetes client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {str(e)}")
            self.v1 = None
            self.version_api = None
            raise KubernetesConfigError(f"Failed to initialize Kubernetes client: {str(e)}") from e

    def _setup_kubernetes_config(self) -> None:
        if os.path.exists(self.CONTAINER_KUBECONFIG_PATH):
            logger.info(f"Using kubeconfig from {self.CONTAINER_KUBECONFIG_PATH}")
            k8s_config.load_kube_config(config_file=self.CONTAINER_KUBECONFIG_PATH)
        elif os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
            logger.info("Using in-cluster Kubernetes configuration")
            k8s_config.load_incluster_config()
        else:
            default_kube_path = os.path.expanduser(self.settings.KUBERNETES_CONFIG_PATH)
            if not os.path.exists(default_kube_path):
                raise KubernetesConfigError("Could not find valid Kubernetes configuration.")

            logger.info(f"Using default kubeconfig from {default_kube_path}")
            k8s_config.load_kube_config(config_file=default_kube_path)

        default_config = k8s_client.Configuration.get_default_copy()
        logger.info(f"Kubernetes client configured for host: {default_config.host}")

    def _test_api_connection(self) -> None:
        try:
            version = self.version_api.get_code()
            logger.info(f"Successfully connected to Kubernetes API. Server version: {version.git_version}")
        except Exception as e:
            logger.error(f"Unexpected error during K8s API connection test: {str(e)}")
            raise KubernetesConfigError(f"Unexpected error connecting to Kubernetes API: {str(e)}") from e

    async def create_execution_pod(
            self,
            execution_id: str,
            image: str,
            command: List[str],
            config_map_data: Dict[str, str]
    ) -> None:
        if not self.circuit_breaker.should_allow_request():
            raise KubernetesServiceError("Service circuit breaker is open")
        if not await self.check_health():
            raise KubernetesServiceError("Kubernetes service is unhealthy")

        config_map_name = f"script-{execution_id}"
        pod_name = f"execution-{execution_id}"

        try:
            entrypoint_script_path = Path("app/scripts/entrypoint.py")
            entrypoint_code = await asyncio.to_thread(entrypoint_script_path.read_text)

            config_map_data["entrypoint.py"] = entrypoint_code

            config_map_body = k8s_client.V1ConfigMap(
                metadata=k8s_client.V1ObjectMeta(name=config_map_name),
                data=config_map_data
            )
            await self._create_config_map(config_map_body)

            final_pod_command = ["/scripts/entrypoint.py"] + command

            builder = PodManifestBuilder(
                execution_id=execution_id,
                config_map_name=config_map_name,
                image=image,
                command=final_pod_command,
                pod_cpu_limit=self.settings.K8S_POD_CPU_LIMIT,
                pod_cpu_request=self.settings.K8S_POD_CPU_REQUEST,
                pod_memory_limit=self.settings.K8S_POD_MEMORY_LIMIT,
                pod_memory_request=self.settings.K8S_POD_MEMORY_REQUEST,
                pod_execution_timeout=self.settings.K8S_POD_EXECUTION_TIMEOUT,
            )
            pod_manifest = builder.build()
            await self._create_namespaced_pod(pod_manifest)

            self._active_pods[execution_id] = datetime.now(timezone.utc)
            logger.info(f"Successfully created pod '{pod_name}' with image '{image}'")
            self.circuit_breaker.record_success()

        except Exception as e:
            logger.error(f"Failed to create execution pod '{execution_id}': {str(e)}", exc_info=True)
            self.circuit_breaker.record_failure()
            await self._cleanup_resources(pod_name, config_map_name)
            raise KubernetesPodError(f"Failed to create execution pod: {str(e)}") from e

    async def get_pod_logs(self, execution_id: str) -> tuple[str, str, dict]:
        # This method reverts to the simple version that parses the clean log output
        pod_name = f"execution-{execution_id}"
        config_map_name = f"script-{execution_id}"

        try:
            pod = await self._wait_for_pod_completion(pod_name)
            pod_phase = pod.status.phase if pod and pod.status else "Unknown"
            full_logs = await self._get_container_logs(pod_name, "script-runner")

            # The simple, reliable parser for the ###METRICS### block
            output, metrics = self._extract_execution_metrics(full_logs)

            final_exit_code = metrics.get("exit_code", 1)
            metrics["pod_phase"] = pod_phase
            metrics["status"] = "completed" if final_exit_code == 0 else "error"

            return output, pod_phase, metrics
        finally:
            logger.info(f"Initiating cleanup for execution '{execution_id}'...")
            await self._cleanup_resources(pod_name, config_map_name)
            self._active_pods.pop(execution_id, None)

    def _extract_execution_metrics(self, logs: str) -> tuple[str, dict]:
        # This is the simple parser for the entrypoint.py output
        split_marker = "\n###METRICS###\n"
        if split_marker in logs:
            output, metrics_json = logs.rsplit(split_marker, 1)
            try:
                metrics_data = json.loads(metrics_json)
                return output.strip(), metrics_data
            except json.JSONDecodeError:
                logger.error(f"Failed to decode metrics JSON: {metrics_json}")
                return logs.strip(), {"error": "Failed to decode metrics JSON.", "exit_code": 1}

        logger.warning("Metrics marker not found in logs.")
        return logs.strip(), {"error": "Metrics marker not found in logs.", "exit_code": 1}

    async def _wait_for_pod_completion(self, pod_name: str) -> k8s_client.V1Pod:
        logger.info(f"Waiting for pod '{pod_name}' to complete...")
        for _ in range(self.POD_RETRY_ATTEMPTS):
            try:
                pod = await asyncio.to_thread(self.v1.read_namespaced_pod, pod_name, self.NAMESPACE)
                if pod.status and pod.status.phase in self.POD_SUCCESS_STATES:
                    logger.info(f"Pod '{pod_name}' reached terminal phase: {pod.status.phase}")
                    return pod
            except ApiException as e:
                if e.status == 404:
                    logger.warning(f"Pod '{pod_name}' not found, retrying...")
                else:
                    logger.error(f"API Error while waiting for pod '{pod_name}': {e.reason}")
            await asyncio.sleep(self.POD_RETRY_INTERVAL)
        raise KubernetesPodError(f"Timeout waiting for pod '{pod_name}' to complete.")

    async def _get_container_logs(self, pod_name: str, container_name: str) -> str:
        try:
            return await asyncio.to_thread(
                self.v1.read_namespaced_pod_log,
                name=pod_name,
                namespace=self.NAMESPACE,
                container=container_name,
            )
        except ApiException as e:
            logger.error(f"Could not retrieve logs for {container_name} in {pod_name}: {e.reason}")
            return f"Error retrieving logs: {e.reason}"

    async def _create_config_map(self, config_map: k8s_client.V1ConfigMap) -> None:
        try:
            await asyncio.to_thread(self.v1.create_namespaced_config_map, namespace=self.NAMESPACE, body=config_map)
            logger.info(f"ConfigMap '{config_map.metadata.name}' created successfully.")
        except ApiException as e:
            logger.error(f"Failed to create ConfigMap '{config_map.metadata.name}': {e.status} {e.reason}")
            raise KubernetesServiceError(f"Failed to create ConfigMap: {str(e)}") from e

    async def _create_namespaced_pod(self, pod_manifest: Dict[str, Any]) -> None:
        pod_name = pod_manifest.get("metadata", {}).get("name", "unknown-pod")
        try:
            await asyncio.to_thread(self.v1.create_namespaced_pod, body=pod_manifest, namespace=self.NAMESPACE)
            logger.info(f"Pod '{pod_name}' created successfully.")
        except ApiException as e:
            logger.error(f"Failed to create pod '{pod_name}': {e.status} {e.reason}")
            raise KubernetesPodError(f"Failed to create pod: {str(e)}") from e

    async def _cleanup_resources(self, pod_name: str, config_map_name: str) -> None:
        if not self.v1:
            return
        try:
            await asyncio.to_thread(self.v1.delete_namespaced_pod, name=pod_name, namespace=self.NAMESPACE)
            logger.info(f"Deletion request sent for pod '{pod_name}'")
        except ApiException as e:
            logger.error(f"Failed to send deletion request for pod '{pod_name}': {e.reason}")

        try:
            await asyncio.to_thread(self.v1.delete_namespaced_config_map, name=config_map_name,
                                    namespace=self.NAMESPACE)
            logger.info(f"Deletion request sent for config map '{config_map_name}'")
        except ApiException as e:
            logger.error(f"Failed to delete config map '{config_map_name}': {e.reason}")

    async def _cleanup_pod_resources(self, pod_name: str) -> None:
        if not pod_name.startswith("execution-"):
            return
        execution_id = pod_name[len("execution-"):]
        config_map_name = f"script-{execution_id}"
        await self._cleanup_resources(pod_name, config_map_name)


def get_k8s_manager(request: Request) -> KubernetesServiceManager:
    if not hasattr(request.app.state, "k8s_manager"):
        request.app.state.k8s_manager = KubernetesServiceManager()
    return request.app.state.k8s_manager  # type: ignore


def get_kubernetes_service(
        request: Request,
        manager: KubernetesServiceManager = Depends(get_k8s_manager)
) -> KubernetesService:
    if not hasattr(request.app.state, "k8s_service"):
        logger.info("Creating new KubernetesService singleton instance.")
        request.app.state.k8s_service = KubernetesService(manager)
    return request.app.state.k8s_service  # type: ignore
