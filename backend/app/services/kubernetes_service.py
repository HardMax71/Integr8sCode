import asyncio
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Set

from fastapi import Depends, Request
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from app.config import get_settings
from app.core.logging import logger
from app.services.circuit_breaker import CircuitBreaker
from app.services.pod_manifest_builder import PodManifestBuilder


class KubernetesServiceError(Exception):
    pass


class KubernetesPodError(KubernetesServiceError):
    pass


class KubernetesConfigError(KubernetesServiceError):
    pass


class KubernetesServiceManager:
    """
    Sits at a higher level to manage multiple KubernetesService
    instances (like a registry).
    """

    def __init__(self) -> None:
        self.services: Set["KubernetesService"] = set()

    def register(self, service: "KubernetesService") -> None:
        self.services.add(service)

    def unregister(self, service: "KubernetesService") -> None:
        self.services.discard(service)

    async def shutdown_all(self) -> None:
        """Gracefully shut down all managed services."""
        for service in list(self.services):
            try:
                await service.graceful_shutdown()
            except Exception as e:
                logger.error(f"Error shutting down K8s service: {str(e)}")
            self.services.discard(service)


class KubernetesService:
    """
    Responsible for:
      - Checking circuit breaker and K8s health
      - Creating ConfigMaps & Pods
      - Getting logs and resource usage (before cleaning up)
      - Cleaning up resources
    """
    NAMESPACE = "default"
    POD_RETRY_ATTEMPTS = 60
    POD_RETRY_INTERVAL = 1
    POD_SUCCESS_STATES = {"Succeeded", "Failed"}
    SHUTDOWN_TIMEOUT = 30  # seconds for graceful shutdown
    HEALTH_CHECK_INTERVAL = 60  # seconds

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
        """Checks health of K8s, with a cooldown to avoid spamming the cluster."""
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
        """
        Gracefully shuts down the service by cleaning up all active pods.
        Terminates early if we exceed the shutdown deadline.
        """
        shutdown_deadline = datetime.now(timezone.utc) + timedelta(seconds=self.SHUTDOWN_TIMEOUT)
        for pod_name in list(self._active_pods.keys()):
            if datetime.now(timezone.utc) > shutdown_deadline:
                logger.warning("Shutdown timeout reached, forcing pod termination")
                break
            try:
                await self._cleanup_pod_resources(pod_name)
            except Exception as e:
                logger.error(f"Error during pod cleanup on shutdown: {str(e)}")

    def _initialize_kubernetes_client(self) -> None:
        """Initializes the K8s client, including config and testing API connection."""
        try:
            self._setup_kubernetes_config()
            self._setup_api_client()
            self._test_api_connection()
        except Exception as e:
            raise KubernetesConfigError(f"Failed to initialize Kubernetes client: {str(e)}") from e

    def _setup_kubernetes_config(self) -> None:
        logging.info(f"KUBERNETES_CONFIG_PATH: {self.settings.KUBERNETES_CONFIG_PATH}")
        logging.info(f"KUBERNETES_CA_CERTIFICATE_PATH: {self.settings.KUBERNETES_CA_CERTIFICATE_PATH}")
        if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
            config.load_incluster_config()
            logging.info("Using in-cluster Kubernetes configuration")
        else:
            config.load_kube_config(config_file=self.settings.KUBERNETES_CONFIG_PATH)
            logging.info(f"Using kubeconfig from {self.settings.KUBERNETES_CONFIG_PATH}")

    def _setup_api_client(self) -> None:
        """Configures the global API client with SSL and CA certificate, if present."""
        configuration = client.Configuration.get_default_copy()
        configuration.verify_ssl = True
        ca_cert_path = self.settings.KUBERNETES_CA_CERTIFICATE_PATH
        if ca_cert_path and os.path.exists(ca_cert_path):
            configuration.ssl_ca_cert = ca_cert_path
            logging.info(f"Using custom CA certificate: {ca_cert_path}")
        else:
            logging.warning("Custom CA certificate not found. Using default CA bundle.")
        api_client = client.ApiClient(configuration)
        self.v1 = client.CoreV1Api(api_client)
        self.version_api = client.VersionApi(api_client)
        self.custom_api = client.CustomObjectsApi(api_client)

    def _test_api_connection(self) -> None:
        """Confirms authentication and connectivity before proceeding."""
        try:
            version = self.version_api.get_code()
            logging.info(f"Successfully connected to Kubernetes API. Server version: {version.git_version}")
        except ApiException as e:
            if e.status == 401:
                raise KubernetesConfigError("Authentication failed. Please check your token.") from e
            raise KubernetesConfigError(f"Failed to connect to Kubernetes API: {str(e)}") from e

    async def create_execution_pod(self, execution_id: str, script: str, python_version: str) -> None:
        """
        Creates and executes a pod for the provided script:
          1) Checks the circuit breaker and health
          2) Creates a ConfigMap to hold the script
          3) Builds and creates the Pod via a PodManifestBuilder
        """
        if not self.circuit_breaker.should_allow_request():
            raise KubernetesServiceError("Service circuit breaker is open")
        if not await self.check_health():
            raise KubernetesServiceError("Kubernetes service is unhealthy")

        temp_file_path = None
        config_map_name = f"script-{execution_id}"
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
                temp_file.write(script)
                temp_file_path = temp_file.name
            with open(temp_file_path, "r") as f:
                script_content = f.read()
            config_map = client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name=config_map_name),
                data={"script.py": script_content},
            )
            await self._create_config_map(config_map)
            builder = PodManifestBuilder(
                python_version=python_version,
                execution_id=execution_id,
                script_config_map_name=config_map_name,
                pod_cpu_limit=self.settings.K8S_POD_CPU_LIMIT,
                pod_cpu_request=self.settings.K8S_POD_CPU_REQUEST,
                pod_memory_limit=self.settings.K8S_POD_MEMORY_LIMIT,
                pod_memory_request=self.settings.K8S_POD_MEMORY_REQUEST,
                pod_execution_timeout=self.settings.K8S_POD_EXECUTION_TIMEOUT,
                namespace=self.NAMESPACE,
            )
            pod_manifest = builder.build()
            await self._create_namespaced_pod(pod_manifest)
            self._active_pods[execution_id] = datetime.now(timezone.utc)
            self.circuit_breaker.record_success()
        except Exception as e:
            self.circuit_breaker.record_failure()
            raise KubernetesPodError(f"Failed to create execution pod: {str(e)}") from e
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    async def get_pod_logs(self, execution_id: str) -> tuple[str, str, dict]:
        pod_name = f"execution-{execution_id}"
        config_map_name = f"script-{execution_id}"

        try:
            # Wait for pod completion
            pod = None
            for _ in range(self.POD_RETRY_ATTEMPTS):
                pod = await asyncio.to_thread(self.v1.read_namespaced_pod, pod_name, self.NAMESPACE)
                if pod and pod.status and pod.status.phase in self.POD_SUCCESS_STATES:
                    break
                await asyncio.sleep(self.POD_RETRY_INTERVAL)

            if not pod or pod.status.phase not in self.POD_SUCCESS_STATES:
                raise KubernetesPodError("Timeout waiting for pod to complete")

            # Get logs from the 'script' container
            try:
                full_logs = await asyncio.to_thread(
                    self.v1.read_namespaced_pod_log,
                    pod_name,
                    self.NAMESPACE,
                    container='script'
                )
            except ApiException:
                full_logs = "No script output available"

            print(f"SCRIPT LOGS (raw): {full_logs}", flush=True)  # for debugging

            # Split out metrics and script output
            script_output, resource_usage = self._extract_execution_metrics(full_logs,
                                                                            execution_id,
                                                                            pod.status.phase)

            # Return the cleaned script output, pod status, and parsed metrics.
            return script_output, pod.status.phase, resource_usage

        finally:
            await self._cleanup_resources(pod_name, config_map_name)
            if execution_id in self._active_pods:
                del self._active_pods[execution_id]

    def _extract_execution_metrics(self, logs: str, execution_id: str, pod_phase: str) -> tuple:
        """
        Splits the logs into the executed script output and metrics JSON.
        Returns a tuple: (script_output, metrics_dict)
        """
        default_metrics = {
            "execution_id": execution_id,
            "execution_time": 0,
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "exit_code": 0,
            "status": pod_phase
        }
        try:
            # Use a regex to find the metrics marker and capture the JSON block that follows.
            # The pattern assumes the marker is "###METRICS###" followed by some whitespace and a JSON object.
            pattern = r"###METRICS###\s*(\{.*?\})"
            match = re.search(pattern, logs, re.DOTALL)
            if match:
                metrics_json = match.group(1).strip()
                metrics = json.loads(metrics_json)
                exit_code = metrics.get("exit_code", 0)
                computed_status = "completed" if exit_code == 0 else "failed"
                metrics["status"] = computed_status
                # Remove the entire metrics section (marker + JSON) from the logs.
                output = re.sub(pattern, "", logs, flags=re.DOTALL).strip()
                return output, metrics
            else:
                return logs, default_metrics
        except Exception as e:
            logger.error(f"Failed to parse metrics for {execution_id}: {str(e)}")
            return logs, default_metrics

    async def _create_config_map(self, config_map: client.V1ConfigMap) -> None:
        try:
            await asyncio.to_thread(
                self.v1.create_namespaced_config_map,
                namespace=self.NAMESPACE,
                body=config_map,
            )
        except ApiException as e:
            raise KubernetesServiceError(f"Failed to create ConfigMap: {str(e)}") from e

    async def _create_namespaced_pod(self, pod_manifest: Dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(
                self.v1.create_namespaced_pod,
                body=pod_manifest,
                namespace=self.NAMESPACE,
            )
        except ApiException as e:
            raise KubernetesPodError(f"Failed to create pod: {str(e)}") from e

    async def _cleanup_resources(self, pod_name: str, config_map_name: str) -> None:
        try:
            await asyncio.to_thread(
                self.v1.delete_namespaced_pod,
                name=pod_name,
                namespace=self.NAMESPACE,
                grace_period_seconds=30,
            )
            logger.info(f"Successfully deleted pod {pod_name}")
            await asyncio.to_thread(
                self.v1.delete_namespaced_config_map,
                name=config_map_name,
                namespace=self.NAMESPACE,
            )
            logger.info(f"Successfully deleted config map {config_map_name}")
        except ApiException as e:
            if e.status != 404:
                logger.error(f"Failed to cleanup resources: {str(e)}")

    async def _cleanup_pod_resources(self, pod_name: str) -> None:
        if not pod_name.startswith("execution-"):
            logger.error(f"Unrecognized pod naming convention: {pod_name}")
            return
        execution_id = pod_name[len("execution-"):]
        config_map_name = f"script-{execution_id}"
        await self._cleanup_resources(pod_name, config_map_name)


def get_k8s_manager(request: Request) -> KubernetesServiceManager:
    if not hasattr(request.app.state, "k8s_manager"):
        request.app.state.k8s_manager = KubernetesServiceManager()
    return request.app.state.k8s_manager  # type: ignore


def get_kubernetes_service(
        manager: KubernetesServiceManager = Depends(get_k8s_manager)
) -> KubernetesService:
    return KubernetesService(manager)
