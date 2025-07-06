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
            "initContainers": [
                {
                    "name": "copy-script",
                    "image": "busybox:1.36",          # tiny & always available
                    "command": ["/bin/sh", "-c",
                                "cp /cfg/* /scripts/ && chmod 555 /scripts/*"],
                    "volumeMounts": [
                        {"name": "script-config", "mountPath": "/cfg", "readOnly": True},
                        {"name": "script-volume",  "mountPath": "/scripts"}
                    ]
                }
            ],
            "containers": [
                {
                    "name": "script-runner",
                    "image": self.image,
                    "imagePullPolicy": "IfNotPresent",
                    "command": self.command,
                    "resources": {
                        "limits":   {"cpu": self.pod_cpu_limit,
                                     "memory": self.pod_memory_limit},
                        "requests": {"cpu": self.pod_cpu_request,
                                     "memory": self.pod_memory_request},
                    },
                    "volumeMounts": [
                        {"name": "script-volume",   "mountPath": "/scripts", "readOnly": True},
                        {"name": "entrypoint-vol",  "mountPath": "/entry",   "readOnly": True},
                        {"name": "writable-tmp",    "mountPath": "/tmp"}
                    ],
                    "terminationMessagePolicy": "FallbackToLogsOnError",
                    "securityContext": {
                        "readOnlyRootFilesystem": True,
                        "allowPrivilegeEscalation": False,
                        "runAsNonRoot": True,
                        "runAsUser": 1000,
                        "runAsGroup": 1000,
                        "capabilities": {
                            "drop": ["ALL"]
                        }
                    }
                }
            ],
            "volumes": [
                {"name": "script-volume",   "emptyDir": {}},
                {"name": "script-config",   "configMap": {"name": self.config_map_name}},
                {"name": "entrypoint-vol",  "configMap": {"name": self.config_map_name}},
                {"name": "writable-tmp",    "emptyDir": {}}
            ],
            "restartPolicy": "Never",
            "activeDeadlineSeconds": self.pod_execution_timeout + 1,
            "hostNetwork": False,
            "hostPID": False,
            "hostIPC": False,
            "dnsPolicy": "None",
            "dnsConfig": {
                "nameservers": ["127.0.0.1"],
                "searches": [],
                "options": []
            },
        }

        if self.priority_class_name:
            spec["priorityClassName"] = self.priority_class_name

        return {
            "apiVersion": "v1",
            "kind": "Pod",
            "metadata": {
                "name": f"execution-{self.execution_id}",
                "namespace": self.namespace,
                "labels": {"app": "script-execution",
                           "execution-id": self.execution_id},
            },
            "spec": spec,
        }


