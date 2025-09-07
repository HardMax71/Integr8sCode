# CPU Time Measurement in Execution Pods

## Overview

The platform measures CPU time for executed scripts using Linux's jiffy-based accounting system. This document explains the limitations and characteristics of CPU time measurement, particularly for short-running processes.

## How CPU Time is Measured

### The Entrypoint Script

The `app/scripts/entrypoint.sh` script wraps all pod executions and captures resource metrics:

1. **Wall Clock Time**: Measured using `date +%s.%N` (nanosecond precision)
2. **CPU Time**: Sampled from `/proc/$PID/stat` fields 14 (user) and 15 (system) in jiffies
3. **Memory Usage**: Peak RSS from `/proc/$PID/status` VmHWM field

### Sampling Loop

```bash
while kill -0 "$PID" 2>/dev/null; do
    # Read CPU jiffies from /proc/$PID/stat
    CPU_JIFFIES=$(awk '{print $14+$15}' "/proc/$PID/stat" 2>/dev/null)
    # Sample every 5ms
    sleep 0.005
done
```

## The cpu_time_jiffies = 0 Problem

### Root Cause: Jiffy Granularity

Linux tracks CPU time in "jiffies" - discrete time units typically representing 10ms each (CLK_TCK=100Hz). This creates a fundamental limitation:

- **< 10ms CPU usage** → Reports as 0 jiffies
- **10-19ms CPU usage** → Reports as 1 jiffy
- **20-29ms CPU usage** → Reports as 2 jiffies

### Why Short Scripts Show 0 CPU Time

Many simple scripts show `cpu_time_jiffies: 0` despite measurable wall time:

| Script Type           | Wall Time | Actual CPU | Reported Jiffies |
|-----------------------|-----------|------------|------------------|
| `echo "Hello"`        | ~5ms      | <1ms       | 0                |
| `print("Hello")`      | ~20ms     | ~3ms       | 0                |
| `time.sleep(0.05)`    | ~50ms     | <1ms       | 0                |
| Simple math operation | ~10ms     | ~2ms       | 0                |

### The Disconnect: Wall Time vs CPU Time

- **Wall Time**: Total elapsed real-world time (includes waiting, I/O, sleep)
- **CPU Time**: Actual processor cycles consumed by the process

A script can run for 100ms wall time but use only 1ms of CPU if it's:
- Waiting for I/O operations
- Sleeping/blocked
- Waiting for system calls

## Additional Limitations

### 1. Sampling Race Conditions

For processes that complete in < 5ms:
- The sampling loop might never execute
- Process exits before first sample
- Result: JIFS remains at initial value of 0

### 2. Lost Final Accounting

When a process exits:
- The kernel performs final CPU accounting
- `/proc/$PID/stat` is immediately removed
- Final CPU time accumulation is lost

### 3. Process Startup Overhead

Short scripts spend proportionally more time in:
- Interpreter initialization (Python, Node.js)
- Library loading
- Process creation

This overhead often doesn't register as CPU time.

## Impact on Metrics

### CPU Utilization Calculation

With `cpu_time_jiffies = 0`:
```
cpu_utilization = (cpu_time_jiffies / CLK_TCK) / wall_time_seconds
                = (0 / 100) / 0.05
                = 0%
```

This appears as if the script used no CPU, which is technically accurate from the kernel's perspective but may be confusing to users.

### What This Means

- **Not a bug**: The measurement is accurate within Linux's accounting granularity
- **Expected behavior**: Short, simple scripts legitimately use < 1 jiffy of CPU
- **Limitation**: Cannot measure CPU usage for processes using < 10ms CPU time

## Recommendations

### For Users

1. **Understand the metrics**:
   - 0 CPU time doesn't mean the script didn't run
   - Wall time shows actual duration
   - CPU time shows processor usage

2. **For CPU measurement**:
   - Run longer or more complex scripts to see CPU usage
   - Batch multiple operations together
   - Use CPU-intensive operations for testing

### For Developers

1. **Alternative Approaches** (not currently implemented):
   - Use `/usr/bin/time` command which uses `wait3()` system call
   - Implement getrusage() wrapper for more accurate accounting
   - Use cgroups v2 CPU accounting for container-level metrics

2. **Display Considerations**:
   - Show "< 0.01s" instead of "0s" for small CPU times
   - Calculate CPU percentage only when cpu_time > 0
   - Document this limitation in user-facing interfaces

## Technical Details

### Jiffy Calculation

```bash
CLK_TCK=$(getconf CLK_TCK)  # Usually 100 Hz
cpu_seconds = cpu_time_jiffies / CLK_TCK
```

### Resource Usage Structure

The entrypoint script outputs:
```json
{
  "resource_usage": {
    "execution_time_wall_seconds": 0.052341,
    "cpu_time_jiffies": 0,
    "clk_tck_hertz": 100,
    "peak_memory_kb": 2048
  }
}
```

### Event Flow

1. Pod executes with entrypoint.sh wrapper
2. Script samples /proc during execution
3. JSON output captured from pod logs
4. PodEventMapper parses JSON via `_try_parse_json()`
5. Resource usage attached to ExecutionCompletedEvent
6. Metrics recorded in result processor

## Security Considerations

### CLK_TCK Disclosure

The `clk_tck_hertz` value is included in resource usage metrics. From a security perspective:

**Why it's included:**
- Required to convert jiffies to seconds: `cpu_seconds = cpu_time_jiffies / clk_tck_hertz`
- Allows proper CPU utilization calculation
- Provides transparency about measurement precision

**Security assessment:**
- **Low risk**: CLK_TCK is obtainable by any user via `getconf CLK_TCK`
- **Not privileged**: No special permissions required to access this value
- **Standard values**: Usually 100 Hz, occasionally 250/300/1000 Hz
- **Already accessible**: Users executing code could obtain it themselves

**Potential concerns (minimal):**
- **System fingerprinting**: Helps identify kernel configuration
- **Timing attacks**: Could theoretically aid in calibrating timing-based attacks
- **Information principle**: Discloses system implementation detail

**Conclusion**: The value is retained as it's necessary for metric interpretation and poses minimal security risk given that users already execute code in the environment.

## References

- Linux proc(5) man page - `/proc/[pid]/stat` documentation
- Linux time(7) man page - Time accounting overview
- getrusage(2) system call documentation
- Understanding Linux CPU accounting and jiffies
- sysconf(3) - System configuration variables