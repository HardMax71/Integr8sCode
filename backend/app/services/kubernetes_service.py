import asyncio
import logging
import os
import tempfile
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, Set
from fastapi import Depends, Request

from app.config import get_settings
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from app.core.logging import logger


class KubernetesServiceError(Exception):
    """Base exception for Kubernetes service errors"""

    pass


class KubernetesPodError(KubernetesServiceError):
    """Exception for pod-related errors"""

    pass


class KubernetesConfigError(KubernetesServiceError):
    """Exception for configuration-related errors"""

    pass


class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, reset_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.failures = 0
        self.last_failure_time: Optional[datetime] = None
        self.is_open = False

    def record_failure(self):
        self.failures += 1
        self.last_failure_time = datetime.utcnow()
        if self.failures >= self.failure_threshold:
            self.is_open = True
            logger.error(f"Circuit breaker opened after {self.failures} failures")

    def record_success(self):
        self.failures = 0
        self.last_failure_time = None
        self.is_open = False

    def should_allow_request(self) -> bool:
        if not self.is_open:
            return True

        if self.last_failure_time and (
            datetime.utcnow() - self.last_failure_time
        ) > timedelta(seconds=self.reset_timeout):
            self.is_open = False
            self.failures = 0
            return True

        return False


class KubernetesServiceManager:
    def __init__(self):
        self.services: Set[KubernetesService] = set()

    def register(self, service: "KubernetesService"):
        self.services.add(service)

    def unregister(self, service: "KubernetesService"):
        self.services.discard(service)

    async def shutdown_all(self):
        """Gracefully shutdown all managed services"""
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
    SHUTDOWN_TIMEOUT = 30  # seconds for graceful shutdown
    HEALTH_CHECK_INTERVAL = 60  # seconds

    def __init__(self, manager: KubernetesServiceManager):
        self.settings = get_settings()
        self.manager = manager
        self._initialize_kubernetes_client()
        self.circuit_breaker = CircuitBreaker()
        self._active_pods: Dict[str, datetime] = {}
        self._is_healthy = True
        self._last_health_check = datetime.utcnow()
        self.manager.register(self)

    def __del__(self):
        self.manager.unregister(self)

    async def check_health(self) -> bool:
        """Perform health check of the Kubernetes service"""
        try:
            if (
                datetime.utcnow() - self._last_health_check
            ).seconds < self.HEALTH_CHECK_INTERVAL:
                return self._is_healthy

            await asyncio.to_thread(self.version_api.get_code)
            self._is_healthy = True
            self.circuit_breaker.record_success()
            self._last_health_check = datetime.utcnow()
            return True
        except Exception as e:
            logger.error(f"Kubernetes health check failed: {str(e)}")
            self._is_healthy = False
            self.circuit_breaker.record_failure()
            self._last_health_check = datetime.utcnow()
            return False

    async def graceful_shutdown(self):
        """Gracefully shutdown the service"""
        shutdown_deadline = datetime.utcnow() + timedelta(seconds=self.SHUTDOWN_TIMEOUT)

        for pod_name, start_time in list(self._active_pods.items()):
            try:
                if datetime.utcnow() > shutdown_deadline:
                    logger.warning("Shutdown timeout reached, forcing pod termination")
                    break

                await self._cleanup_pod_resources(pod_name)
            except Exception as e:
                logger.error(f"Error during pod cleanup on shutdown: {str(e)}")

    def _initialize_kubernetes_client(self) -> None:
        """Initialize Kubernetes client with proper configuration"""
        try:
            self._setup_kubernetes_config()
            self._setup_api_client()
            self._test_api_connection()
        except Exception as e:
            raise KubernetesConfigError(
                f"Failed to initialize Kubernetes client: {str(e)}"
            )

    def _setup_kubernetes_config(self) -> None:
        """Set up Kubernetes configuration"""
        logging.info(f"KUBERNETES_CONFIG_PATH: {self.settings.KUBERNETES_CONFIG_PATH}")
        logging.info(
            f"KUBERNETES_CA_CERTIFICATE_PATH: {self.settings.KUBERNETES_CA_CERTIFICATE_PATH}"
        )

        if os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount"):
            config.load_incluster_config()
            logging.info("Using in-cluster Kubernetes configuration")
        else:
            config.load_kube_config(config_file=self.settings.KUBERNETES_CONFIG_PATH)
            logging.info(
                f"Using kubeconfig from {self.settings.KUBERNETES_CONFIG_PATH}"
            )

    def _setup_api_client(self) -> None:
        """Set up Kubernetes API client with proper SSL configuration"""
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

    def _test_api_connection(self) -> None:
        """Test connection to Kubernetes API"""
        try:
            version = self.version_api.get_code()
            logging.info(
                f"Successfully connected to Kubernetes API. Server version: {version.git_version}"
            )
        except ApiException as e:
            if e.status == 401:
                raise KubernetesConfigError(
                    "Authentication failed. Please check your token."
                )
            raise KubernetesConfigError(
                f"Failed to connect to Kubernetes API: {str(e)}"
            )

    def _create_pod_manifest(
        self, execution_id: str, config_map_name: str, python_version: str
    ) -> Dict[str, Any]:
        """Create pod manifest with security settings and health probes"""
        # Format timestamp in a k8s-compliant way
        timestamp = datetime.utcnow().strftime("%Y-%m-%d-%H-%M-%S")
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"execution-{execution_id}",
                "labels": {
                    "app": "integr8scode",
                    "execution_id": execution_id,
                    "created_at": timestamp,
                },
            },
            "spec": {
                "restartPolicy": "Never",
                "terminationGracePeriodSeconds": 30,
                "securityContext": {
                    "runAsNonRoot": True,
                    "runAsUser": 1000,
                    "runAsGroup": 3000,
                    "fsGroup": 2000,
                    "seccompProfile": {"type": "RuntimeDefault"},
                    "supplementalGroups": [4000],
                },
                "containers": [
                    {
                        "name": "python",
                        "image": f"python:{python_version}-slim",
                        "imagePullPolicy": "IfNotPresent",
                        "command": [
                            "/bin/sh",
                            "-c",
                            f"timeout {self.settings.K8S_POD_EXECUTION_TIMEOUT} python /scripts/script.py",
                        ],
                        "volumeMounts": [
                            {
                                "name": "script-volume",
                                "mountPath": "/scripts",
                                "readOnly": True,
                            }
                        ],
                        "resources": {
                            "limits": {
                                "cpu": self.settings.K8S_POD_CPU_LIMIT,
                                "memory": self.settings.K8S_POD_MEMORY_LIMIT,
                            },
                            "requests": {
                                "cpu": self.settings.K8S_POD_CPU_REQUEST,
                                "memory": self.settings.K8S_POD_MEMORY_REQUEST,
                            },
                        },
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {"drop": ["ALL"]},
                            "readOnlyRootFilesystem": True,
                            "seccompProfile": {"type": "RuntimeDefault"},
                        },
                        "lifecycle": {
                            "preStop": {
                                "exec": {"command": ["/bin/sh", "-c", "sleep 5"]}
                            }
                        },
                    }
                ],
                "volumes": [
                    {
                        "name": "script-volume",
                        "configMap": {"name": config_map_name, "defaultMode": 0o444},
                    }
                ],
                "hostPID": False,
                "hostIPC": False,
                "hostNetwork": False,
                "dnsPolicy": "Default",
                "nodeSelector": {"kubernetes.io/os": "linux"},
            },
        }

    async def create_execution_pod(
        self, execution_id: str, script: str, python_version: str
    ) -> None:
        """Create and execute a pod with the provided script"""
        if not self.circuit_breaker.should_allow_request():
            raise KubernetesServiceError("Service circuit breaker is open")

        if not await self.check_health():
            raise KubernetesServiceError("Kubernetes service is unhealthy")

        temp_file_path = None
        config_map_name = f"script-{execution_id}"

        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as temp_file:
                temp_file.write(script)
                temp_file_path = temp_file.name

            with open(temp_file_path, "r") as f:
                script_content = f.read()

            config_map = client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name=config_map_name),
                data={"script.py": script_content},
            )
            await self.create_config_map(config_map)

            pod_manifest = self._create_pod_manifest(
                execution_id, config_map_name, python_version
            )
            await self._create_namespaced_pod(pod_manifest)

            self._active_pods[execution_id] = datetime.utcnow()
            self.circuit_breaker.record_success()

        except Exception as e:
            self.circuit_breaker.record_failure()
            raise KubernetesPodError(f"Failed to create execution pod: {str(e)}")
        finally:
            if temp_file_path and os.path.exists(temp_file_path):
                os.unlink(temp_file_path)

    async def create_config_map(self, config_map: client.V1ConfigMap) -> None:
        """Create a ConfigMap in the cluster"""
        try:
            await asyncio.to_thread(
                self.v1.create_namespaced_config_map,
                namespace=self.NAMESPACE,
                body=config_map,
            )
        except ApiException as e:
            raise KubernetesServiceError(f"Failed to create ConfigMap: {str(e)}")

    async def _create_namespaced_pod(self, pod_manifest: Dict[str, Any]) -> None:
        """Create a pod in the namespace"""
        try:
            await asyncio.to_thread(
                self.v1.create_namespaced_pod,
                body=pod_manifest,
                namespace=self.NAMESPACE,
            )
        except ApiException as e:
            raise KubernetesPodError(f"Failed to create pod: {str(e)}")

    async def get_pod_logs(self, execution_id: str) -> str:
        """Get logs from the execution pod and clean up resources"""
        if not self.circuit_breaker.should_allow_request():
            raise KubernetesServiceError("Service circuit breaker is open")

        pod_name = f"execution-{execution_id}"
        config_map_name = f"script-{execution_id}"

        try:
            logs = await self._wait_for_pod_and_get_logs(pod_name)
            self.circuit_breaker.record_success()
            return logs
        finally:
            await self._cleanup_resources(pod_name, config_map_name)
            if execution_id in self._active_pods:
                del self._active_pods[execution_id]

    async def _wait_for_pod_and_get_logs(self, pod_name: str) -> str:
        """Wait for pod completion and return logs"""
        for _ in range(self.POD_RETRY_ATTEMPTS):
            pod = await asyncio.to_thread(
                self.v1.read_namespaced_pod, name=pod_name, namespace=self.NAMESPACE
            )
            if pod.status.phase in self.POD_SUCCESS_STATES:
                break
            await asyncio.sleep(self.POD_RETRY_INTERVAL)
        else:
            raise KubernetesPodError("Timeout waiting for pod to complete")

        return await asyncio.to_thread(
            self.v1.read_namespaced_pod_log, name=pod_name, namespace=self.NAMESPACE
        )

    async def _cleanup_resources(self, pod_name: str, config_map_name: str) -> None:
        """Clean up pod and config map resources"""
        try:
            # Delete pod with grace period
            await asyncio.to_thread(
                self.v1.delete_namespaced_pod,
                name=pod_name,
                namespace=self.NAMESPACE,
                grace_period_seconds=30,
            )
            logger.info(f"Successfully deleted pod {pod_name}")

            # Delete config map
            await asyncio.to_thread(
                self.v1.delete_namespaced_config_map,
                name=config_map_name,
                namespace=self.NAMESPACE,
            )
            logger.info(f"Successfully deleted config map {config_map_name}")
        except ApiException as e:
            if e.status != 404:  # Ignore "not found" errors
                logger.error(f"Failed to cleanup resources: {str(e)}")


def get_k8s_manager(request: Request) -> KubernetesServiceManager:
    if not hasattr(request.app.state, "k8s_manager"):
        request.app.state.k8s_manager = KubernetesServiceManager()
    return request.app.state.k8s_manager


def get_kubernetes_service(
    manager: KubernetesServiceManager = Depends(get_k8s_manager),
) -> KubernetesService:
    return KubernetesService(manager)
