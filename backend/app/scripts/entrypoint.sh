#!/bin/sh
#
# Strict, portable POSIX-sh entrypoint that runs an arbitrary
# command, captures its output, exit-code and coarse resource
# usage, then writes metrics to /dev/termination-log and
# length-prefixed stdout/stderr to container stdout.

# Both streams travel in one Kafka message (1 MiB by default), and /tmp is 10Mi for most runtimes.
MAX_STREAM_BYTES=262144

# ---------- argument check --------------------------------------------------

if [ "$#" -eq 0 ]; then
    printf 'exit_code=127\ncpu_jiffies=0\nclk_tck=100\npeak_memory_kb=0\nwall_seconds=0\n' > /dev/termination-log
    ERR_MSG="Entrypoint Error: No command provided."
    printf 'STDOUT 0\nSTDERR %d\n%s' "${#ERR_MSG}" "$ERR_MSG"
    exit 127
fi

# ---------- temp files & timing --------------------------------------------

set -e
WORK="$(mktemp -d -t run.XXXXXX)" || exit 1
trap 'rm -rf "$WORK"' EXIT
OUT="$WORK/out"
ERR="$WORK/err"
mkfifo "$WORK/out.pipe" "$WORK/err.pipe"
set +e

# Keeps the first bytes of a stream and drains the rest, so the script never blocks or fills /tmp.
# dd writes each read straight to the file: a buffering head would lose it while a background child holds the pipe.
capture() {
    SIZE=0
    while [ "$SIZE" -le "$MAX_STREAM_BYTES" ]; do
        dd bs=65536 count=1 >> "$1" 2> /dev/null
        NEW_SIZE=$(($(wc -c < "$1")))
        [ "$NEW_SIZE" -eq "$SIZE" ] && break
        SIZE=$NEW_SIZE
    done
    cat > /dev/null
}

capture "$OUT" < "$WORK/out.pipe" &
OUT_READER=$!
capture "$ERR" < "$WORK/err.pipe" &
ERR_READER=$!

# busybox date (the alpine images) prints nothing for %N, so fall back to /proc/uptime there (10 ms steps)
now() {
    T="$(date +%s.%N)"
    case "$T" in
        *.) cut -d' ' -f1 /proc/uptime ;;
        *) printf '%s\n' "$T" ;;
    esac
}

START_TIME="$(now)"

# ---------- run user command in the background -----------------------------

"$@" > "$WORK/out.pipe" 2> "$WORK/err.pipe" &
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

END_TIME="$(now)"
ELAPSED_S=$(printf '%s\n' "$END_TIME $START_TIME" | awk '{printf "%.6f",$1-$2}')

# A background child of the script can hold the pipes open, so wait for the readers about a second at most.
TRIES=0
while [ "$TRIES" -lt 200 ] && { kill -0 "$OUT_READER" || kill -0 "$ERR_READER"; } 2>/dev/null; do
    sleep 0.005
    TRIES=$((TRIES + 1))
done

# ---------- write resource metrics to termination log ----------------------

printf 'exit_code=%d\ncpu_jiffies=%d\nclk_tck=%d\npeak_memory_kb=%d\nwall_seconds=%s\n' \
    "${EXIT_CODE:-1}" "${JIFS:-0}" "${CLK_TCK:-100}" "${PEAK_KB:-0}" "${ELAPSED_S:-0}" \
    > /dev/termination-log

# ---------- write length-prefixed stdout/stderr ----------------------------

emit() {
    SIZE=$(($(wc -c < "$3")))
    if [ "$SIZE" -le "$MAX_STREAM_BYTES" ]; then
        printf '%s %d\n' "$1" "$SIZE"
        head -c "$SIZE" "$3"
        return
    fi
    NOTICE="[$2 truncated: showing the first $MAX_STREAM_BYTES bytes]"
    printf '%s %d\n' "$1" "$((MAX_STREAM_BYTES + ${#NOTICE} + 2))"
    head -c "$MAX_STREAM_BYTES" "$3"
    printf '\n%s\n' "$NOTICE"
}

emit STDOUT stdout "$OUT"
emit STDERR stderr "$ERR"

exit 0
