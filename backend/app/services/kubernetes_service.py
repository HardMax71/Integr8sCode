import asyncio
import logging
import os
import tempfile

from app.config import get_settings
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config import ConfigException


class KubernetesService:
    def __init__(self):
        self.settings = get_settings()
        try:
            config.load_kube_config(config_file=self.settings.KUBERNETES_CONFIG_PATH)
            self.v1 = client.CoreV1Api()
            logging.info(f"Successfully loaded Kubernetes config from {self.settings.KUBERNETES_CONFIG_PATH}")
        except ConfigException as e:
            logging.error(f"Error loading Kubernetes config: {e}")
            raise

    async def create_execution_pod(self, execution_id: str, script: str):
        # Create a temporary file with the script content
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(script)
            temp_file_path = temp_file.name

        try:
            # Create a ConfigMap to store the script
            config_map_name = f"script-{execution_id}"
            config_map = client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name=config_map_name),
                data={"script.py": open(temp_file_path, "r").read()}
            )

            await self.create_config_map(config_map)

            pod_manifest = {
                "apiVersion": "v1",
                "kind": "Pod",
                "metadata": {
                    "name": f"execution-{execution_id}",
                    "labels": {
                        "app": "integr8scode",
                        "execution_id": execution_id
                    }
                },
                "spec": {
                    "restartPolicy": "Never",
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 3000,
                        "fsGroup": 2000,
                        "seccompProfile": {
                            "type": "RuntimeDefault"  # Apply Seccomp profile
                        },
                        "supplementalGroups": [4000]
                    },
                    "containers": [{
                        "name": "python",
                        "image": "python:3.9-slim",
                        "imagePullPolicy": "IfNotPresent",
                        "command": [
                            "/bin/sh",
                            "-c",
                            f"timeout {self.settings.K8S_POD_EXECUTION_TIMEOUT} python /scripts/script.py"
                        ],
                        "volumeMounts": [
                            {
                                "name": "script-volume",
                                "mountPath": "/scripts",
                                "readOnly": True  # Mount ConfigMap as read-only
                            }
                        ],
                        "resources": {
                            "limits": {
                                "cpu": self.settings.K8S_POD_CPU_LIMIT,
                                "memory": self.settings.K8S_POD_MEMORY_LIMIT
                            },
                            "requests": {
                                "cpu": self.settings.K8S_POD_CPU_REQUEST,
                                "memory": self.settings.K8S_POD_MEMORY_REQUEST
                            }
                        },
                        "securityContext": {  # Container-level security context
                            "allowPrivilegeEscalation": False,
                            "capabilities": {
                                "drop": ["ALL"]  # Drop all capabilities
                            },
                            "readOnlyRootFilesystem": True,  # Ensure container filesystem is read-only
                            "seccompProfile": {
                                "type": "RuntimeDefault"
                            }
                        }
                    }],
                    "volumes": [
                        {
                            "name": "script-volume",
                            "configMap": {
                                "name": config_map_name,
                                "defaultMode": 0o444  # Set ConfigMap files as read-only
                            }
                        }
                    ],
                    "hostPID": False,  # Disable host PID namespace
                    "hostIPC": False,  # Disable host IPC namespace
                    "hostNetwork": False,  # Disable host networking
                    "dnsPolicy": "Default",  # Use default DNS policy
                    "nodeSelector": {
                        "kubernetes.io/os": "linux"  # Ensure Pod runs on Linux nodes
                    }
                }
            }

            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.v1.create_namespaced_pod(body=pod_manifest, namespace="default")
            )
        except ApiException as e:
            logging.error(f"Exception when calling CoreV1Api->create_namespaced_pod: {e}")
            raise
        finally:
            # Clean up the temporary file
            os.unlink(temp_file_path)

    async def create_config_map(self, config_map):
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self.v1.create_namespaced_config_map(namespace="default", body=config_map)
            )
        except ApiException as e:
            logging.error(f"Exception when calling CoreV1Api->create_namespaced_config_map: {e}")
            raise

    async def get_pod_logs(self, execution_id: str) -> str:
        pod_name = f"execution-{execution_id}"
        loop = asyncio.get_event_loop()
        try:
            # Wait for the pod to be in a state where logs can be read
            for _ in range(60):  # Wait up to 60 seconds
                pod = await loop.run_in_executor(
                    None,
                    lambda: self.v1.read_namespaced_pod(name=pod_name, namespace="default")
                )
                if pod.status.phase in ['Running', 'Succeeded', 'Failed']:
                    break
                await asyncio.sleep(1)
            else:
                raise Exception("Timeout waiting for pod to be ready")

            logs = await loop.run_in_executor(
                None,
                lambda: self.v1.read_namespaced_pod_log(name=pod_name, namespace="default")
            )
            await loop.run_in_executor(
                None,
                lambda: self.v1.delete_namespaced_pod(name=pod_name, namespace="default")
            )
            return logs
        except ApiException as e:
            logging.error(f"Exception when interacting with pod {pod_name}: {e}")
            raise


def get_kubernetes_service() -> KubernetesService:
    return KubernetesService()
