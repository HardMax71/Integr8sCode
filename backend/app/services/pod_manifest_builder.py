import textwrap
from typing import Dict, Any


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
        # Manual about clock used: https://docs.python.org/3/library/time.html#time.perf_counter
        wrapper_code = textwrap.dedent(f"""
            import time, subprocess, sys, json, os
            
            def read_cpu_usage():
                with open('/sys/fs/cgroup/cpuacct/cpuacct.usage', 'r') as f:
                    return int(f.read().strip())
            
            def read_memory_usage():
                with open('/sys/fs/cgroup/memory/memory.usage_in_bytes', 'r') as f:
                    return int(f.read().strip())
            
            exit_code = 0
            timeout = {self.pod_execution_timeout}
            
            # Measure only the subprocess execution.
            try:
                start_time = time.perf_counter()
                start_cpu = read_cpu_usage()
                
                result = subprocess.run(
                    ['python', '/scripts/script.py'],
                    timeout=timeout,
                    check=True,
                    capture_output=True,
                    text=True
                )
                
                print(result.stdout, end='')
                if result.stderr:
                    print(result.stderr, file=sys.stderr, end='')
            
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as e:
                # subprocess.TimeoutExpired doesn't have an attr "returncode -> returning 124
                exit_code = getattr(e, "returncode", 124)
                
                if e.stdout:
                    print(e.stdout, end='')
                if e.stderr:
                    print(e.stderr, file=sys.stderr, end='')
            finally:
                # Not the best idea to measure here cause prints also take place, but still working
                end_time = time.perf_counter()
                end_cpu = read_cpu_usage()
            
            elapsed = end_time - start_time
            cpu_used_ns = end_cpu - start_cpu
            cpu_usage_millicores = 0 if elapsed < 1e-9 else (cpu_used_ns / (elapsed * 1e9)) * 1000
            memory_used_mi = read_memory_usage() / (1024 * 1024)
            
            metrics = {{
                "execution_id": "{self.execution_id}",
                "execution_time": round(elapsed, 6),
                "cpu_usage": round(cpu_usage_millicores, 2),
                "memory_usage": round(memory_used_mi, 2),
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
