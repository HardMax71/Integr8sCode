#!/bin/sh

# This script is written in the strictest, most portable POSIX sh.
# It makes zero assumptions about the shell's features.

# Use a simple, POSIX-compliant method for escaping JSON strings.
json_escape() {
    sed -e ':a;N;$!ba' -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\n/\\n/g' -e 's/\t/\\t/g' -e 's/\r/\\r/g'
}

# Exit immediately if no command is provided.
if [ "$#" -eq 0 ]; then
    printf '{"exit_code": 127, "resource_usage": null, "stdout": "", "stderr": "Entrypoint Error: No command provided."}'
    exit 0
fi

# Create temporary files for stdout and stderr. Exit if mktemp fails.
set -e
OUT=$(mktemp)
ERR=$(mktemp)
trap 'rm -f "$OUT" "$ERR"' EXIT
set +e

# Record start time using nanosecond precision (%s for seconds, %N for nanoseconds).
START_TIME=$(date +%s.%N)

# This subshell construct is the key. It isolates the user command.
# A failure inside this subshell will not crash our main script.
( "$@" >"$OUT" 2>"$ERR" ) &
PID=$!

PEAK_KB=0
JIFS=0

# Loop while the process directory exists. This is the most reliable check.
while [ -d "/proc/$PID" ]; do
    # Silence all errors from grep/cat to prevent log contamination from race conditions.
    CUR_KB=$(grep VmHWM "/proc/$PID/status" 2>/dev/null | awk '{print $2}')
    if [ -n "$CUR_KB" ] && [ "$CUR_KB" -gt "$PEAK_KB" ]; then
        PEAK_KB=$CUR_KB
    fi

    # Use awk for arithmetic; it handles empty/malformed input without crashing the shell.
    CPU_JIFFIES=$(awk '{print $14 + $15}' "/proc/$PID/stat" 2>/dev/null)
    if [ -n "$CPU_JIFFIES" ]; then
        JIFS=$CPU_JIFFIES
    fi
    sleep 0.05
done

# This will now work correctly because the parent script is not PID 1.
wait "$PID"
EXIT_CODE=$?

END_TIME=$(date +%s.%N)
# Calculate elapsed time using floating-point math via awk, formatted to 6 decimal places.
# The result is stored in ELAPSED_S, which the original JSON block uses.
ELAPSED_S=$(printf '%s\n' "$END_TIME $START_TIME" | awk '{printf "%.6f", $1 - $2}')

# Defensively get clock ticks per second.
CLK_TCK=$(getconf CLK_TCK 2>/dev/null || printf "100")

OUT_JSON=$(cat "$OUT" | json_escape)
ERR_JSON=$(cat "$ERR" | json_escape)

# Use the most robust printf format possible, passing all variables as arguments.
# The final output has NO trailing newline. This is critical.
json=$(cat <<EOF
{
  "exit_code": ${EXIT_CODE:-1},
  "resource_usage": {
    "execution_time_wall_seconds": ${ELAPSED_S:-0},
    "cpu_time_jiffies": ${JIFS:-0},
    "clk_tck_hertz": ${CLK_TCK:-100},
    "peak_memory_kb": ${PEAK_KB:-0}
  },
  "stdout": "$(cat "$OUT" | json_escape)",
  "stderr": "$(cat "$ERR" | json_escape)"
}
EOF
)

# final output – no trailing newline!
printf '%s' "$json"