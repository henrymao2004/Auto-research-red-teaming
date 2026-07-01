#!/usr/bin/env bash
# Manage dtagent backend stacks.
# Usage:
#   OPENROUTER_API_KEY=... bash scripts/build_dtagent_backends.sh \
#     [pull|build|up|down|all]
# Default: all.
# Medical backend needs OPENROUTER_API_KEY or OPENAI_API_KEY.
set -euo pipefail
DTAGENT="$(cd "$(dirname "$0")/../plugins/scenarios/dtagent" && pwd)"
ENVS="$DTAGENT/envs"
CMD="${1:-all}"

pull_images() {
  echo ">> pulling dtagent backend images (host-published bridges pull from Docker Hub)…"
  grep -hE '^[[:space:]]*image:' "$ENVS"/*.bridge.yml \
    | sed -E 's/^[[:space:]]*image:[[:space:]]*//; s/["'"'"']//g' \
    | grep -v '^ar_' | sort -u \
    | while read -r img; do
        if docker image inspect "$img" >/dev/null 2>&1; then echo "   SKIP $img (present)"
        else echo "   PULL $img"; docker pull --quiet "$img" >/dev/null && echo "        ok"; fi
      done
}

build_medical() {
  echo ">> building ar_medical_service (patched medical backend → OpenRouter)…"
  docker build -t ar_medical_service:latest -f "$DTAGENT/medical_patch/Dockerfile" "$DTAGENT/medical_patch"
}

up_bridges() {
  : "${OPENROUTER_API_KEY:=${OPENAI_API_KEY:-}}"
  [ -z "$OPENROUTER_API_KEY" ] && echo "   WARN: OPENROUTER_API_KEY unset — medical patient/judge sim won't work." >&2
  echo ">> bringing up bridge stacks (host-published; idempotent)…"
  for f in "$ENVS"/*.bridge.yml; do
    name="$(basename "$f" .bridge.yml)"
    OPENAI_API_KEY="$OPENROUTER_API_KEY" docker compose -p "${name}_bridge" -f "$f" up -d
  done
  echo ">> backends up. Health: curl localhost:12001/ (medical), :8080 (salesforce), :8035 (paypal)…"
}

down_bridges() {
  for f in "$ENVS"/*.bridge.yml; do
    docker compose -p "$(basename "$f" .bridge.yml)_bridge" -f "$f" down 2>/dev/null || true
  done
  echo ">> all dtagent bridges down."
}

case "$CMD" in
  pull)  pull_images ;;
  build) build_medical ;;
  up)    up_bridges ;;
  down)  down_bridges ;;
  all)   pull_images; build_medical; up_bridges ;;
  *) echo "usage: $0 [pull|build|up|down|all]"; exit 2 ;;
esac
