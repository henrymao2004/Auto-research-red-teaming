#!/usr/bin/env bash
# Run held-out attacks.
# Usage: <run_code> [parallel] [victim] [scenario] [model].
# Defaults: 1, claude_code, agenthazard, claude-haiku-4-5.
# Skips completed instances.
set -euo pipefail

RUN_CODE="${1:?usage: run_heldout_eval.sh <run_code> [parallel] [victim] [scenario] [model]}"
PARALLEL="${2:-1}"
VICTIM="${3:-claude_code}"
SCENARIO="${4:-agenthazard}"
MODEL="${5:-claude-haiku-4-5}"
# Retry transient container failures.
#   ATTEMPTS         : total tries per instance before giving up (default 5)
#   ATTEMPT_TIMEOUT  : per-try container wall-clock seconds (default 300; was 900)
#   RETRY_BACKOFF    : seconds between tries
ATTEMPTS="${ATTEMPTS:-5}"
ATTEMPT_TIMEOUT="${ATTEMPT_TIMEOUT:-300}"
RETRY_BACKOFF="${RETRY_BACKOFF:-20}"

HELDOUT_RUN="heldout_${RUN_CODE}"
ATTACKS_DIR="attacks/${HELDOUT_RUN}"
[ -d "$ATTACKS_DIR" ] || { echo "no $ATTACKS_DIR — run instantiate_concepts.py first"; exit 1; }

TOTAL=$(ls -d "$ATTACKS_DIR"/v* 2>/dev/null | wc -l | tr -d ' ')
echo "[$(date +%H:%M:%S)] held-out eval: ${TOTAL} attack specs, parallel=${PARALLEL}"

# Detect retryable container failures.
_is_transient_fail() {
    local rj="$1"
    [ -f "$rj" ] || return 1
    python3 - "$rj" <<'PY'
import json, sys
try:
    j = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)  # retry partial results
e = str(j.get("error") or "")
cont = (j.get("raw_payload") or {}).get("container") or {}
e2 = str(cont.get("error") or "")
blob = (e + " " + e2).lower()
sys.exit(0 if ("timed out" in blob or "exited" in blob
               or "without writing" in blob or "docker error" in blob) else 1)
PY
}

run_one() {
    local d="$1"
    local n
    n=$(basename "$d" | sed 's/^v//')
    if [ -f "$d/result.json" ]; then
        return 0
    fi
    local attempt=0
    while :; do
        attempt=$((attempt+1))
        echo "[$(date +%H:%M:%S)] v${n} (attempt ${attempt}/${ATTEMPTS})"
        uv run -m autoresearch_redteam.run_attack \
            --run-code "${HELDOUT_RUN}" \
            --version "${n}" \
            --victim "${VICTIM}" \
            --scenario "${SCENARIO}" \
            --model "${MODEL}" \
            --max-input-tokens 500000 --max-output-tokens 50000 \
            --timeout "${ATTEMPT_TIMEOUT}" \
            >> "held_out_eval/${RUN_CODE}/eval.log" 2>&1 || \
            echo "    v${n} run_attack nonzero exit (see eval.log)"
        if _is_transient_fail "$d/result.json"; then
            if [ "$attempt" -lt "$ATTEMPTS" ]; then
                echo "    v${n} transient container hang — discarding + retrying in ${RETRY_BACKOFF}s"
                rm -f "$d/result.json" "$d/trajectory.json"
                sleep "${RETRY_BACKOFF}"
                continue
            fi
            echo "    v${n} STILL failing after ${ATTEMPTS} attempts — leaving as infra-fail (not a non-break)"
        fi
        break
    done
}

# Group dtagent by shared backends.
_serial_group() {   # instance-id -> backend serial-group key
    if [ "$SCENARIO" = dtagent ]; then
        case "$1" in
            medical-*) echo dtap_medical ;;
            *)         echo dtap_shared ;;   # shared gmail/slack
        esac
    else
        echo "$1"     # isolated group
    fi
}
export -f run_one _is_transient_fail _serial_group
export HELDOUT_RUN RUN_CODE VICTIM SCENARIO MODEL ATTEMPTS ATTEMPT_TIMEOUT RETRY_BACKOFF

mkdir -p "held_out_eval/${RUN_CODE}"

if [ "$PARALLEL" -le 1 ]; then
    for d in "$ATTACKS_DIR"/v*; do
        run_one "$d"
    done
elif [ "$SCENARIO" = dtagent ]; then
    # Run each backend group serially.
    GROUPS=$(for d in "$ATTACKS_DIR"/v*; do _serial_group "$(basename "$d" | sed 's/^v//')"; done | sort -u)
    echo "[$(date +%H:%M:%S)] dtagent backend-group parallel: groups = $(echo $GROUPS | tr '\n' ' ')"
    for g in $GROUPS; do
        (
            for d in "$ATTACKS_DIR"/v*; do
                [ "$(_serial_group "$(basename "$d" | sed 's/^v//')")" = "$g" ] || continue
                run_one "$d"
            done
            echo "[$(date +%H:%M:%S)] group ${g} done"
        ) &
    done
    wait
else
    printf '%s\n' "$ATTACKS_DIR"/v* | xargs -n1 -P"$PARALLEL" -I{} bash -c 'run_one "$@"' _ {}
fi

echo "[$(date +%H:%M:%S)] done. results under $ATTACKS_DIR/v*/result.json"
echo "next: uv run python scripts/aggregate_heldout.py ${RUN_CODE}"
