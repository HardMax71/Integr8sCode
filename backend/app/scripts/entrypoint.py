#!/usr/bin/env python3
import json
import resource
import subprocess
import sys
import time


def main():
    if len(sys.argv) < 2:
        print("Usage: entrypoint.py <command_to_run...>", file=sys.stderr)
        sys.exit(1)

    user_command = sys.argv[1:]
    start_time = time.perf_counter()

    # Use Popen for fine-grained control and to get the PID
    process = subprocess.Popen(
        user_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    peak_memory_kb = 0
    while process.poll() is None:
        try:
            # VmRSS in /proc/<pid>/status is a reliable way to get memory in KB
            with open(f"/proc/{process.pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        current_memory_kb = int(line.split()[1])
                        peak_memory_kb = max(peak_memory_kb, current_memory_kb)
                        break
        except (IOError, IndexError, ValueError):
            # Process might have just finished, which is fine.
            pass
        time.sleep(0.1)

    stdout_str, stderr_str = process.communicate()
    exit_code = process.returncode
    elapsed_time = time.perf_counter() - start_time

    # getrusage on the completed child is the most accurate way to get total CPU time.
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    total_cpu_time = usage.ru_utime + usage.ru_stime

    # --- Assemble and Print Final Output ---
    if stdout_str:
        print(stdout_str, end='')
    if stderr_str:
        print(stderr_str, file=sys.stderr, end='')

    metrics = {
        "execution_time": round(elapsed_time, 6),
        "cpu_usage": round(total_cpu_time, 6),
        "memory_usage": round(peak_memory_kb / 1024, 2),  # In MiB
        "exit_code": exit_code
    }

    print("\n###METRICS###")
    print(json.dumps(metrics))

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
