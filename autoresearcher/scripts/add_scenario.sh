#!/bin/bash
# add_scenario.sh <name>
#
# Scaffold a scenario plugin.
set -euo pipefail

NAME="${1:?usage: add_scenario.sh <name>}"
AUTORES=$(cd "$(dirname "$0")/.." && pwd)
DIR="$AUTORES/plugins/scenarios/$NAME"

if [ -d "$DIR" ]; then
    echo "ERROR: $DIR already exists" >&2
    exit 1
fi

CAP_NAME="$(echo "${NAME:0:1}" | tr '[:lower:]' '[:upper:]')${NAME:1}"

mkdir -p "$DIR/clean"

cat > "$DIR/scenario.yaml" <<YAML
name: $NAME
description: REPLACE_ME — one-line description of this scenario.
native_attack_family: multi_turn       # change if your family is different
scenario: $NAME.scenario:${CAP_NAME}Scenario
categories: []
status: scaffold
YAML

cat > "$DIR/scenario.py" <<PY
"""Generated scenario plugin scaffold; fill in the runtime-specific parts.

Mirror plugins/scenarios/agenthazard/scenario.py.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
CLEAN_DIR = HERE / "clean"


class ${CAP_NAME}Scenario:
    name = "$NAME"
    native_attack_family = "multi_turn"
    attack_schema: dict[str, Any] = {}    # JSON Schema for attack.json
    subagent_blurb = ""                    # short attack-family paragraph
    categories: list[str] = []             # scenario categories
    train_path = HERE / "train.json"
    heldout_path = HERE / "heldout.json"
    judge_data_path = HERE / "judge_data.json"
    clean_dir = CLEAN_DIR

    def load_instance(self, instance_id: int) -> dict[str, Any]:
        for cat in self.categories:
            path = CLEAN_DIR / cat / f"{instance_id}.json"
            if path.exists():
                return json.loads(path.read_text())
        raise FileNotFoundError(f"instance {instance_id} not found under {CLEAN_DIR}")

    def classify_instance(self, instance_id: int) -> str:
        for path, key, label in (
            (self.train_path, "train", "train"),
            (self.heldout_path, "held_out", "held_out"),
        ):
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
            except Exception:
                continue
            for cat in (data.get("categories") or {}).values():
                if instance_id in (cat.get(key) or []):
                    return label
        return "unknown"

    def build_input_spec(self, attack: dict, instance: dict, model: str) -> dict:
        raise NotImplementedError("Implement build_input_spec — see docs/BYO_SCENARIO.md")

    def judge_trajectory(self, instance, trajectory_payload, **kw) -> dict:
        from .judge import judge_trajectory as _judge
        return _judge(instance, trajectory_payload, **kw)
PY

cat > "$DIR/judge.py" <<PY
"""Generated judge scaffold; fill in scenario-specific scoring.

Mirror plugins/scenarios/agenthazard/judge.py: read trajectory,
call an OpenAI-compatible chat completions endpoint, return at minimum
{"harmful": bool, "score": float, "reason": str}.
"""
from __future__ import annotations


def judge_trajectory(instance, trajectory, **kwargs):
    raise NotImplementedError("Implement judge_trajectory — see docs/BYO_SCENARIO.md")
PY

cat > "$DIR/regen_split.py" <<'PY'
"""Generated split-script scaffold.

Writes train.json + heldout.json (no combined split file) under this
plugin dir. See plugins/scenarios/agenthazard/regen_split.py as a
template.
"""
PY

cat > "$DIR/convert.py" <<'PY'
"""Generated dataset-converter scaffold.

Turns the upstream dataset into per-instance JSONs under clean/<cat>/<id>.json.
See plugins/scenarios/agenthazard/convert.py as a template.
"""
PY

touch "$DIR/clean/.gitkeep"

echo "Scaffolded $DIR"
echo "Next:"
echo "  1. Edit scenario.yaml: description, native_attack_family, categories"
echo "  2. Edit scenario.py: build_input_spec + attack_schema + subagent_blurb"
echo "  3. Implement judge.py"
echo "  4. Implement convert.py + regen_split.py, then run them"
echo "  5. Run: uv run -m autoresearch_redteam.run_attack --list"
echo "  6. See docs/BYO_SCENARIO.md for the full checklist."
