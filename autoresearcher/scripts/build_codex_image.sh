#!/bin/bash
# Build the codex victim image.
# Requires ar_claude_code_base:latest.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
AUTORES=$(cd "$SCRIPT_DIR/.." && pwd)
CODEX_DIR="$AUTORES/plugins/victims/codex"
CANON_CORE="$AUTORES/plugins/victims/claude_code/docker/runner_core.py"

if ! docker image inspect ar_claude_code_base:latest > /dev/null 2>&1; then
    echo "ERROR: base image ar_claude_code_base:latest missing." >&2
    echo "       Run: bash $SCRIPT_DIR/build_base_image.sh" >&2
    exit 1
fi

if [ ! -f "$CANON_CORE" ]; then
    echo "ERROR: canonical runner_core.py not found at $CANON_CORE" >&2
    exit 1
fi

# Stage the shared runner core.
cp "$CANON_CORE" "$CODEX_DIR/docker/runner_core.py"
echo "[build_codex_image] staged runner_core.py into codex build context"

docker build -t ar_codex:latest \
    -f "$CODEX_DIR/Dockerfile" \
    "$CODEX_DIR/"

echo "[build_codex_image] built ar_codex:latest"
