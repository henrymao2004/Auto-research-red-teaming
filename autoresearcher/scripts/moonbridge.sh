#!/usr/bin/env bash
# Moon Bridge launcher.
# Usage: build | up | status | down | all.
# Env: MB_CONFIG, MB_SRC, MB_RESPONSES_PORT, MB_ANTHROPIC_PORT.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="ar_moonbridge:latest"
CONFIG="${MB_CONFIG:-$REPO/templates/moonbridge/config.yml}"
# Codex Transform config.
RCONFIG="${MB_RESPONSES_CONFIG:-$(dirname "$CONFIG")/config_responses.yml}"
[ -f "$RCONFIG" ] || RCONFIG="$CONFIG"
RPORT="${MB_RESPONSES_PORT:-38440}"
APORT="${MB_ANTHROPIC_PORT:-38441}"
SRC="${MB_SRC:-/tmp/moon-bridge-src}"
DATA="/tmp/ar_moonbridge_data"
SCRIPTS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROXY_SCRIPT="$SCRIPTS/retry_proxy.py"
PROXY_PORT="${MB_PROXY_PORT:-38443}"
PROXY_LOG="${MB_PROXY_LOG:-/tmp/retry_proxy.log}"

build() {
  if [ ! -d "$SRC/.git" ]; then
    echo ">> cloning moon-bridge into $SRC"
    git clone --depth 1 https://github.com/ZhiYi-R/moon-bridge.git "$SRC"
  fi
  echo ">> building $IMAGE from $SRC"
  docker build -t "$IMAGE" "$SRC"
  echo ">> built $IMAGE"
}

require_config() {
  if [ ! -f "$CONFIG" ]; then
    echo "ERROR: config not found: $CONFIG" >&2
    echo "  cp $REPO/templates/moonbridge/config.example.yml $CONFIG  then fill in your keys." >&2
    exit 1
  fi
  if grep -q "REPLACE_WITH_" "$CONFIG"; then
    echo "WARN: $CONFIG still has REPLACE_WITH_* template values — fill in your provider api_key(s)." >&2
  fi
}

up() {
  require_config
  docker image inspect "$IMAGE" >/dev/null 2>&1 || build
  mkdir -p "$DATA"
  docker rm -f ar_moonbridge_responses ar_moonbridge_anthropic >/dev/null 2>&1 || true
  echo ">> codex  ingress (Transform)        -> http://localhost:$RPORT/v1/responses"
  docker run -d --name ar_moonbridge_responses --restart unless-stopped \
    -p "$RPORT:38440" -v "$RCONFIG:/config/config.yml" -v "$DATA:/data" "$IMAGE" \
    -config /config/config.yml -addr 0.0.0.0:38440 -mode Transform >/dev/null
  echo ">> claude ingress (CaptureAnthropic) -> http://localhost:$APORT/v1/messages  [config.yml upstream]"
  docker run -d --name ar_moonbridge_anthropic --restart unless-stopped \
    -p "$APORT:38440" -v "$CONFIG:/config/config.yml" -v "$DATA:/data" "$IMAGE" \
    -config /config/config.yml -addr 0.0.0.0:38440 -mode CaptureAnthropic >/dev/null
  # Optional OpenRouter Anthropic ingress.
  ORCONF="${MB_OR_CONFIG:-$(dirname "$CONFIG")/config_openrouter.yml}"
  ORPORT="${MB_OPENROUTER_PORT:-38442}"
  docker rm -f ar_moonbridge_openrouter >/dev/null 2>&1 || true
  if [ -f "$ORCONF" ]; then
    echo ">> claude ingress (CaptureAnthropic) -> http://localhost:$ORPORT/v1/messages  [OpenRouter upstream]"
    docker run -d --name ar_moonbridge_openrouter --restart unless-stopped \
      -p "$ORPORT:38440" -v "$ORCONF:/config/config.yml" -v "$DATA:/data" "$IMAGE" \
      -config /config/config.yml -addr 0.0.0.0:38440 -mode CaptureAnthropic >/dev/null
    # Retry proxy for OpenRouter ingress.
    if [ -f "$PROXY_SCRIPT" ]; then
      pkill -f "retry_proxy.py" >/dev/null 2>&1 || true
      echo ">> retry proxy             -> http://localhost:$PROXY_PORT  [retries :$ORPORT 5xx/EOF]"
      RETRY_PROXY_ADDR="0.0.0.0:$PROXY_PORT" RETRY_PROXY_TARGET="http://localhost:$ORPORT" \
        nohup python3 "$PROXY_SCRIPT" > "$PROXY_LOG" 2>&1 &
    else
      echo "WARN: $PROXY_SCRIPT missing — skipping retry proxy." >&2
    fi
  fi
  sleep 4
  status
}

status() {
  echo "== Moon Bridge instances =="
  docker ps --filter "name=ar_moonbridge_" --format '  {{.Names}}  {{.Status}}  {{.Ports}}' || true
  echo "  codex models (:$RPORT/v1/models):"
  curl -s --max-time 5 "http://localhost:$RPORT/v1/models" 2>/dev/null | head -c 400 || echo "    (not responding)"
  echo
  if pgrep -f "retry_proxy.py" >/dev/null 2>&1; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "http://localhost:$PROXY_PORT/v1/models" 2>/dev/null)
    echo "  retry proxy (:$PROXY_PORT): alive  /v1/models -> HTTP $code  (log: $PROXY_LOG)"
  else
    echo "  retry proxy (:$PROXY_PORT): not running"
  fi
}

down() {
  docker rm -f ar_moonbridge_responses ar_moonbridge_anthropic ar_moonbridge_openrouter >/dev/null 2>&1 || true
  pkill -f "retry_proxy.py" >/dev/null 2>&1 || true
  echo ">> moon-bridge stopped (incl. retry proxy)"
}

case "${1:-up}" in
  build)  build ;;
  up)     up ;;
  status) status ;;
  down)   down ;;
  all)    build; up ;;
  *)      echo "usage: $0 [build|up|status|down|all]" >&2; exit 2 ;;
esac
