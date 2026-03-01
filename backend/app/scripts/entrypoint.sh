#!/bin/sh
#
# Strict, portable POSIX-sh entrypoint that runs an arbitrary
# command, captures its output, exit-code and coarse resource
# usage, then writes metrics to /dev/termination-log and
# length-prefixed stdout/stderr to container stdout.

# ---------- argument check --------------------------------------------------

if [ "$#" -eq 0 ]; then
    printf 'cpu_jiffies=0\nclk_tck=100\npeak_memory_kb=0\nwall_seconds=0\n' > /dev/termination-log
    ERR_MSG="Entrypoint Error: No command provided."
    printf 'STDOUT 0\nSTDERR %d\n%s' "${#ERR_MSG}" "$ERR_MSG"
    exit 127
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

# ---------- write resource metrics to termination log ----------------------

printf 'cpu_jiffies=%d\nclk_tck=%d\npeak_memory_kb=%d\nwall_seconds=%s\n' \
    "${JIFS:-0}" "${CLK_TCK:-100}" "${PEAK_KB:-0}" "${ELAPSED_S:-0}" \
    > /dev/termination-log

# ---------- write length-prefixed stdout/stderr ----------------------------

STDOUT_BYTES=$(wc -c < "$OUT")
STDERR_BYTES=$(wc -c < "$ERR")
printf 'STDOUT %d\n' "$STDOUT_BYTES"
cat "$OUT"
printf 'STDERR %d\n' "$STDERR_BYTES"
cat "$ERR"

exit "$EXIT_CODE"
