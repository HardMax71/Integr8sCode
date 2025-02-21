from typing import Dict, Any
import textwrap

class PodManifestBuilder:
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
        # The wrapper runs the target script, calculates metrics,
        # and always exits with 0 so that the pod status is "Succeeded".
        # The actual exit code from the script is included in the metrics.
        wrapper_code = textwrap.dedent(f"""
            import time, resource, subprocess, sys, json
            start = time.time()
            timeout = {self.pod_execution_timeout}
            exit_code = 0
            try:
                result = subprocess.run(['python', '/scripts/script.py'],
                                          timeout=timeout,
                                          check=True,
                                          capture_output=True,
                                          text=True)
                print(result.stdout, end='')
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end='')
            except subprocess.TimeoutExpired:
                exit_code = 124
            except subprocess.CalledProcessError as e:
                if e.stdout:
                    print(e.stdout, end='')
                if e.stderr:
                    print(e.stderr, file=sys.stderr, end='')
                exit_code = e.returncode
            end = time.time()
            elapsed = end - start

            usage = resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu_time_used = usage.ru_utime + usage.ru_stime
            cpu_usage_m = (cpu_time_used / elapsed) * 1000 if elapsed > 0 else 0
            memory_used_mi = usage.ru_maxrss / 1024.0

            metrics = {{
                "execution_id": "{self.execution_id}",
                "execution_time": round(elapsed, 2),        # in seconds
                "cpu_usage": round(cpu_usage_m, 2),         # in m
                "memory_usage": round(memory_used_mi, 2),   # in Mi
                "exit_code": exit_code
            }}
            print("\\n###METRICS###")
            print(json.dumps(metrics))
            sys.exit(0)
        """)

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
                "shareProcessNamespace": True,
                "containers": [
                    {
                        "name": "script",
                        "image": f"python:{self.python_version}-slim",
                        "command": ["python", "-u", "-c", wrapper_code],
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
                        "volumeMounts": [
                            {"name": "script-volume", "mountPath": "/scripts"},
                        ],
                    }
                ],
                "volumes": [
                    {"name": "script-volume", "configMap": {"name": self.script_config_map_name}},
                ],
                "restartPolicy": "Never",
                "activeDeadlineSeconds": self.pod_execution_timeout,
            },
        }
