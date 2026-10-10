# CPU time measurement

Every executor pod runs the user's command under [entrypoint.sh](https://github.com/HardMax71/Integr8sCode/blob/main/backend/app/scripts/entrypoint.sh), a POSIX sh wrapper started as `/bin/sh /entry/entrypoint.sh <runtime command>`. It measures wall time, CPU time and peak memory, and hands the results back through two channels: the container's termination message and its stdout.

## What the wrapper does

It starts the command in the background with stdout and stderr redirected to temp files, then polls `/proc/$PID` every 5 ms while the process is alive. Each sample reads `VmHWM` from `/proc/$PID/status` for peak RSS and fields 14 and 15 of `/proc/$PID/stat` (user plus system time, in jiffies) for CPU. Wall time is the difference of two `date +%s.%N` readings. `CLK_TCK` comes from `getconf`, falling back to 100.

When the command exits, the wrapper writes `key=value` lines to `/dev/termination-log`:

```text
exit_code=0
cpu_jiffies=3
clk_tck=100
peak_memory_kb=9216
wall_seconds=0.052341
```

Then it prints the captured output to stdout, each stream framed by a header with its length in bytes:

```text
STDOUT <bytes>
<stdout>STDERR <bytes>
<stderr>
```

The wrapper itself always exits 0, so the real exit code travels in the termination message. If it's called with no command, it writes `exit_code=127` and an error message in the same format.

## How the backend reads it

The pod monitor's `PodEventMapper` picks this up once the container has terminated. `_parse_termination_message` splits the termination message into a dict, and `_parse_framed_output` cuts stdout and stderr out of the pod log by the length headers. If the framing can't be parsed, both streams come back empty. The values end up in `ResourceUsageDomain` (`execution_time_wall_seconds`, `cpu_time_jiffies`, `clk_tck_hertz`, `peak_memory_kb`) on the completion event, and the result processor stores them with the execution.

The editor's output panel converts jiffies to milliseconds with `clk_tck_hertz`.

## Why short scripts show zero CPU

Linux accounts CPU time in jiffies, which are 10 ms at the usual `CLK_TCK` of 100. A script that uses less than 10 ms of CPU reports 0, one that uses 10 to 19 ms reports 1, and so on. A `print("hello")` usually lands at 0 even though its wall time is tens of milliseconds. The output panel shows that case as `< 10 m` instead of zero.

Two more effects push short runs toward 0. A process that finishes before the first 5 ms sample is never read at all. And `/proc/$PID/stat` disappears the moment the process exits, so CPU time used after the last sample is lost.

Wall time and CPU time measure different things anyway. Wall time includes sleeping, I/O and waiting; CPU time only counts cycles the process actually used. A script that sleeps for a second has a wall time of about a second and almost no CPU.

## Exposing CLK_TCK

`clk_tck_hertz` is part of the result because jiffies mean nothing without it. It's not a secret: any process can read it with `getconf CLK_TCK`, and users already run arbitrary code in the same environment.

See [proc(5)](https://man7.org/linux/man-pages/man5/proc.5.html) for the `/proc/[pid]/stat` fields and [time(7)](https://man7.org/linux/man-pages/man7/time.7.html) for how the kernel accounts time.
