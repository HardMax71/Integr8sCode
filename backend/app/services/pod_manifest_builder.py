from datetime import datetime, timezone
from typing import Dict, Any


class PodManifestBuilder:
    """
    Responsible for building the Pod manifest YAML/JSON for Python script execution.
    """

    def __init__(
            self,
            python_version: str,
            execution_id: str,
            script_config_map_name: str,
            pod_cpu_limit: str,
            pod_cpu_request: str,
            pod_memory_limit: str,
            pod_memory_request: str,
            pod_execution_timeout: int,
            namespace: str = "default",
    ):
        self.python_version = python_version
        self.execution_id = execution_id
        self.script_config_map_name = script_config_map_name
        self.pod_cpu_limit = pod_cpu_limit
        self.pod_cpu_request = pod_cpu_request
        self.pod_memory_limit = pod_memory_limit
        self.pod_memory_request = pod_memory_request
        self.pod_execution_timeout = pod_execution_timeout
        self.namespace = namespace

    def build(self) -> Dict[str, Any]:
        """
        Returns a dictionary that can be passed directly to the K8s Python client
        or turned into YAML, representing a single Pod specification.
        """
        # Format timestamp in a k8s-compliant way
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H-%M-%S")
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"execution-{self.execution_id}",
                "labels": {
                    "app": "integr8scode",
                    "execution_id": self.execution_id,
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
                        "image": f"python:{self.python_version}-slim",
                        "imagePullPolicy": "IfNotPresent",
                        "command": [
                            "/bin/sh",
                            "-c",
                            f"timeout {self.pod_execution_timeout} python /scripts/script.py",
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
                                "cpu": self.pod_cpu_limit,
                                "memory": self.pod_memory_limit,
                            },
                            "requests": {
                                "cpu": self.pod_cpu_request,
                                "memory": self.pod_memory_request,
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
                        "configMap": {
                            "name": self.script_config_map_name,
                            "defaultMode": 0o444,
                        },
                    }
                ],
                "hostPID": False,
                "hostIPC": False,
                "hostNetwork": False,
                "dnsPolicy": "Default",
                "nodeSelector": {"kubernetes.io/os": "linux"},
            },
        }
