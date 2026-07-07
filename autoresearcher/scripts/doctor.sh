#!/usr/bin/env bash
# Local readiness checks.
set -u

AUTORES=$(cd "$(dirname "$0")/.." && pwd)
ROOT=$(cd "$AUTORES/.." && pwd)
PYTHON_BIN=${PYTHON:-python3}

PASS=0
WARN=0
FAIL=0

ok() { printf "OK   %s\n" "$*"; PASS=$((PASS + 1)); }
warn() { printf "WARN %s\n" "$*"; WARN=$((WARN + 1)); }
fail() { printf "FAIL %s\n" "$*"; FAIL=$((FAIL + 1)); }
has_cmd() { command -v "$1" >/dev/null 2>&1; }

check_cmd() {
  if has_cmd "$1"; then ok "$1 found"; else warn "$1 not found"; fi
}

check_env_any() {
  label=$1
  shift
  for name in "$@"; do
    if [ -n "${!name:-}" ]; then
      ok "$label set via $name"
      return
    fi
  done
  warn "$label unset (${*})"
}

echo "AHA doctor"
echo "repo: $ROOT"
echo

check_cmd uv
check_cmd "$PYTHON_BIN"
check_cmd docker
check_cmd claude
check_cmd codex

echo
echo "Python / registry"
if (cd "$AUTORES" && PYTHONPATH="$AUTORES/src" "$PYTHON_BIN" -m autoresearch_redteam.run_attack --list >/tmp/aha_doctor_run_attack_list.txt 2>/tmp/aha_doctor_run_attack_list.err); then
  ok "run_attack --list"
else
  fail "run_attack --list failed; see /tmp/aha_doctor_run_attack_list.err"
fi

echo
echo "Model environment"
check_env_any "victim endpoint" VICTIM_BASE_URL ANTHROPIC_BASE_URL CODEX_RESPONSES_BASE_URL
check_env_any "victim key" VICTIM_API_KEY VICTIM_AUTH_TOKEN ANTHROPIC_AUTH_TOKEN MOONBRIDGE_API_KEY OPENROUTER_API_KEY
check_env_any "judge key" JUDGE_API_KEY OPENROUTER_API_KEY
check_env_any "scenario-build generator key" ROUTER_API_KEY OPENROUTER_API_KEY RESEARCHER_API_KEY

echo
echo "Docker"
if has_cmd docker && docker info >/tmp/aha_doctor_docker.txt 2>/tmp/aha_doctor_docker.err; then
  ok "Docker daemon reachable"
  for image in ar_claude_code_base:latest ar_agenthazard:latest ar_agentdyn:latest ar_codex:latest; do
    if docker image inspect "$image" >/dev/null 2>&1; then
      ok "image present: $image"
    else
      warn "image missing: $image"
    fi
  done
else
  warn "Docker daemon not reachable"
fi

echo
echo "DTap backend ports (warnings are fine unless running dtagent)"
for port in 8080 8030 8034 8032 8040 12001 8036; do
  if "$PYTHON_BIN" - "$port" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket()
sock.settimeout(0.25)
try:
    sock.connect(("127.0.0.1", port))
except OSError:
    sys.exit(1)
finally:
    sock.close()
PY
  then
    ok "localhost:$port reachable"
  else
    warn "localhost:$port not reachable"
  fi
done

echo
echo "Benchmark seed strings"
if has_cmd rg; then
  seed_hits=$(rg -n --glob '!/.git/**' --glob '!/.venv/**' --glob '!**/__pycache__/**' \
    'AKIA[0-9A-Z]{12,}|sk_live_[A-Za-z0-9]+|ghp_[A-Za-z0-9]{20,}|SG\.[A-Za-z0-9_-]+' "$ROOT" 2>/dev/null | wc -l | tr -d ' ')
  if [ "${seed_hits:-0}" -gt 0 ]; then
    warn "$seed_hits secret-shaped benchmark seed strings found; expected in vendored safety benchmarks, never replace with real keys"
  else
    ok "no secret-shaped seed strings found"
  fi
else
  warn "rg not found; skipped benchmark seed scan"
fi

echo
echo "Summary: $PASS ok, $WARN warn, $FAIL fail"
if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
