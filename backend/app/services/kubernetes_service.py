import asyncio
import logging
import os
import tempfile
from typing import Dict, Any

from app.config import get_settings
from kubernetes import client, config
from kubernetes.client.rest import ApiException


class KubernetesServiceError(Exception):
    """Base exception for Kubernetes service errors"""

    pass


class KubernetesPodError(KubernetesServiceError):
    """Exception for pod-related errors"""

    pass


class KubernetesConfigError(KubernetesServiceError):
    """Exception for configuration-related errors"""

    pass


class KubernetesService:
    NAMESPACE = "default"
    POD_RETRY_ATTEMPTS = 60
    POD_RETRY_INTERVAL = 1
    POD_SUCCESS_STATES = {"Succeeded", "Failed"}

    def __init__(self):
        self.settings = get_settings()
        self._initialize_kubernetes_client()

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
        """Create pod manifest with security settings"""
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"execution-{execution_id}",
                "labels": {"app": "integr8scode", "execution_id": execution_id},
            },
            "spec": {
                "restartPolicy": "Never",
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
        temp_file_path = None
        config_map_name = f"script-{execution_id}"

        try:
            # Create temporary file
            with tempfile.NamedTemporaryFile(
                    mode="w", suffix=".py", delete=False
            ) as temp_file:
                temp_file.write(script)
                temp_file_path = temp_file.name

            # Create ConfigMap
            with open(temp_file_path, "r") as f:
                script_content = f.read()

            config_map = client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name=config_map_name),
                data={"script.py": script_content},
            )
            await self.create_config_map(config_map)

            # Create Pod
            pod_manifest = self._create_pod_manifest(
                execution_id, config_map_name, python_version
            )
            await self._create_namespaced_pod(pod_manifest)

        except Exception as e:
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
        pod_name = f"execution-{execution_id}"
        config_map_name = f"script-{execution_id}"

        try:
            # Wait for pod completion
            logs = await self._wait_for_pod_and_get_logs(pod_name)
            return logs
        finally:
            # Cleanup resources
            await self._cleanup_resources(pod_name, config_map_name)

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
            # Delete pod
            await asyncio.to_thread(
                self.v1.delete_namespaced_pod, name=pod_name, namespace=self.NAMESPACE
            )
            logging.info(f"Successfully deleted pod {pod_name}")

            # Delete config map
            await asyncio.to_thread(
                self.v1.delete_namespaced_config_map,
                name=config_map_name,
                namespace=self.NAMESPACE,
            )
            logging.info(f"Successfully deleted config map {config_map_name}")
        except ApiException as e:
            if e.status != 404:  # Ignore "not found" errors
                logging.error(f"Failed to cleanup resources: {str(e)}")


def get_kubernetes_service() -> KubernetesService:
    return KubernetesService()
