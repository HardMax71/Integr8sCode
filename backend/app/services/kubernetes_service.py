import asyncio
import logging
import os
import tempfile

from app.config import get_settings
from kubernetes import client, config
from kubernetes.client.rest import ApiException



class KubernetesService:
    def __init__(self):
        self.settings = get_settings()
        try:
            logging.info(f"KUBERNETES_CONFIG_PATH: {self.settings.KUBERNETES_CONFIG_PATH}")
            logging.info(f"KUBERNETES_CA_CERTIFICATE_PATH: {self.settings.KUBERNETES_CA_CERTIFICATE_PATH}")

            if os.path.exists('/var/run/secrets/kubernetes.io/serviceaccount'):
                config.load_incluster_config()
                logging.info("Using in-cluster Kubernetes configuration")
            else:
                config.load_kube_config(config_file=self.settings.KUBERNETES_CONFIG_PATH)
                logging.info(f"Using kubeconfig from {self.settings.KUBERNETES_CONFIG_PATH}")

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

            logging.info(f"Kubernetes API server: {configuration.host}")
            logging.info(f"Using token authentication: {bool(configuration.api_key)}")
            logging.info(f"API Key prefix: {configuration.api_key_prefix}")

            # Test API connection
            try:
                version = self.version_api.get_code()
                logging.info(f"Successfully connected to Kubernetes API. Server version: {version.git_version}")
            except ApiException as e:
                logging.error(f"Error getting Kubernetes version: {e}")
                if e.status == 401:
                    logging.error("Authentication failed. Please check your token.")
                raise

        except Exception as e:
            logging.error(f"Error in Kubernetes configuration: {str(e)}")
            raise

    async def create_execution_pod(self, execution_id: str, script: str, python_version: str):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as temp_file:
            temp_file.write(script)
            temp_file_path = temp_file.name

        try:
            config_map_name = f"script-{execution_id}"
            with open(temp_file_path, "r") as f:
                script_content = f.read()

            config_map = client.V1ConfigMap(
                metadata=client.V1ObjectMeta(name=config_map_name),
                data={"script.py": script_content}
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
                            "type": "RuntimeDefault"
                        },
                        "supplementalGroups": [4000]
                    },
                    "containers": [{
                        "name": "python",
                        "image": f"python:{python_version}-slim",
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
                                "readOnly": True
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
                        "securityContext": {
                            "allowPrivilegeEscalation": False,
                            "capabilities": {
                                "drop": ["ALL"]
                            },
                            "readOnlyRootFilesystem": True,
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
                                "defaultMode": 0o444
                            }
                        }
                    ],
                    "hostPID": False,
                    "hostIPC": False,
                    "hostNetwork": False,
                    "dnsPolicy": "Default",
                    "nodeSelector": {
                        "kubernetes.io/os": "linux"
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

    async def get_pod_logs(self, execution_id: str):
        pod_name = f"execution-{execution_id}"
        namespace = "default"
        loop = asyncio.get_event_loop()
        try:
            # Wait for pod to complete
            for _ in range(60):
                pod = await loop.run_in_executor(
                    None,
                    lambda: self.v1.read_namespaced_pod(name=pod_name, namespace=namespace)
                )
                if pod.status.phase in ['Succeeded', 'Failed']:
                    break
                await asyncio.sleep(1)
            else:
                raise Exception("Timeout waiting for pod to complete")

            # Get pod logs
            logs = await loop.run_in_executor(
                None,
                lambda: self.v1.read_namespaced_pod_log(name=pod_name, namespace=namespace)
            )

            return logs
        except ApiException as e:
            if e.status == 404:
                logging.error(f"Pod {pod_name} not found. It might have been deleted already.")
            else:
                logging.error(f"Exception when interacting with pod {pod_name}: {e}")
            raise
        finally:
            # Always attempt to delete the pod, even if an exception occurred
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self.v1.delete_namespaced_pod(name=pod_name, namespace=namespace)
                )
                logging.info(f"Successfully deleted pod {pod_name}")
            except ApiException as delete_error:
                if delete_error.status == 404:
                    logging.warning(
                        f"Pod {pod_name} not found when attempting to delete. It may have been deleted already.")
                else:
                    logging.error(f"Failed to delete pod {pod_name}: {delete_error}")


def get_kubernetes_service() -> KubernetesService:
    return KubernetesService()
