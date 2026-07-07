#!/bin/bash
# Codex discovery loop.
# Run from the worktree's inner autoresearcher dir.
set -euo pipefail

if [ $# -lt 2 ]; then
    echo "Usage: $0 <run_code> <goal...>" >&2
    exit 1
fi

RUN_CODE=$1; shift
GOAL="$*"

STOP_FILE="attacks/$RUN_CODE/STOP"
LOCK_FILE="attacks/$RUN_CODE/.codex_loop.lock"
# Completed iterations require result.json.
# MAX_ITERS caps raw codex passes.
REAL_CAP=${REAL_CAP:-100}        # completed-iteration target (the real cap)
MAX_ITERS=${MAX_ITERS:-300}      # raw-pass backstop (prevents runaway only)
SLEEP_BETWEEN=${SLEEP_BETWEEN:-5}

if ! command -v codex > /dev/null 2>&1; then
    echo "ERROR: codex CLI not on PATH." >&2
    exit 1
fi

# Source repo .env for each codex pass.
REPO=$(cd "$(dirname "$0")/../.." && pwd)
if [ -f "$REPO/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO/.env"
    set +a
    echo ">> sourced $REPO/.env"
fi

# Require victim credentials.
if [ -z "${VICTIM_API_KEY:-}" ]; then
    echo "ERROR: VICTIM_API_KEY unset (even after sourcing $REPO/.env)." >&2
    echo "       Set VICTIM_API_KEY (+ VICTIM_BASE_URL) in $REPO/.env, or run /setup." >&2
    exit 1
fi

mkdir -p "attacks/$RUN_CODE"
echo ">> codex loop for $RUN_CODE (target $REAL_CAP completed iters; raw cap $MAX_ITERS passes); Ctrl-C or STOP file to halt."

for ((i = 1; i <= MAX_ITERS; i++)); do
    if [ -f "$STOP_FILE" ]; then
        echo ">> STOP file present ($STOP_FILE) — halting after $((i-1)) passes."
        break
    fi
    # Count completed iterations.
    DONE=$(find "attacks/$RUN_CODE" -maxdepth 2 -path "*/v[0-9]*/result.json" -type f | wc -l | tr -d ' ')
    if [ "$DONE" -ge "$REAL_CAP" ]; then
        echo ">> REAL_CAP reached: $DONE completed iterations (>= $REAL_CAP) — halting."
        break
    fi
    echo ">> === codex pass $i/$MAX_ITERS (completed=$DONE/$REAL_CAP) ==="
    # Use flock when available.
    if command -v flock >/dev/null 2>&1; then
        flock "$LOCK_FILE" \
            codex exec \
                --dangerously-bypass-approvals-and-sandbox \
                --skip-git-repo-check \
                "\$autoresearch-redteam-discovery $RUN_CODE $GOAL" \
            || echo ">> WARN iteration $i exited non-zero; continuing."
    else
        codex exec \
            --dangerously-bypass-approvals-and-sandbox \
            --skip-git-repo-check \
            "\$autoresearch-redteam-discovery $RUN_CODE $GOAL" \
            || echo ">> WARN iteration $i exited non-zero; continuing."
    fi
    sleep "$SLEEP_BETWEEN"
done

echo ">> codex loop finished."
