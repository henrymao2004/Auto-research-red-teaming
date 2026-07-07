#!/bin/bash
# Build the shared Claude Code base image.
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
AUTORES=$(cd "$SCRIPT_DIR/.." && pwd)
DOCKER_DIR="$AUTORES/plugins/victims/claude_code/docker"

docker build -t ar_claude_code_base:latest \
    -f "$DOCKER_DIR/Dockerfile.base" \
    "$DOCKER_DIR/"
