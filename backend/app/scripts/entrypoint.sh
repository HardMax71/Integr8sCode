#!/bin/sh
#
# Strict, portable POSIX-sh entrypoint that runs an arbitrary
# command, captures its output, exit-code and coarse resource
# usage, then prints a single-line JSON blob to stdout.

# Very small, POSIX-compliant JSON string escaper
json_escape() {
    sed -e ':a;N;$!ba' \
        -e 's/\\/\\\\/g'  \
        -e 's/"/\\"/g'   \
        -e 's/\n/\\n/g'  \
        -e 's/\t/\\t/g'  \
        -e 's/\r/\\r/g'
}

# ---------- argument check --------------------------------------------------

if [ "$#" -eq 0 ]; then
    printf '{"exit_code":127,"resource_usage":null,"stdout":"","stderr":"Entrypoint Error: No command provided."}'
    exit 0
fi

# ---------- temp files & timing --------------------------------------------

set -e
OUT="$(mktemp -t out.XXXXXX)"   || exit 1
ERR="$(mktemp -t err.XXXXXX)"   || exit 1
trap 'rm -f "$OUT" "$ERR"' EXIT
set +e

START_TIME="$(date +%s.%N)"

# ---------- run user command in the background -----------------------------

( "$@" >"$OUT" 2>"$ERR" ) &
PID=$!

CLK_TCK="$(getconf CLK_TCK 2>/dev/null || printf '100')"
PEAK_KB=0
JIFS=0

# ---------- lightweight sampling loop --------------------------------------

# `kill -0` succeeds while the process is alive but does not send a signal.
while kill -0 "$PID" 2>/dev/null; do
    # peak-RSS (VmHWM)
    CUR_KB=$(grep VmHWM "/proc/$PID/status" 2>/dev/null | awk '{print $2}')
    if [ -n "$CUR_KB" ] && [ "$CUR_KB" -gt "$PEAK_KB" ]; then
        PEAK_KB=$CUR_KB
    fi

    # user + sys CPU time (jiffies)
    CPU_JIFFIES=$(awk '{print $14+$15}' "/proc/$PID/stat" 2>/dev/null)
    if [ -n "$CPU_JIFFIES" ]; then
        JIFS=$CPU_JIFFIES
    fi

    # 5 ms sampling interval
    sleep 0.005
done

# ---------- reap child & compute metrics -----------------------------------

wait "$PID"
EXIT_CODE=$?

END_TIME="$(date +%s.%N)"
ELAPSED_S=$(printf '%s\n' "$END_TIME $START_TIME" | awk '{printf "%.6f",$1-$2}')

# ---------- emit single-line JSON ------------------------------------------

# Build JSON on a single line
# Note: CLK_TCK included for CPU time conversion (cpu_seconds = jiffies / clk_tck)
# Security: CLK_TCK is obtainable by any user via getconf, not sensitive
printf '{"exit_code":%d,"resource_usage":{"execution_time_wall_seconds":%s,"cpu_time_jiffies":%d,"clk_tck_hertz":%d,"peak_memory_kb":%d},"stdout":"%s","stderr":"%s"}' \
    "${EXIT_CODE:-1}" \
    "${ELAPSED_S:-0}" \
    "${JIFS:-0}" \
    "${CLK_TCK:-100}" \
    "${PEAK_KB:-0}" \
    "$(cat "$OUT" | json_escape)" \
    "$(cat "$ERR" | json_escape)"
