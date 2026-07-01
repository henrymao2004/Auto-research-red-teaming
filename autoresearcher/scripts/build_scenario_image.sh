#!/bin/bash
# Build a scenario image.
# Requires ar_claude_code_base:latest.
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: $0 <scenario_name>" >&2
    exit 1
fi

SCENARIO=$1
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
AUTORES=$(cd "$SCRIPT_DIR/.." && pwd)
SCENARIO_DIR="$AUTORES/plugins/scenarios/${SCENARIO}"

if [ ! -f "$SCENARIO_DIR/Dockerfile" ]; then
    echo "ERROR: no Dockerfile at $SCENARIO_DIR/Dockerfile" >&2
    exit 1
fi

if ! docker image inspect ar_claude_code_base:latest > /dev/null 2>&1; then
    echo "ERROR: base image ar_claude_code_base:latest missing." >&2
    echo "       Run: bash $SCRIPT_DIR/build_base_image.sh" >&2
    exit 1
fi

docker build -t "ar_${SCENARIO}:latest" \
    -f "$SCENARIO_DIR/Dockerfile" \
    "$SCENARIO_DIR/"
