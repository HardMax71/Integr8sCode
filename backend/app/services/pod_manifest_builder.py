import textwrap
from typing import Any, Dict
import resource

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
        # The wrapper runs the target script, calculates metrics using the resource module.
        # If the target script times out or fails, the wrapper will exit with a non-zero code,
        # causing the pod status to reflect the failure (e.g., "Error").
        # Metrics are still printed before exiting.
        # Manual about clock used: https://docs.python.org/3/library/time.html#time.perf_counter
        # Manual about resource usage: https://docs.python.org/3/library/resource.html
        # resource.getrusage(resource.RUSAGE_CHILDREN) gets metrics for waited-for children.
        # ru_maxrss is typically in KiB on Linux, ru_utime/ru_stime are in seconds.
        wrapper_code = textwrap.dedent(f"""
import time, subprocess, sys, json, os, resource

exit_code = 0 # Assume success initially
timeout = {self.pod_execution_timeout}
elapsed = 0.0
cpu_usage_millicores = 0.0
memory_used_mi = 0.0
process_result = None # To store subprocess result or exception info

try:
    start_time = time.perf_counter()

    process_result = subprocess.run(
        ['python', '/scripts/script.py'],
        timeout=timeout,
        check=True,         # Raise CalledProcessError on non-zero exit code
        capture_output=True,
        text=True
    )

    # If run completes successfully, exit_code remains 0
    print(process_result.stdout, end='')
    if process_result.stderr:
        print(process_result.stderr, file=sys.stderr, end='')


except subprocess.TimeoutExpired as e:
    # subprocess.TimeoutExpired doesn't have "returncode". Use 124 standardly (timeout signal).
    exit_code = 124
    process_result = e # Store exception
    print(f"Script timed out after {{timeout}} seconds.", file=sys.stderr)
    # Print any captured output before timeout
    if hasattr(e, 'stdout') and e.stdout:
        print(e.stdout, end='')
    if hasattr(e, 'stderr') and e.stderr:
        print(e.stderr, file=sys.stderr, end='')


except subprocess.CalledProcessError as e:
    # Script executed but returned a non-zero exit code
    exit_code = e.returncode
    process_result = e # Store exception
    print(f"Script failed with exit code {{exit_code}}.", file=sys.stderr)
    # Print output from the failed script
    if e.stdout:
        print(e.stdout, end='')
    if e.stderr:
        print(e.stderr, file=sys.stderr, end='')


except Exception as e:
    # Catch other potential exceptions during subprocess.run or setup
    exit_code = 1 # General wrapper/execution error
    process_result = e # Store exception
    print(f"Wrapper error during script execution: {{e}}", file=sys.stderr)
    # No stdout/stderr guaranteed on 'e' here

finally:
    # Measure elapsed time regardless of outcome
    # Use start_time if it was set, otherwise elapsed remains 0
    if 'start_time' in locals():
        end_time = time.perf_counter()
        elapsed = end_time - start_time
    else:
        # Handle case where exception occurred before start_time was set
        elapsed = 0.0

    try:
        # Get resource usage for all waited-for children
        # This captures the total usage of the 'python /scripts/script.py' process if it ran
        usage = resource.getrusage(resource.RUSAGE_CHILDREN)

        # Total CPU time (user + system) in seconds
        total_cpu_time_sec = usage.ru_utime + usage.ru_stime

        # Calculate average CPU usage in millicores over the elapsed wall-clock time
        # Avoid division by zero if elapsed time is negligible or script failed instantly
        cpu_usage_millicores = 0 if elapsed < 1e-9 else (total_cpu_time_sec / elapsed) * 1000

        # Max resident set size (peak memory usage). Typically in KiB on Linux.
        # Convert KiB to MiB (1 MiB = 1024 KiB)
        memory_used_mi = usage.ru_maxrss / 1024.0

    except Exception as res_e:
         # Only print error if resource retrieval failed; keep previous exit_code
         print(f"Wrapper error retrieving resource usage: {{res_e}}", file=sys.stderr)
         # Keep default metric values (0.0) or previously calculated ones if applicable

    # --- Metrics Generation ---
    metrics = {{
        "execution_id": "{self.execution_id}",
        "execution_time": round(elapsed, 6),
        "cpu_usage": round(cpu_usage_millicores, 2), # In millicores
        "memory_usage": round(memory_used_mi, 2),   # In MiB
        "exit_code": exit_code # The actual exit code (0 for success, 124 for timeout, non-zero for script error)
    }}
    # Ensure metrics are printed even on failure, separated from other output
    print("\\n###METRICS###")
    print(json.dumps(metrics))

    # --- Exit with actual code ---
    # Exit with the captured exit_code. This will make the pod status reflect
    # failure (Error/Failed) if the script timed out or returned non-zero.
    sys.exit(exit_code)
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
                # +5s to allow catch-block to raise error in cause of timeout
                "activeDeadlineSeconds": self.pod_execution_timeout + 5,
            },
        }