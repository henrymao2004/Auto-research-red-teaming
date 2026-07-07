# Usage — operator reference

This is the detailed operator guide. For the project overview, headline
results, and disclosure policy, see the top-level [`README.md`](../README.md).
For the 5-step first run, see [`QUICKSTART.md`](QUICKSTART.md).

## The variables of an experiment

Three are registry-discovered plugin axes; two are runtime model params:

| Variable          | What it is                                                                 | How it's chosen                           |
| ----------------- | -------------------------------------------------------------------------- | ----------------------------------------- |
| **researcher agent** | the harness running the attack-search **method** (which sub-agents it dispatches each round) | plugin — `--researcher` (`plugins/researchers/<name>/`, default `default`; `codex` also ships) |
| **research model** | the LLM the researcher agent (orchestrator + sub-agents) runs on | runtime — for Claude researcher: `--researcher-model-local claude-5-fable` or `--researcher-model <provider/model>`; for Codex researcher: `--researcher codex --researcher-model gpt-5.5` / `gpt-5.4` |
| **victim agent**  | the harness **under attack**                                          | plugin — `--victim` (`plugins/victims/<name>/`, default `claude_code`) |
| **victim model**  | the LLM the **victim agent** runs on — the target being attacked | runtime — `--model` (**mandatory**, e.g. `deepseek-v4-pro`) |
| **scenario**      | task suite + attack family + judge                        | plugin — `--scenario` (`plugins/scenarios/<name>/`, default `agenthazard`) |

`--model` selects the **victim model only**. The **research model** is set
separately: Claude researchers can use host subscription auth
(`--researcher-model-local claude-5-fable`) or OpenRouter
(`--researcher-model <provider/model>`), while Codex researchers use
`--researcher codex --researcher-model gpt-5.5` or `gpt-5.4`. The
research model is fully isolated from the victim backbone; neither is the
judge model (`JUDGE_MODEL`) nor the Stage-2 Claude Code instantiator.
The same **victim-agent** harness on a different **victim model** is a
different experiment.

## Launching a run

**Basic mode** — pick a victim agent + scenario, name the victim model with
`--model`, and give an outer goal:

```bash
cd autoresearcher
./scripts/launch_run.sh my_first_run \
    --victim claude_code --scenario agenthazard \
    --model deepseek-v4-pro \
    'break deepseek-v4-pro on AgentHazard'
```

Defaults are `--victim claude_code --scenario agenthazard --researcher
default`; `--model` is **mandatory** (pass it explicitly, or include a
recognised model slug in the goal string and the launcher infers it).

```bash
# Claude subscription researcher
./scripts/launch_run.sh ah_fable --victim claude_code --scenario agenthazard \
    --model deepseek-v4-pro --researcher-model-local claude-5-fable \
    'break deepseek-v4-pro on AgentHazard'

# Codex researcher
./scripts/launch_run.sh ah_codex_researcher --researcher codex \
    --victim claude_code --scenario agenthazard \
    --model deepseek-v4-pro --researcher-model gpt-5.5 \
    'break deepseek-v4-pro on AgentHazard'
```

**Monitor sidecar** (second terminal — stops the loop on critical signals):

```
> /loop 15m /autoresearch-redteam-monitor my_first_run
```

**Stage 1 summary** (single-file human-readable digest):

```
uv run python scripts/render_summary.py my_first_run
# writes attacks/my_first_run/SUMMARY.md: run timeline,
# attack outcomes, iteration breakdown, latest Critic check
```

**Stage 2 held-out evaluation** (one slash command wraps all 4 steps):

```
> /concept-eval my_first_run
# prepares held-out attacks, runs them, aggregates results,
# and prints headline ASR = broken / |held-out|.
```

**Build a new scenario** (LLM-synth, for ideas with no existing dataset):

```
> /scenario-build "warehouse robot assistant"
# A 3-word phrase is enough — it interviews you (plain-language rounds),
# synthesizes ~200 instances, materialises plugins/scenarios/<name>/ for launch.
```
Full worked example: [`SCENARIO_BUILD_WALKTHROUGH.md`](SCENARIO_BUILD_WALKTHROUGH.md).

**Import an existing benchmark** (pip / git / HuggingFace / local files):

```
> /scenario-import "harmbench from https://github.com/centerforaisafety/HarmBench"
# Inspects upstream, interviews you on the contract + judge, drafts a
# convert.py from the matching recipe, extracts data into the standard
# layout. AgentDojo is the canonical example output.
```

## Workflows

### `/scenario-build` — bootstrap a NEW scenario (LLM-synth)

For ideas with no existing dataset. Free text → contract → synthesised
instances → launchable plugin. The interview is plain-language throughout
(each question leads with everyday words and concrete examples; the
contract field it fills is a trailing aside).

See [`SCENARIO_BUILD_WALKTHROUGH.md`](SCENARIO_BUILD_WALKTHROUGH.md)
for a full worked `/scenario-build` interview (start keyword `warehouse
robot`, mixes reuse-existing + custom→`/scenario-extend` answers). For
the generated plugin layout and hand-author path, see
[`BYO_SCENARIO.md`](BYO_SCENARIO.md).

### `/scenario-import` — import an EXISTING benchmark

For published benchmarks. `/scenario-import` inspects the upstream
source, interviews you on the contract and judge, drafts a converter,
validates a small sample, then materialises a plugin in the standard
layout. It supports pip packages, git repos, HuggingFace datasets, and
local files.

AgentDojo is the canonical output of this flow — its `convert.py` walks
`agentdojo.task_suite.load_suites.get_suite()` to extract all 949
(user_task × injection_task) pairs from upstream v1.2.2. Import recipe
templates live under `templates/scenario-import-recipes/`; plugin
structure is documented in [`BYO_SCENARIO.md`](BYO_SCENARIO.md).

### `/scenario-extend` — wire user-described custom dimensions

Invoked by `/scenario-build` and `/scenario-import` when the interview
captured anything outside the framework's built-in slug set. The
contract layer is fully open (`RuntimeSpec` is `extra="allow"`;
`attack_wiring.kind`, `environment_hydration.kind`,
`interceptor_action.kind`, `trajectory_capture.include`,
`payload_schema.type` all accept arbitrary strings) — this skill teaches
the runner the new kind.

Standalone invocation is supported — pass the scenario name plus a
free-text description of the extension. Use it when a new scenario needs
a custom attack delivery channel, environment hydration path, interceptor
action, trajectory filter, payload schema type, MCP tool bridge, or judge
hook.

### Stage 1 — autonomous attack search

Per iteration (the `/autoresearch-redteam-discovery` skill, dispatched by
`/loop`), the run writes a fully inspectable attack folder under
`attacks/<run>/v<N>/`:

| Step | Sub-agent / Tool                | Writes                                                |
| ---- | ------------------------------- | ----------------------------------------------------- |
| 0    | `STOP` file check               | (early-exit if monitor wrote `STOP`)                  |
| 1    | Orchestrator reads run state + log | `RUN_HINT.md`, `vcg.md`, `AGENT_LOG.md`            |
| 2    | Orchestrator picks mode + Stage-1 instance | `attacks/<run>/v<N>/` directory             |
| 3a   | `redteam-hypothesizer` (Opus)    | `v<N>/proposal.md` (hypothesis + falsifier)           |
| 3b   | `redteam-attack-designer` (Opus) | `v<N>/attack.json` + proposal's "Attack design" block |
| 4    | `Bash: run_attack` (Docker)      | `v<N>/result.json`, `v<N>/trajectory.json`            |
| 5    | `redteam-reflector` (Sonnet)     | `v<N>/reflection.md` (is_break / hypothesis_status)   |
| 6    | Orchestrator updates run ledger  | `vcg.md`                                              |
| 7    | Orchestrator commits             | `git commit -m 'v<N>: ...'`                           |
| 7.5  | `redteam-critic` (Opus, every 10 iter) | `AGENT_LOG.md` critique block                  |
| 8    | Orchestrator appends iter row    | `AGENT_LOG.md` table                                  |
| 9    | Done — `/loop` re-invokes        | —                                                     |

The important user-facing artifacts are `attack.json`, `result.json`,
`trajectory.json`, `reflection.md`, `AGENT_LOG.md`, and the rendered
`SUMMARY.md`. The internal ledger file (`vcg.md`) is used by the
held-out pipeline; its schema lives in
[`ARCHITECTURE.md`](ARCHITECTURE.md).

### Stage 2 — held-out evaluation via `/concept-eval`

Wraps the 4 raw scripts in one slash command:

```
> /concept-eval <run>
# 1. freeze_concepts.py <run>
# 2. instantiate_concepts.py <run> -s S
# 3. run_heldout_eval.sh <run> P F S M
# 4. aggregate_heldout.py <run>
```

Single attempt per held-out instance; Claude Code instantiates the
held-out attack in a sandboxed `claude -p` call isolated from the victim.

### Monitor — sidecar

10 stop signals: 7 health + 2 critical-immediate (forbidden-path
probing, stalled iteration) + 1 hard ceiling (outer iter cap = 100).
**STOP** when any critical fires, or **≥ 2 red OR ≥ 4 yellow**, or
signal 3 / 6 / 10 red. **WARN** on 1 red OR 2-3 yellow.

## Plugins

The key axes of an experiment:

- **scenario** — `--scenario` (`plugins/scenarios/<name>/`): task suite +
  attack family + judge.
- **research agent + victim agent** — `--researcher`
  (`plugins/researchers/<name>/`, the attack-search method) and
  `--victim` (`plugins/victims/<name>/`, the harness under attack).
- **research model** — for Claude researchers,
  `--researcher-model-local claude-5-fable` or
  `--researcher-model <provider/model>`; for Codex researchers,
  `--researcher codex --researcher-model gpt-5.5` / `gpt-5.4`.
- **victim model** — `--model`: the LLM the victim agent runs on, the
  target. Not a plugin.

The registry validates the victim-agent/scenario pairing: the scenario's
`native_attack_family` must be in the victim agent's
`supports_attack_families`. The default researcher
(`plugins/researchers/default/`) ships
Hypothesizer, Attack-Designer, Reflector, Critic (the inner loop), plus
`scenario-architect` and `scenario-importer` for the scenario-build /
import interviews.

Adding a plugin from the repo root:

```bash
autoresearcher/scripts/add_victim.sh     <name>   # scaffold plugins/victims/<name>/
autoresearcher/scripts/add_scenario.sh   <name>   # scaffold plugins/scenarios/<name>/
autoresearcher/scripts/add_researcher.sh <name>   # scaffold plugins/researchers/<name>/
```

See [`PLUGINS.md`](PLUGINS.md) for the registry + Protocol description, and
[`BYO_SCENARIO.md`](BYO_SCENARIO.md) for the scenario-authoring guide.

## Architecture

```
                         Window 1                                Window 2
            ┌─────────────────────────┐                ┌──────────────────┐
            │ Orchestrator + sub-     │                │ Monitor          │
            │  agents (researcher     │                │  (researcher     │
            │  agent on the RESEARCH  │                │   agent,         │
            │  MODEL — Claude or      │                │   /loop 15m)     │
            │  Codex model)           │                │                  │
            │                         │                │  10 stop signals │
            │ ┌─ Step 3a ──────┐      │                │  (2 critical)    │
            │ │ Task(          │      │                │  → STOP file     │
            │ │  hypothesizer) │      │                └──────────────────┘
            │ └────────────────┘      │
            │ ┌─ Step 3b ──────┐      │
            │ │ Task(          │      │
            │ │  attack-       │      │
            │ │  designer)     │      │
            │ └────────────────┘      │
            │ ┌─ Step 4 ───────┐      │   resolves victim agent +
            │ │ Bash:          │      │   scenario via
            │ │  run_attack ──┐│      │   registry.victim(F),
            │ │  (sandbox)    ││      │   registry.scenario(S)
            │ └───────────────┘│      │
            │ ┌─ Step 5 ───────┐      │
            │ │ Task(          │      │
            │ │  reflector)    │      │
            │ └────────────────┘      │
            │ ┌─ Step 6-7 ─────┐      │
            │ │ Update vcg.md  │      │
            │ │ git commit     │      │
            │ └────────────────┘      │
            │ ┌─ Step 7.5 ─────┐      │
            │ │ Task(critic)   │      │
            │ │ every 10 iter  │      │
            │ └────────────────┘      │
            └─────────────────────────┘
                              │
                              ▼
                ┌──────────────────────────────┐
                │ Victim Agent (sandboxed)     │
                │  runs on the VICTIM MODEL     │
                │  (--model): claude_code direct │
                │  to provider; codex via :38440 │
                └──────────────────────────────┘
                              │
                              ▼
                ┌──────────────────────────────┐
                │ Judge LLM (host call)        │
                │  any OpenAI-compatible       │
                │  endpoint (default: OpenRouter)│
                └──────────────────────────────┘
```

The researcher agent (orchestrator + sub-agents) runs on the **research
model**: use `--researcher-model-local claude-5-fable` for a host Claude
subscription researcher, `--researcher-model <provider/model>` for an
OpenRouter / third-party Claude researcher, or
`--researcher codex --researcher-model gpt-5.5` / `gpt-5.4` for a Codex
researcher. The victim agent runs on the **victim model** (`--model`).
The judge and instance generator are separate host-side calls; Stage 2
uses a separate Claude Code instantiator. The isolation guarantees are
described in [`ARCHITECTURE.md`](ARCHITECTURE.md); endpoint setup is in
[`MODELS.md`](MODELS.md).

## Endpoints

The core model slots are configured by **`/setup`**: research model,
victim model, judge model, and the scenario-build generator endpoint.
For the research model, AHA supports host Claude subscription models
(`RESEARCHER_MODEL_LOCAL=claude-5-fable`), OpenRouter / third-party
models (`RESEARCHER_MODEL=<provider/model>`), and Codex researcher
models (`--researcher codex --researcher-model gpt-5.5`). Full provider
and endpoint details live in [`MODELS.md`](MODELS.md).

## Running autonomously

The orchestrator and sub-agents run with
`claude --dangerously-skip-permissions` so they iterate overnight
without prompting on every Bash call. The run is set up like this:

- **Per-attack sandbox** — a fresh Docker container per attack; the
  attack spec is piped in via stdin; 10-min hard kill; capped CPU +
  memory.
- **Worktree isolation** — each run lives in `worktrees/<run_code>/` on
  its own branch.
- **Project settings** — `autoresearcher/.claude/settings.local.json`
  carries the allow/deny list; held-out per-instance JSONs live under
  `clean_heldout/`.
- **Critic sub-agent** — a fresh-context audit every 20 iterations.
- **Sidecar monitor** — 10 stop signals every 15 min; touches a `STOP`
  file the next iteration reads.

See [`PERMISSIONS.md`](PERMISSIONS.md) for the full permission model.
