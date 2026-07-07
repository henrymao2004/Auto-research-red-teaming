#!/bin/bash
# launch_run.sh <run_code> [--victim F] [--scenario B] [--researcher S]
#   [--model M] [--researcher-model M | --researcher-model-local M] <goal...>
#
# Create a run worktree and launch the orchestrator.

set -euo pipefail

VICTIM=claude_code
SCENARIO=agenthazard
RESEARCHER=default
MODEL=""        # explicit or inferred
RESEARCHER_MODEL_CLI=""   # CLI researcher model
RESEARCHER_MODEL_LOCAL_CLI=""   # CLI researcher override (host subscription auth)
NO_EXEC=0       # --no-exec: set up the worktree but do not launch the orchestrator

POSITIONAL=()
while [ $# -gt 0 ]; do
    case "$1" in
        --victim)  VICTIM=$2;  shift 2;;
        --scenario)  SCENARIO=$2;  shift 2;;
        --researcher) RESEARCHER=$2; shift 2;;
        --model)      MODEL=$2;      shift 2;;
        --researcher-model) RESEARCHER_MODEL_CLI=$2; shift 2;;
        --researcher-model-local) RESEARCHER_MODEL_LOCAL_CLI=$2; shift 2;;
        --no-exec) NO_EXEC=1; shift;;
        -h|--help)
            cat <<EOF
Usage: $0 <run_code> [--victim F] [--scenario B] [--researcher S] --model M
       [--researcher-model M | --researcher-model-local M] <goal...>

Defaults: --victim $VICTIM  --scenario $SCENARIO  --researcher $RESEARCHER
NOTE: --model has NO default. Pass it explicitly, or include a recognised
      model slug (e.g. deepseek-v4-pro) in the goal string and the launcher
      will infer it.

Researcher model:
  Claude researcher (--researcher default):
    --researcher-model M       route via OpenRouter; needs RESEARCHER_API_KEY
                               or OPENROUTER_API_KEY.
    --researcher-model-local M run on host claude.ai subscription auth, e.g.
                               claude-5-fable.
    When neither is set, the researcher uses the host's default claude model.
  Codex researcher (--researcher codex):
    --researcher-model M       set the codex researcher model, e.g. gpt-5.5 or
                               gpt-5.4; uses host codex login.
See ../.env.example.

Example:
  ./scripts/launch_run.sh my_first_run \\
      --victim claude_code --scenario agenthazard --model deepseek-v4-pro \\
      'break deepseek-v4-pro on AgentHazard'

Required env (see ../.env.example):
  ANTHROPIC_AUTH_TOKEN  victim's anthropic-compat key (or DEEPSEEK_API_KEY)
  JUDGE_API_KEY         host-side OpenAI-compatible judge key
  ROUTER_API_KEY        scenario-build generator key (warned if missing)
Optional researcher-backbone env (see ../.env.example):
  RESEARCHER_MODEL      LLM for the orchestrator + sub-agents
  RESEARCHER_BASE_URL   OpenRouter anthropic endpoint (https://openrouter.ai/api)
  RESEARCHER_API_KEY    OpenRouter key (forwarded as ANTHROPIC_AUTH_TOKEN)
  RESEARCHER_MODEL_LOCAL  host Claude subscription model, e.g. claude-5-fable
EOF
            exit 0;;
        *) POSITIONAL+=("$1"); shift;;
    esac
done
set -- "${POSITIONAL[@]}"

if [ $# -lt 2 ]; then
    echo "ERROR: need <run_code> and <goal>. Try $0 --help." >&2
    exit 1
fi

RUN_CODE=$1
shift
GOAL="$*"

GOAL_MODEL=$(echo "$GOAL" \
    | grep -Eoi '(\b(deepseek|claude|gpt|gemini|qwen|llama|mistral)[-_./][a-z0-9._-]+|\bo[1-9][0-9]*(-[a-z0-9.-]+)?)' \
    | head -1 || true)

if [ -z "$MODEL" ]; then
    if [ -n "$GOAL_MODEL" ]; then
        echo ">> --model not given; inferred '$GOAL_MODEL' from goal string."
        MODEL=$GOAL_MODEL
    fi
elif [ -n "$GOAL_MODEL" ] && [ "$GOAL_MODEL" != "$MODEL" ]; then
    echo "WARN: --model '$MODEL' differs from goal-string token '$GOAL_MODEL'." >&2
    echo "      Using --model. Edit the goal string if this is a typo." >&2
fi

AUTORES=$(cd "$(dirname "$0")/.." && pwd)
REPO=$(cd "$AUTORES/.." && pwd)
WT_OUTER=$AUTORES/worktrees/$RUN_CODE
WT_INNER=$WT_OUTER/autoresearcher
RESEARCHER_SRC=$AUTORES/plugins/researchers/$RESEARCHER/agents
if [ ! -d "$RESEARCHER_SRC" ]; then
    echo "ERROR: researcher agent '$RESEARCHER' not found at $RESEARCHER_SRC" >&2
    echo "       available: $(ls "$AUTORES/plugins/researchers" 2>/dev/null)" >&2
    exit 1
fi
if ls "$RESEARCHER_SRC"/*.toml > /dev/null 2>&1; then
    ORCH=codex
else
    ORCH=claude
fi

# Source repo .env before endpoint derivation.
if [ -f "$REPO/.env" ]; then
    set -a
    # shellcheck disable=SC1091
    source "$REPO/.env"
    set +a
    echo ">> sourced $REPO/.env"
fi

: "${MODEL:=${VICTIM_MODEL:-}}"
if [ -z "$MODEL" ]; then
    echo "ERROR: no victim model. Pass --model <slug>, include a model slug in" >&2
    echo "       the goal string, or set VICTIM_MODEL in .env (run /setup)." >&2
    exit 1
fi

# Derive endpoint slots from one provider key.
if [ -n "${UNIFIED_API_KEY:-}" ] && [ -n "${UNIFIED_PROVIDER:-}" ]; then
    case "$UNIFIED_PROVIDER" in
        anthropic)
            : "${VICTIM_API_KEY:=$UNIFIED_API_KEY}"; : "${VICTIM_BASE_URL:=https://api.anthropic.com}"
            : "${JUDGE_API_KEY:=$UNIFIED_API_KEY}";  : "${JUDGE_BASE_URL:=https://api.anthropic.com}"
            : "${ROUTER_API_KEY:=$UNIFIED_API_KEY}"; : "${ROUTER_BASE_URL:=https://api.anthropic.com}" ;;
        openrouter)
            : "${VICTIM_API_KEY:=$UNIFIED_API_KEY}"; : "${VICTIM_BASE_URL:=https://openrouter.ai/api}"
            : "${JUDGE_API_KEY:=$UNIFIED_API_KEY}";  : "${JUDGE_BASE_URL:=https://openrouter.ai/api/v1}"
            : "${ROUTER_API_KEY:=$UNIFIED_API_KEY}"; : "${ROUTER_BASE_URL:=https://openrouter.ai/api/v1}" ;;
        deepseek)
            : "${VICTIM_API_KEY:=$UNIFIED_API_KEY}"; : "${VICTIM_BASE_URL:=https://api.deepseek.com/anthropic}"
            : "${JUDGE_API_KEY:=$UNIFIED_API_KEY}";  : "${JUDGE_BASE_URL:=https://api.deepseek.com/v1}"
            : "${ROUTER_API_KEY:=$UNIFIED_API_KEY}"; : "${ROUTER_BASE_URL:=https://api.deepseek.com/v1}" ;;
        openai)
            : "${JUDGE_API_KEY:=$UNIFIED_API_KEY}";  : "${JUDGE_BASE_URL:=https://api.openai.com/v1}"
            : "${ROUTER_API_KEY:=$UNIFIED_API_KEY}"; : "${ROUTER_BASE_URL:=https://api.openai.com/v1}"
            echo "WARN: UNIFIED_PROVIDER=openai can't serve the victim (no Anthropic API)." >&2
            echo "      Set VICTIM_API_KEY + VICTIM_BASE_URL separately." >&2 ;;
        *)
            echo "ERROR: UNIFIED_PROVIDER='$UNIFIED_PROVIDER' not recognised (anthropic|openrouter|deepseek|openai)." >&2
            exit 1 ;;
    esac
    echo ">> UNIFIED_PROVIDER=$UNIFIED_PROVIDER — derived victim/judge/generator endpoints"
fi

: "${VICTIM_API_KEY:=${VICTIM_AUTH_TOKEN:-${ANTHROPIC_AUTH_TOKEN:-${ANTHROPIC_API_KEY:-${DEEPSEEK_API_KEY:-}}}}}"
: "${VICTIM_BASE_URL:=${ANTHROPIC_BASE_URL:-}}"
export VICTIM_API_KEY VICTIM_BASE_URL JUDGE_API_KEY JUDGE_BASE_URL ROUTER_API_KEY ROUTER_BASE_URL

: "${RESEARCHER_MODEL:=${RESEARCHER_MODEL_CLI:-}}"
[ -n "$RESEARCHER_MODEL_CLI" ] && RESEARCHER_MODEL=$RESEARCHER_MODEL_CLI
: "${RESEARCHER_MODEL_LOCAL:=${RESEARCHER_MODEL_LOCAL_CLI:-}}"
[ -n "$RESEARCHER_MODEL_LOCAL_CLI" ] && RESEARCHER_MODEL_LOCAL=$RESEARCHER_MODEL_LOCAL_CLI

if [ "$ORCH" = "codex" ]; then
    if [ -n "${RESEARCHER_MODEL_LOCAL:-}" ]; then
        echo "ERROR: --researcher-model-local is for Claude researchers." >&2
        echo "       For --researcher codex use --researcher-model <codex-model>." >&2
        exit 1
    fi
    : "${RESEARCHER_MODEL:=gpt-5.5}"
else
    if [ -n "${RESEARCHER_MODEL:-}" ] && [ -n "${RESEARCHER_MODEL_LOCAL:-}" ]; then
        echo "ERROR: set only ONE researcher backbone — --researcher-model (OpenRouter)" >&2
        echo "       or --researcher-model-local (host subscription auth), not both." >&2
        exit 1
    fi
fi

# Researcher description.
if [ "$ORCH" = "codex" ]; then
    RESEARCHER_DESC="$RESEARCHER_MODEL (codex)"
elif [ -n "${RESEARCHER_MODEL:-}" ]; then
    RESEARCHER_DESC="$RESEARCHER_MODEL (OpenRouter)"
elif [ -n "${RESEARCHER_MODEL_LOCAL:-}" ]; then
    RESEARCHER_DESC="$RESEARCHER_MODEL_LOCAL (subscription)"
else
    RESEARCHER_DESC="host-default-claude-auth"
fi

if [ "$ORCH" != "codex" ] && [ -n "${RESEARCHER_MODEL:-}" ]; then
    : "${RESEARCHER_BASE_URL:=https://openrouter.ai/api}"
    : "${RESEARCHER_API_KEY:=${OPENROUTER_API_KEY:-}}"
    if [ -z "${RESEARCHER_API_KEY:-}" ]; then
        echo "ERROR: --researcher-model / RESEARCHER_MODEL=$RESEARCHER_MODEL set but no" >&2
        echo "       RESEARCHER_API_KEY (or OPENROUTER_API_KEY). Set it in .env (run /setup)." >&2
        exit 1
    fi
fi

if [ "$ORCH" != "codex" ] && [ -n "${RESEARCHER_MODEL:-}" ] && [ -z "${VICTIM_BASE_URL:-}" ]; then
    echo "ERROR: a researcher backbone is set but VICTIM_BASE_URL is empty." >&2
    echo "       The victim adapter would inherit ANTHROPIC_BASE_URL → the" >&2
    echo "       researcher endpoint, breaking backbone isolation. Set" >&2
    echo "       VICTIM_BASE_URL explicitly in .env (run /setup)." >&2
    exit 1
fi

if [ -z "${VICTIM_API_KEY:-}" ]; then
    echo "ERROR: no victim key. Set VICTIM_API_KEY in .env (+ VICTIM_BASE_URL)," >&2
    echo "       or UNIFIED_API_KEY + UNIFIED_PROVIDER, or run /setup." >&2
    exit 1
fi
[ -z "${JUDGE_API_KEY:-}" ]  && echo "WARN: JUDGE_API_KEY unset — needed for LLM-prompt judges (run /setup)." >&2
[ -z "${ROUTER_API_KEY:-}" ] && echo "WARN: ROUTER_API_KEY unset — needed by /scenario-build (run /setup)." >&2

cd "$REPO"

if [ -d "$WT_OUTER" ]; then
    echo ">> Worktree $WT_OUTER already exists, resuming."
else
    echo ">> Creating worktree $WT_OUTER on branch loop/$RUN_CODE"
    git worktree add "$WT_OUTER" -b "loop/$RUN_CODE"
    # Initialize worktree assets.
    [ -L "$WT_OUTER/.venv" ] || ln -sf "$REPO/.venv" "$WT_OUTER/.venv"
    mkdir -p "$WT_INNER/.claude"
    if [ -f "$AUTORES/.claude/settings.local.json" ]; then
        cp "$AUTORES/.claude/settings.local.json" \
           "$WT_INNER/.claude/settings.local.json"
    elif [ -f "$REPO/templates/claude-settings/project-settings.local.json" ]; then
        echo ">> using template project-settings.local.json (no local copy found)"
        cp "$REPO/templates/claude-settings/project-settings.local.json" \
           "$WT_INNER/.claude/settings.local.json"
    else
        echo "WARN: no settings.local.json available; agent may prompt on every Bash." >&2
    fi

    if [ -f "$WT_INNER/.claude/settings.local.json" ] && command -v python3 >/dev/null 2>&1; then
        python3 - "$WT_INNER/.claude/settings.local.json" <<'PYEOF'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
perm = d.get("permissions", d)
deny = perm.setdefault("deny", [])
if "AskUserQuestion" not in deny:
    deny.append("AskUserQuestion")
    json.dump(d, open(p, "w"), indent=2)
    print(">> worktree settings hardened: AskUserQuestion denied (orchestrator/monitor only)")
PYEOF
    fi

    if ls "$RESEARCHER_SRC"/*.toml > /dev/null 2>&1; then
        mkdir -p "$WT_INNER/.codex/agents"
        cp "$RESEARCHER_SRC"/*.toml "$WT_INNER/.codex/agents/"
        for agent_toml in "$WT_INNER/.codex/agents"/*.toml; do
            sed -i.bak -E "s|^model = \".*\"|model = \"$RESEARCHER_MODEL\"|" "$agent_toml"
            rm -f "$agent_toml.bak"
        done
        echo ">> researcher agent '$RESEARCHER' copied into .codex/agents/ ($(ls "$WT_INNER/.codex/agents" | wc -l) codex agents; model=$RESEARCHER_MODEL)"
        SKILL_PATH="$AUTORES/.claude/skills/autoresearch-redteam-discovery/SKILL.md"
        CODEX_TMPL="$REPO/templates/codex-settings/config.toml"
        if [ ! -f "$CODEX_TMPL" ]; then
            echo "ERROR: codex settings template missing at $CODEX_TMPL" >&2
            exit 1
        fi
        sed -e "s#__SKILL_PATH__#$SKILL_PATH#g" \
            -e "s#__RESEARCHER_MODEL__#$RESEARCHER_MODEL#g" \
            "$CODEX_TMPL" > "$WT_INNER/.codex/config.toml"
        echo ">> seeded .codex/config.toml from templates/codex-settings/ (model=$RESEARCHER_MODEL)"
    else
        mkdir -p "$WT_INNER/.claude/agents"
        cp "$RESEARCHER_SRC"/*.md "$WT_INNER/.claude/agents/"
        echo ">> researcher agent '$RESEARCHER' copied into .claude/agents/ ($(ls "$WT_INNER/.claude/agents" | wc -l) agents)"
    fi
    GOAL_BRIEF_REF=""
    for src in "$AUTORES/GOAL_BRIEF.md" "$REPO/GOAL_BRIEF.md"; do
        if [ -f "$src" ]; then
            cp "$src" "$WT_INNER/GOAL_BRIEF.md"
            echo ">> GOAL_BRIEF.md copied from $src"
            GOAL_BRIEF_REF="$WT_INNER/GOAL_BRIEF.md"
            break
        fi
    done
    mkdir -p "$WT_INNER/attacks/$RUN_CODE"
    cat > "$WT_INNER/attacks/$RUN_CODE/vcg.md" <<VCG
# Vulnerability Concept Graph — $RUN_CODE

Persistent worldview. Concepts only enter here when the Reflector emits
a "New concept tuple" AND \`is_break=true\` for the iteration.

## Counted Concepts

(none yet — promotion requires n_confirmations >= 3, confidence >= 0.6, and >= 1 is_break observation. This VCG is scoped to one (victim, scenario, model) cell; cross-cell transferability is analysed post hoc.)

## Candidate Concepts

(none yet)

## Edges

| from | relation | to | confidence | evidence |
|---|---|---|---|---|
VCG
    cat > "$WT_INNER/attacks/$RUN_CODE/AGENT_LOG.md" <<AGL
# Agent Log — $RUN_CODE

**Goal**: $GOAL
**Branch**: loop/$RUN_CODE
**State**: initialised by launch_run.sh on $(date -u +%Y-%m-%dT%H:%M:%SZ).

## Layout (already initialised — do NOT re-create at other paths)

- \`attacks/$RUN_CODE/vcg.md\` — vulnerability concept graph
- \`attacks/$RUN_CODE/v<N>/\` — per-iteration artefacts (proposal, attack, result, trajectory, reflection)
- \`attacks/$RUN_CODE/AGENT_LOG.md\` — this file; cross-iteration narrative + periodic Critic checks

## Iteration log

(the SKILL appends one row per iteration here)
AGL
    cat > "$WT_INNER/RUN_HINT.md" <<HINT
# Run: $RUN_CODE
# Goal: $GOAL
# Victim:  $VICTIM
# Scenario:  $SCENARIO
# Researcher: $RESEARCHER
# Model:      $MODEL
# Researcher model: ${RESEARCHER_DESC}
# Goal brief: ${GOAL_BRIEF_REF:-none}
# Work in: attacks/$RUN_CODE/
# Branch: loop/$RUN_CODE
# Worktree (inner cwd): $WT_INNER
HINT
fi

# Preflight victim images.
if [ "$VICTIM" = "claude_code" ]; then
    if ! command -v docker > /dev/null 2>&1; then
        echo "WARN: docker not on PATH; skipping image preflight." >&2
    elif ! docker image inspect "ar_${SCENARIO}:latest" > /dev/null 2>&1; then
        echo ">> scenario image ar_${SCENARIO}:latest missing — building..."
        if ! docker image inspect ar_claude_code_base:latest > /dev/null 2>&1; then
            echo ">> base image ar_claude_code_base:latest missing — building base first..."
            bash "$AUTORES/scripts/build_base_image.sh"
        fi
        bash "$AUTORES/scripts/build_scenario_image.sh" "$SCENARIO"
    else
        echo ">> docker image ar_${SCENARIO}:latest present."
    fi
elif [ "$VICTIM" = "codex" ]; then
    if ! command -v docker > /dev/null 2>&1; then
        echo "WARN: docker not on PATH; skipping image preflight." >&2
    elif ! docker image inspect ar_codex:latest > /dev/null 2>&1; then
        echo ">> victim image ar_codex:latest missing — building..."
        if ! docker image inspect ar_claude_code_base:latest > /dev/null 2>&1; then
            echo ">> base image ar_claude_code_base:latest missing — building base first..."
            bash "$AUTORES/scripts/build_base_image.sh"
        fi
        bash "$AUTORES/scripts/build_codex_image.sh"
    else
        echo ">> docker image ar_codex:latest present."
    fi
fi

cd "$WT_INNER"
export PATH="/opt/homebrew/bin:$HOME/.local/bin:$PATH"

echo ""
echo "=========================================================="
echo "  Run code:   $RUN_CODE"
echo "  Goal:       $GOAL"
echo "  Victim:      $VICTIM"
echo "  Scenario:  $SCENARIO"
echo "  Researcher: $RESEARCHER"
echo "  Model:      $MODEL"
echo "  Worktree:   $WT_OUTER"
echo "  cwd:        $WT_INNER  (where claude will open)"
echo "  Branch:     loop/$RUN_CODE"
echo ""
echo "  Endpoints (resolved):"
echo "    victim     → ${VICTIM_BASE_URL:-<unset>}  model=$MODEL  key=$([ -n "${VICTIM_API_KEY:-}" ] && echo "OK …${VICTIM_API_KEY: -4}" || echo MISSING)"
echo "    judge      → ${JUDGE_BASE_URL:-<unset>}  model=${JUDGE_MODEL:-<from .env>}  key=$([ -n "${JUDGE_API_KEY:-}" ] && echo "OK …${JUDGE_API_KEY: -4}" || echo "unset (LLM judges only)")"
echo "    generator  → ${ROUTER_BASE_URL:-<unset>}  model=${GENERATOR_MODEL:-<default>}  key=$([ -n "${ROUTER_API_KEY:-}" ] && echo "OK …${ROUTER_API_KEY: -4}" || echo "unset")"
if [ "$ORCH" = "codex" ]; then
    echo "    researcher → host codex auth  model=${RESEARCHER_MODEL}"
elif [ -n "${RESEARCHER_MODEL:-}" ]; then
    echo "    researcher → ${RESEARCHER_BASE_URL}  model=${RESEARCHER_MODEL}  key=$([ -n "${RESEARCHER_API_KEY:-}" ] && echo "OK …${RESEARCHER_API_KEY: -4}" || echo MISSING)"
elif [ -n "${RESEARCHER_MODEL_LOCAL:-}" ]; then
    echo "    researcher → host claude.ai subscription auth  model=${RESEARCHER_MODEL_LOCAL}"
else
    echo "    researcher → host default claude auth  (no researcher model set)"
fi
echo ""
if [ "$ORCH" = "codex" ]; then
    echo "  Orchestrator: codex (native subagent spawning; .codex/agents/)"
    echo "  Inside codex, run:"
    echo "    \$autoresearch-redteam-discovery $RUN_CODE $GOAL"
    echo "  (ordered dispatch + file ownership enforced by AGENTS.md — see it)"
else
    echo "  Inside claude, run:"
    echo "    /loop /autoresearch-redteam-discovery $RUN_CODE $GOAL"
fi
echo "=========================================================="
echo ""

if [ "$NO_EXEC" = "1" ]; then
    echo ">> --no-exec: worktree ready, orchestrator NOT launched."
    if [ "$ORCH" = "codex" ]; then
        echo "   To run: cd $WT_INNER && codex --dangerously-bypass-approvals-and-sandbox"
    elif [ -n "${RESEARCHER_MODEL_LOCAL:-}" ]; then
        echo "   To run: cd $WT_INNER && claude --model $RESEARCHER_MODEL_LOCAL --dangerously-skip-permissions"
        echo "           then: /loop /autoresearch-redteam-discovery $RUN_CODE $GOAL"
    else
        echo "   To run: cd $WT_INNER && claude --dangerously-skip-permissions"
        echo "           then: /loop /autoresearch-redteam-discovery $RUN_CODE $GOAL"
    fi
    exit 0
fi

if [ "$ORCH" = "codex" ]; then
    if ! command -v codex > /dev/null 2>&1; then
        echo "ERROR: codex CLI not on PATH (needed for --researcher codex)." >&2
        exit 1
    fi
    if [ ! -f "$HOME/.codex/auth.json" ]; then
        echo "WARN: ~/.codex/auth.json missing — run 'codex login' first." >&2
    fi
    exec codex --dangerously-bypass-approvals-and-sandbox
fi

# Clear host Anthropic env.
unset ANTHROPIC_API_KEY
unset ANTHROPIC_BASE_URL
unset ANTHROPIC_AUTH_TOKEN

# Launch researcher backbone.
if [ -n "${RESEARCHER_MODEL:-}" ]; then
    echo ">> researcher backbone: claude on $RESEARCHER_MODEL via $RESEARCHER_BASE_URL"
    exec env \
        ANTHROPIC_BASE_URL="$RESEARCHER_BASE_URL" \
        ANTHROPIC_AUTH_TOKEN="$RESEARCHER_API_KEY" \
        ANTHROPIC_API_KEY= \
        claude --model "$RESEARCHER_MODEL" --dangerously-skip-permissions
fi

# Subscription researcher: host claude.ai auth (ANTHROPIC_* already unset above),
# just pin the model. No OpenRouter, no extra key.
if [ -n "${RESEARCHER_MODEL_LOCAL:-}" ]; then
    echo ">> researcher backbone: claude on $RESEARCHER_MODEL_LOCAL via host subscription auth"
    exec claude --model "$RESEARCHER_MODEL_LOCAL" --dangerously-skip-permissions
fi

exec claude --dangerously-skip-permissions
