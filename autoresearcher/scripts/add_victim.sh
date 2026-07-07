#!/bin/bash
# add_victim.sh <name>
#
# Scaffold a victim plugin.
set -euo pipefail

NAME="${1:?usage: add_victim.sh <name>}"
AUTORES=$(cd "$(dirname "$0")/.." && pwd)
DIR="$AUTORES/plugins/victims/$NAME"

if [ -d "$DIR" ]; then
    echo "ERROR: $DIR already exists" >&2
    exit 1
fi

CAP_NAME="$(echo "${NAME:0:1}" | tr '[:lower:]' '[:upper:]')${NAME:1}"

mkdir -p "$DIR"

cat > "$DIR/victim.yaml" <<YAML
name: $NAME
description: REPLACE_ME — one-line description of this victim runtime.
default_model: REPLACE_ME
victim: $NAME.adapter:${CAP_NAME}Adapter
docker_image: ar_$NAME:latest
supports_attack_families:
  - multi_turn
status: scaffold
YAML

cat > "$DIR/adapter.py" <<PY
"""Generated victim adapter scaffold; fill in the runtime-specific parts.

Mirror plugins/victims/claude_code/adapter.py:
  - spawn the victim runtime (Docker container preferred for isolation)
  - split a per-attack tempdir into two subdirs:
      /work    — agent cwd (agent-visible)
      /harness — empty at start, only carries trajectory.json output
  - pipe the input_spec JSON to the container via STDIN
    (docker run -i ... < spec). Do NOT write input.json to any
    bind-mounted path — that's how the agent can read its own
    attack plan via 'ls' / 'Read'.
  - read trajectory.json back from the harness side
  - return parsed trajectory + a _container envelope
"""
from __future__ import annotations


class ${CAP_NAME}Adapter:
    name = "$NAME"
    default_model = "REPLACE_ME"
    supports_attack_families = ("multi_turn",)

    def __init__(self, *, model: str | None = None, timeout_seconds: int = 600, **_):
        raise NotImplementedError(
            "Fill in this adapter. See docs/PLUGINS.md and "
            "plugins/victims/claude_code/adapter.py for a template."
        )

    def run(self, input_spec):
        raise NotImplementedError
PY

echo "Scaffolded $DIR"
echo "Next:"
echo "  1. Edit $DIR/victim.yaml: fill description + default_model"
echo "  2. Edit $DIR/adapter.py: implement run(input_spec) -> dict"
echo "  3. (optional) Add docker/ + Dockerfile for sandboxed execution"
echo "  4. Run: uv run -m autoresearch_redteam.run_attack --list"
echo "  5. See docs/PLUGINS.md for the plugin contract + checklist."
