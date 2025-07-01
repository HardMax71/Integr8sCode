from typing import Any, Dict, List, Optional


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
            priority_class_name: Optional[str],
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
        self.priority_class_name = priority_class_name
        self.namespace = namespace

    def build(self) -> Dict[str, Any]:
        spec: Dict[str, Any] = {
            "containers": [
                {
                    "name": "script-runner",
                    "image": self.image,
                    "imagePullPolicy": "IfNotPresent",
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
        }

        if self.priority_class_name:
            spec["priorityClassName"] = self.priority_class_name

        pod_manifest: Dict[str, Any] = {
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
            "spec": spec,
        }

        return pod_manifest
