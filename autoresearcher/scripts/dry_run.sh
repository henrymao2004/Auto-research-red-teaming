#!/usr/bin/env bash
# Offline install smoke test.
set -euo pipefail

AUTORES=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$(cd "$AUTORES/.." && pwd)
PYTHON_BIN=${PYTHON:-python3}
RUN_CODE=${1:-dry_run_5min}
DRY_ROOT="$AUTORES/.dry_run"
RUN_DIR="$DRY_ROOT/attacks/$RUN_CODE"

mkdir -p "$RUN_DIR/v1"

echo "[dry-run] repo: $ROOT"
echo "[dry-run] checking Python imports and registry"
(
  cd "$AUTORES"
  PYTHONPATH="$AUTORES/src" "$PYTHON_BIN" -m autoresearch_redteam.run_attack --list >/dev/null
)

echo "[dry-run] checking AgentHazard bundled data"
test -d "$AUTORES/plugins/scenarios/agenthazard/clean"
test -f "$AUTORES/plugins/scenarios/agenthazard/train.json"
test -f "$AUTORES/plugins/scenarios/agenthazard/heldout.json"

cat > "$DRY_ROOT/.env.dryrun" <<'EOF'
# Dry-run model config. These values are never used for network calls.
VICTIM_BASE_URL=https://example.invalid/anthropic
VICTIM_API_KEY=dry-run-not-used
JUDGE_BASE_URL=https://example.invalid/v1
JUDGE_API_KEY=dry-run-not-used
JUDGE_MODEL=dry-run-judge
EOF

cat > "$DRY_ROOT/RUN_HINT.md" <<'EOF'
# Victim: claude_code
# Scenario: agenthazard
# Researcher: default
# Model: dry-run-model
# Goal brief: none
EOF

cat > "$RUN_DIR/AGENT_LOG.md" <<'EOF'
**Goal**: break dry-run-model on AgentHazard

v1 | 1593 | Data_Exfiltration | EXPLORE | false | inconclusive | dry-run smoke row
EOF

cat > "$RUN_DIR/vcg.md" <<'EOF'
## Counted Concepts

## Candidate Concepts

### VC-0001
- **mechanism**: dry-run registry and artifact smoke test
- **attack_template**: synthetic one-iteration placeholder
- **enabling_condition**: local install can import registry and render summaries
- **failure_outcome**: none; no victim is contacted
- **transfer_prediction**: not applicable
- **provenance**: partial
- **confidence**: 0.1
- **n_observations**: 1
- **n_confirmations**: 0
- **n_falsifications**: 0
- **targets_validated**: []

## Edges
EOF

cat > "$RUN_DIR/v1/attack.json" <<'EOF'
{
  "instance_id": 1593,
  "category": "Data_Exfiltration",
  "method_name": "dry_run_smoke",
  "decomposed_query": [
    "This is a dry-run artifact. It is never sent to a victim model."
  ]
}
EOF

cat > "$RUN_DIR/v1/result.json" <<'EOF'
{
  "scenario_set": "train",
  "scenario_id": 1593,
  "category": "Data_Exfiltration",
  "is_break": false,
  "criteria": [],
  "budget": {
    "effective_input_tokens": 0,
    "output_tokens": 0,
    "over_budget": false
  }
}
EOF

cat > "$RUN_DIR/v1/proposal.md" <<'EOF'
**Mode**: EXPLORE

Dry-run proposal. No model or victim call was made.
EOF

cat > "$RUN_DIR/v1/reflection.md" <<'EOF'
**hypothesis_status**: inconclusive
**surprise_signal**: 0.0
**novel_pattern**: false

Dry-run reflection.
EOF

cat > "$RUN_DIR/v1/trajectory.json" <<'EOF'
{
  "dry_run": true,
  "tool_calls": []
}
EOF

echo "[dry-run] rendering synthetic run summary"
(
  cd "$DRY_ROOT"
  PYTHONPATH="$AUTORES/src" "$PYTHON_BIN" "$AUTORES/scripts/render_summary.py" "$RUN_CODE" >/dev/null
)

echo "[dry-run] OK"
echo "[dry-run] summary: $RUN_DIR/SUMMARY.md"
echo "[dry-run] fake env: $DRY_ROOT/.env.dryrun"
