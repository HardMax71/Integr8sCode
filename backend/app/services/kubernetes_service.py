import asyncio
import logging
import os

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.config import ConfigException
from app.config import get_settings

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
        pod_manifest = {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"execution-{execution_id}",
                "labels": {"app": "integr8scode", "execution_id": execution_id}
            },
            "spec": {
                "restartPolicy": "Never",
                "containers": [{
                    "name": "python",
                    "image": "python:3.9-slim",
                    "command": ["python", "-c", script],
                    "resources": {
                        "limits": {
                            "cpu": self.settings.K8S_POD_CPU_LIMIT,
                            "memory": self.settings.K8S_POD_MEMORY_LIMIT
                        },
                        "requests": {
                            "cpu": self.settings.K8S_POD_CPU_REQUEST,
                            "memory": self.settings.K8S_POD_MEMORY_REQUEST
                        }
                    }
                }]
            }
        }
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None,
                lambda: self.v1.create_namespaced_pod(body=pod_manifest, namespace="default")
            )
        except ApiException as e:
            logging.error(f"Exception when calling CoreV1Api->create_namespaced_pod: {e}")
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
