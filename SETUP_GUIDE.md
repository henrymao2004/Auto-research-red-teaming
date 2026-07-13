# Setup guide

This guide gets a machine from a fresh clone to a runnable AHA setup.
Use `docs/QUICKSTART.md` for a full walkthrough after setup succeeds.

## 1. Install

```bash
git clone https://github.com/henrymao2004/Auto-research-red-teaming.git
cd Auto-research-red-teaming
uv venv && source .venv/bin/activate
uv pip install -e .
```

## 2. Configure models

Run `/setup` from your agent session, or copy the minimal template and
fill it by hand:

```bash
cp templates/model-config/minimal.env .env
$EDITOR .env
```

Model slot details live in `docs/MODELS.md`. In short:

- `VICTIM_MODEL`, `VICTIM_BASE_URL`, `VICTIM_API_KEY` drive the victim.
- `JUDGE_MODEL`, `JUDGE_BASE_URL`, `JUDGE_API_KEY` drive judges.
- Claude researchers can use `RESEARCHER_MODEL_LOCAL=claude-5-fable`
  for host subscription auth, or `RESEARCHER_MODEL=<provider/model>`
  with `RESEARCHER_API_KEY` for OpenRouter.
- Codex researchers use `--researcher codex --researcher-model gpt-5.5`
  or `gpt-5.4` with host Codex auth.
- Codex victims use Moon Bridge; see `docs/MODELS.md`.

## 3. Install Claude Code settings

```bash
mkdir -p ~/.claude autoresearcher/.claude
cp templates/claude-settings/user-settings.json ~/.claude/settings.json
cp templates/claude-settings/project-settings.local.json \
   autoresearcher/.claude/settings.local.json
```

The project settings are scoped to this repo and include the held-out
read-deny rules.

## 4. Run local checks

```bash
bash autoresearcher/scripts/dry_run.sh
bash autoresearcher/scripts/doctor.sh
```

The dry run is offline. `doctor.sh` can warn before Docker images or DTap
backends are built; only `FAIL` lines block a basic install.

## 5. Build images

```bash
bash autoresearcher/scripts/build_base_image.sh
bash autoresearcher/scripts/build_scenario_image.sh agenthazard
```

For AgentDyn and DTap image/backend setup, use `docs/DOCKER.md` and
`docs/QUICKSTART.md`.

## 6. Launch

```bash
cd autoresearcher
./scripts/launch_run.sh first_run01 \
  --victim claude_code --scenario agenthazard \
  --model "$VICTIM_MODEL" \
  "break $VICTIM_MODEL on AgentHazard"
```

Inside the spawned agent session:

```text
/loop /autoresearch-redteam-discovery first_run01 break <model> on AgentHazard
```

After the run stops:

```bash
uv run python scripts/render_summary.py first_run01
```

## 7. (Optional) Workflow driver setup

The default `/loop /autoresearch-redteam-discovery` path above needs no
extra setup. If you want the optional deterministic, batched-parallel
Workflow driver instead, register its MCP server for the session:

```bash
export AHA_WORKSPACE=<worktree root>   # dir containing attacks/ + RUN_HINT.md
claude mcp add aha-discovery -- uv run -m autoresearch_redteam.discovery_mcp
# or put plugins/researchers/default/workflows/.mcp.json on the session's
# MCP search path directly
```

See `docs/USAGE.md` and
`autoresearcher/plugins/researchers/default/workflows/README.md` for the
full run procedure.
