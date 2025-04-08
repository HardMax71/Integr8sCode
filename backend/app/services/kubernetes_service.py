import asyncio
import json
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Set

from app.config import get_settings
from app.core.logging import logger
from app.services.circuit_breaker import CircuitBreaker
from app.services.pod_manifest_builder import PodManifestBuilder
from fastapi import Depends, Request

# Import config as k8s_config and client as k8s_client for clarity
from kubernetes import client as k8s_client
from kubernetes import config as k8s_config
from kubernetes.client.rest import ApiException


class KubernetesServiceError(Exception):
    pass


class KubernetesPodError(KubernetesServiceError):
    pass


class KubernetesConfigError(KubernetesServiceError):
    pass


class KubernetesServiceManager:
    def __init__(self) -> None:
        self.services: Set["KubernetesService"] = set()

    def register(self, service: "KubernetesService") -> None:
        self.services.add(service)

    def unregister(self, service: "KubernetesService") -> None:
        self.services.discard(service)

    async def shutdown_all(self) -> None:
        for service in list(self.services):
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
    # Define standard kubeconfig path within the container for CI/generated cases
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
            # Use the already initialized version_api
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
            # Load configuration first - this sets up the default client instance
            self._setup_kubernetes_config()
            # Now create API instances using the configured default client
            self.v1 = k8s_client.CoreV1Api()
            self.version_api = k8s_client.VersionApi()
            self.custom_api = k8s_client.CustomObjectsApi()
            # Test connection using the initialized API instance
            self._test_api_connection()
            logger.info("Kubernetes client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize Kubernetes client: {str(e)}")
            # Set APIs to None or handle differently if initialization fails
            self.v1 = None
            self.version_api = None
            self.custom_api = None
            raise KubernetesConfigError(f"Failed to initialize Kubernetes client: {str(e)}") from e

    def _setup_kubernetes_config(self) -> None:
        # Explicitly check for the kubeconfig file generated in CI first
        if os.path.exists(self.CONTAINER_KUBECONFIG_PATH):
            logger.info(f"Using kubeconfig from {self.CONTAINER_KUBECONFIG_PATH}")
            k8s_config.load_kube_config(config_file=self.CONTAINER_KUBECONFIG_PATH)
        elif os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
            logger.info("Using in-cluster Kubernetes configuration")
            k8s_config.load_incluster_config()
        else:
            # Fallback to default path from settings (for local dev maybe)
            default_kube_path = os.path.expanduser(self.settings.KUBERNETES_CONFIG_PATH)
            if os.path.exists(default_kube_path):
                logger.info(f"Using default kubeconfig from {default_kube_path}")
                k8s_config.load_kube_config(config_file=default_kube_path)
            else:
                logger.error("No Kubernetes configuration found (in-cluster, CI path, or default path).")
                raise KubernetesConfigError("Could not find valid Kubernetes configuration.")
        # Log the configured host after loading
        # Note: Accessing the default config requires care, get_default_copy is safer if needed
        try:
            default_config = k8s_client.Configuration.get_default_copy()
            logger.info(f"Kubernetes client configured for host: {default_config.host}")
        except Exception:
            logger.warning("Could not retrieve default configuration host for logging.")

    def _test_api_connection(self) -> None:
        try:
            # Use the instance variable version_api initialized earlier
            version = self.version_api.get_code()
            logger.info(f"Successfully connected to Kubernetes API. Server version: {version.git_version}")
        except ApiException as e:
            logger.error(
                f"Kubernetes API connection test failed. Status: {e.status}, Reason: {e.reason}, Body: {e.body}")
            if e.status == 401:
                raise KubernetesConfigError("Authentication failed. Please check your token.") from e
            raise KubernetesConfigError(f"Failed to connect to Kubernetes API: {str(e)}") from e
        except Exception as e:  # Catch other errors like SSL handshake failures
            logger.error(f"Unexpected error during Kubernetes API connection test: {str(e)}")
            raise KubernetesConfigError(f"Unexpected error connecting to Kubernetes API: {str(e)}") from e

    async def create_execution_pod(self, execution_id: str, script: str, python_version: str) -> None:
        if not self.circuit_breaker.should_allow_request():
            raise KubernetesServiceError("Service circuit breaker is open")
        if not await self.check_health():
            raise KubernetesServiceError("Kubernetes service is unhealthy")
        # Ensure clients are initialized
        if not self.v1:
            logger.error("Kubernetes CoreV1Api client is not initialized.")
            raise KubernetesConfigError("Kubernetes client not initialized.")

        temp_file_path = None
        config_map_name = f"script-{execution_id}"
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as temp_file:
                temp_file.write(script)
                temp_file_path = temp_file.name
            with open(temp_file_path, "r") as f:
                script_content = f.read()
            config_map = k8s_client.V1ConfigMap(
                metadata=k8s_client.V1ObjectMeta(name=config_map_name),
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
            logger.info(f"Successfully created pod '{pod_manifest['metadata']['name']}' and associated config map.")
            self.circuit_breaker.record_success()
        except Exception as e:
            logger.error(f"Failed to create execution pod '{execution_id}': {str(e)}")
            self.circuit_breaker.record_failure()
            # Attempt cleanup if pod creation failed after config map creation
            await self._cleanup_resources(f"execution-{execution_id}", config_map_name)
            raise KubernetesPodError(f"Failed to create execution pod: {str(e)}") from e
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    async def get_pod_logs(self, execution_id: str) -> tuple[str, str, dict]:
        pod_name = f"execution-{execution_id}"
        config_map_name = f"script-{execution_id}"
        # Ensure clients are initialized
        if not self.v1:
            logger.error("Kubernetes CoreV1Api client is not initialized.")
            raise KubernetesConfigError("Kubernetes client not initialized.")

        try:
            pod = None
            logger.info(f"Waiting for pod '{pod_name}' to complete...")
            for attempt in range(self.POD_RETRY_ATTEMPTS):
                try:
                    pod = await asyncio.to_thread(self.v1.read_namespaced_pod, pod_name, self.NAMESPACE)
                    if pod and pod.status and pod.status.phase in self.POD_SUCCESS_STATES:
                        logger.info(f"Pod '{pod_name}' reached terminal phase: {pod.status.phase}")
                        break
                    logger.debug(
                        f"Pod '{pod_name}' status: {pod.status.phase if pod and pod.status else 'Unknown'}. "
                        f"Attempt {attempt + 1}/{self.POD_RETRY_ATTEMPTS}")
                except ApiException as e:
                    if e.status == 404:
                        logger.warning(
                            f"Pod '{pod_name}' not found (yet?). Attempt {attempt + 1}/{self.POD_RETRY_ATTEMPTS}")
                    else:
                        logger.error(
                            f"API Error reading pod '{pod_name}': {e.status} {e.reason}. "
                            f"Attempt {attempt + 1}/{self.POD_RETRY_ATTEMPTS}")
                        # Depending on the error, might want to break early or continue retrying
                await asyncio.sleep(self.POD_RETRY_INTERVAL)
            else:  # Loop completed without break
                logger.error(
                    f"Timeout waiting for pod '{pod_name}' to complete after {self.POD_RETRY_ATTEMPTS} attempts.")
                # Attempt to read pod one last time to get phase if possible
                try:
                    pod = await asyncio.to_thread(self.v1.read_namespaced_pod, pod_name, self.NAMESPACE)
                    current_phase = pod.status.phase if pod and pod.status else "Unknown"
                except Exception:
                    current_phase = "Unknown"
                raise KubernetesPodError(f"Timeout waiting for pod to complete. Last known phase: {current_phase}")

            logger.info(f"Retrieving logs for pod '{pod_name}'...")
            try:
                full_logs = await asyncio.to_thread(
                    self.v1.read_namespaced_pod_log,
                    pod_name,
                    self.NAMESPACE,
                    container='script'
                )
                logger.debug(f"Raw logs retrieved for pod '{pod_name}'. Length: {len(full_logs)}")
            except ApiException as e:
                logger.warning(f"Could not retrieve logs for pod '{pod_name}': {e.status} {e.reason}")
                full_logs = f"Error retrieving logs: {e.status} {e.reason}"

            pod_status_phase_name: str = pod.status.phase if pod and pod.status else "Unknown"
            script_output, resource_usage = self._extract_execution_metrics(full_logs,
                                                                            execution_id,
                                                                            pod_status_phase_name)

            return script_output, pod.status.phase if pod and pod.status else "Unknown", resource_usage

        finally:
            logger.info(f"Initiating cleanup for resources related to execution '{execution_id}'...")
            await self._cleanup_resources(pod_name, config_map_name)
            if execution_id in self._active_pods:
                del self._active_pods[execution_id]

    def _extract_execution_metrics(self, logs: str, execution_id: str, pod_phase: str) -> tuple:
        default_metrics = {
            "execution_id": execution_id,
            "execution_time": 0.0,
            "cpu_usage": 0.0,
            "memory_usage": 0.0,
            "exit_code": 0 if pod_phase == "Succeeded" else 1,  # Best guess if metrics missing
            "status": pod_phase
        }
        try:
            pattern = r"###METRICS###\s*(\{.*?\})"
            match = re.search(pattern, logs,
                              re.DOTALL | re.MULTILINE)  # Ensure MULTILINE for ^$ if needed, DOTALL for . across lines
            if match:
                metrics_json = match.group(1).strip()
                logger.debug(f"Found metrics JSON for {execution_id}: {metrics_json}")
                metrics = json.loads(metrics_json)
                # Determine status based on exit code primarily
                # Default to error if exit code missing & pod failed
                exit_code = metrics.get("exit_code",
                                        1 if pod_phase != "Succeeded" else 0)
                computed_status = "completed" if exit_code == 0 else "error"  # Use 'error' status for non-zero exit
                metrics["status"] = computed_status
                metrics["pod_phase"] = pod_phase  # Add original pod phase for info
                output = re.sub(pattern, "", logs, flags=re.DOTALL | re.MULTILINE).strip()
                logger.info(f"Metrics successfully extracted for {execution_id}")
                return output, metrics
            else:
                logger.warning(f"Metrics marker not found in logs for {execution_id}. Pod phase: {pod_phase}")
                # Base status on pod phase if metrics missing
                default_metrics["status"] = "completed" if pod_phase == "Succeeded" else "error"
                return logs.strip(), default_metrics  # Return all logs as output if no marker
        except json.JSONDecodeError as e:
            logger.error(
                f"Failed to decode metrics JSON for {execution_id}: {str(e)}. "
                f"Raw JSON attempted: '{match.group(1).strip() if match else 'N/A'}'")
            default_metrics["status"] = "error"  # Mark as error if JSON parsing fails
            return logs.strip(), default_metrics
        except Exception as e:
            logger.error(f"Unexpected error parsing metrics for {execution_id}: {str(e)}")
            default_metrics["status"] = "error"  # Mark as error on unexpected failures
            return logs.strip(), default_metrics

    async def _create_config_map(self, config_map: k8s_client.V1ConfigMap) -> None:
        if not self.v1:
            raise KubernetesConfigError("Kubernetes client not initialized.")
        try:
            await asyncio.to_thread(
                self.v1.create_namespaced_config_map,
                namespace=self.NAMESPACE,
                body=config_map,
            )
            logger.info(f"ConfigMap '{config_map.metadata.name}' created successfully.")
        except ApiException as e:
            logger.error(f"Failed to create ConfigMap '{config_map.metadata.name}': {e.status} {e.reason} - {e.body}")
            raise KubernetesServiceError(f"Failed to create ConfigMap: {str(e)}") from e

    async def _create_namespaced_pod(self, pod_manifest: Dict[str, Any]) -> None:
        if not self.v1:
            raise KubernetesConfigError("Kubernetes client not initialized.")
        pod_name = pod_manifest.get("metadata", {}).get("name", "unknown-pod")
        try:
            await asyncio.to_thread(
                self.v1.create_namespaced_pod,
                body=pod_manifest,
                namespace=self.NAMESPACE,
            )
            logger.info(f"Pod '{pod_name}' created successfully.")
        except ApiException as e:
            logger.error(f"Failed to create pod '{pod_name}': {e.status} {e.reason} - {e.body}")
            raise KubernetesPodError(f"Failed to create pod: {str(e)}") from e

    async def _cleanup_resources(self, pod_name: str, config_map_name: str) -> None:
        if not self.v1:
            logger.error("Cannot cleanup resources, Kubernetes client not initialized.")
            return
        # Cleanup Pod
        try:
            await asyncio.to_thread(
                self.v1.delete_namespaced_pod,
                name=pod_name,
                namespace=self.NAMESPACE,
                grace_period_seconds=5,  # Reduce grace period for faster cleanup
                propagation_policy='Background'  # Start deletion quickly
            )
            logger.info(f"Deletion request sent for pod '{pod_name}'")
        except ApiException as e:
            if e.status != 404:  # Ignore if already deleted
                logger.error(f"Failed to delete pod '{pod_name}': {e.status} {e.reason}")
            else:
                logger.info(f"Pod '{pod_name}' already deleted or not found.")
        # Cleanup ConfigMap
        try:
            await asyncio.to_thread(
                self.v1.delete_namespaced_config_map,
                name=config_map_name,
                namespace=self.NAMESPACE,
                propagation_policy='Background'
            )
            logger.info(f"Deletion request sent for config map '{config_map_name}'")
        except ApiException as e:
            if e.status != 404:  # Ignore if already deleted
                logger.error(f"Failed to delete config map '{config_map_name}': {e.status} {e.reason}")
            else:
                logger.info(f"ConfigMap '{config_map_name}' already deleted or not found.")

    async def _cleanup_pod_resources(self, pod_name: str) -> None:
        if not pod_name.startswith("execution-"):
            logger.error(f"Unrecognized pod naming convention, cannot derive resources: {pod_name}")
            return
        execution_id = pod_name[len("execution-"):]
        config_map_name = f"script-{execution_id}"
        await self._cleanup_resources(pod_name, config_map_name)


def get_k8s_manager(request: Request) -> KubernetesServiceManager:
    if not hasattr(request.app.state, "k8s_manager"):
        logger.info("Creating new KubernetesServiceManager instance.")
        request.app.state.k8s_manager = KubernetesServiceManager()
    return request.app.state.k8s_manager  # type: ignore


def get_kubernetes_service(
        manager: KubernetesServiceManager = Depends(get_k8s_manager)
) -> KubernetesService:
    # Consider if KubernetesService should be a singleton or per-request
    # For now, assuming per-request is acceptable, but manager is singleton per app instance
    return KubernetesService(manager)
