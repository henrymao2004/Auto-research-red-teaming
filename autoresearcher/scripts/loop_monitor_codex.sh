#!/bin/bash
# Codex monitor loop.
# Run from the worktree's inner autoresearcher dir.
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <run_code>" >&2
    exit 1
fi

RUN_CODE=$1

STOP_FILE="attacks/$RUN_CODE/STOP"
LOCK_FILE="attacks/$RUN_CODE/.codex_monitor_loop.lock"
MAX_ITERS=${MAX_ITERS:-200}                # generous outer cap (monitor is cheap)
CHECK_INTERVAL=${CHECK_INTERVAL:-900}      # 15 min, mirrors claude `/loop 15m`

if ! command -v codex > /dev/null 2>&1; then
    echo "ERROR: codex CLI not on PATH." >&2
    exit 1
fi

mkdir -p "attacks/$RUN_CODE"
echo ">> codex MONITOR loop for $RUN_CODE (max $MAX_ITERS checks, every ${CHECK_INTERVAL}s); Ctrl-C or STOP file to halt."

for ((i = 1; i <= MAX_ITERS; i++)); do
    if [ -f "$STOP_FILE" ]; then
        echo ">> STOP file present ($STOP_FILE) — monitor halting after $((i-1)) checks."
        break
    fi
    echo ">> === codex monitor check $i/$MAX_ITERS @ $(date '+%H:%M:%S') ==="
    # Use flock when available.
    if command -v flock >/dev/null 2>&1; then
        flock "$LOCK_FILE" \
            codex exec \
                --dangerously-bypass-approvals-and-sandbox \
                --skip-git-repo-check \
                "\$autoresearch-redteam-monitor $RUN_CODE" \
            || echo ">> WARN monitor check $i exited non-zero; continuing."
    else
        codex exec \
            --dangerously-bypass-approvals-and-sandbox \
            --skip-git-repo-check \
            "\$autoresearch-redteam-monitor $RUN_CODE" \
            || echo ">> WARN monitor check $i exited non-zero; continuing."
    fi
    # Re-check STOP before sleeping.
    [ -f "$STOP_FILE" ] && { echo ">> STOP written by check $i — halting."; break; }
    sleep "$CHECK_INTERVAL"
done

echo ">> codex monitor loop finished."
