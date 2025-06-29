from typing import Any, Dict, List


class PodManifestBuilder:
    def __init__(
            self,
            execution_id: str,
            config_map_name: str,
            image: str,
            command: List[str],
            pod_cpu_limit: str,
            pod_cpu_request: str,
            pod_memory_limit: str,
            pod_memory_request: str,
            pod_execution_timeout: int,
            namespace: str = "default",
    ):
        self.execution_id = execution_id
        self.config_map_name = config_map_name
        self.image = image
        self.command = command
        self.pod_cpu_limit = pod_cpu_limit
        self.pod_cpu_request = pod_cpu_request
        self.pod_memory_limit = pod_memory_limit
        self.pod_memory_request = pod_memory_request
        self.pod_execution_timeout = pod_execution_timeout
        self.namespace = namespace

    def build(self) -> Dict[str, Any]:
        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"execution-{self.execution_id}",
                "namespace": self.namespace,
                "labels": {
                    "app": "script-execution",
                    "execution-id": self.execution_id,
                },
            },
            "spec": {
                "containers": [
                    {
                        "name": "script-runner",
                        "image": self.image,
                        "imagePullPolicy": "IfNotPresent",  # Only if not available locally
                        "command": self.command,
                        "args": [],
                        "resources": {
                            "limits": {"cpu": self.pod_cpu_limit, "memory": self.pod_memory_limit},
                            "requests": {"cpu": self.pod_cpu_request, "memory": self.pod_memory_request},
                        },
                        "volumeMounts": [
                            {"name": "script-volume", "mountPath": "/scripts"},
                        ],
                    }
                ],
                "volumes": [
                    {
                        "name": "script-volume",
                        "configMap": {
                            "name": self.config_map_name,
                            "defaultMode": 0o755
                        }
                    },
                ],
                "restartPolicy": "Never",
                "activeDeadlineSeconds": self.pod_execution_timeout + 5,
            },
        }
