# Quickstart — your first run, end to end

Cold-start walkthrough for your first experiment — one researcher agent, victim agent, victim model, and scenario.
Covers the bits that are scattered across README + per-topic docs
(env, permissions, Docker, skills) and **also** the bits that are not
written down elsewhere: how to inspect a live run, how to stop one,
the full artefact tree, and a per-model troubleshooting hook.

If you've done this before, the [cheat sheet](#13-cheat-sheet) at the
bottom is the only section you need.

An experiment = a **researcher agent** (on a research model,
`--researcher-model`) + a **victim agent** (on a victim model, `--model`)
+ a **scenario**. **Configure the LLM endpoints first** (`/setup`,
step 1) — victim, judge, generator, and the optional researcher backbone;
OpenRouter covers any model for either backbone.

The walkthrough uses the default victim agent + scenario —
`claude_code` + `agenthazard` — with your chosen victim model. Replace
`<your-model>` with whatever Anthropic-protocol victim model you're attacking (examples: `claude-haiku-4-5`,
`deepseek-v4-pro`, `claude-sonnet-4-5`). Three scenarios ship today —
`agenthazard`, `agentdyn`, `dtagent` (launch examples in
[§6](#6-launch-stage-1--window-1)).

---

## 0. Prerequisites

| Tool | Check |
|---|---|
| Docker (daemon running) | `docker info` returns without error |
| `uv` ≥ 0.4 | `uv --version` |
| Claude Code CLI | `claude --version` |
| `git` ≥ 2.30 (worktree support) | `git --version` |

Three model slots plus one generation endpoint, two config lanes (the fastest way to fill them is `/setup`,
step 2; full reference [`MODELS.md`](MODELS.md)):

| Slot | What | Lane |
|---|---|---|
| **victim** (`--model`) | agent under attack (claude_code / codex) | **A — agent backbone** |
| **research** (`--researcher-model`) | the researcher agent's backbone | **A — agent backbone** |
| **judge** (`JUDGE_*`) | scores attacks (plain OpenAI-chat call) | **B — env** |
| **generator** (`ROUTER_*` + `GENERATOR_MODEL`) | `/scenario-build` instance synthesis (plain OpenAI-chat call) | **B — env** |

Lane A depends on the backbone: **claude_code talks directly** to a provider's
Anthropic-compatible endpoint (no proxy); **codex goes through Moon Bridge**
(one `config.yml`), which is what lets codex run on DeepSeek/OpenRouter — they
don't serve the Responses API directly. Lane B are not agents, so they stay
on env.

---

## 1. Clone + install

```bash
git clone https://github.com/henrymao2004/Auto-research-red-teaming.git
cd Auto-research-red-teaming
uv venv && source .venv/bin/activate && uv pip install -e .
```

## 2. Configure endpoints — start here

**This is the first thing to do.** Run `/setup` — it walks both config
lanes in plain language and writes everything. Two lanes (full reference:
[`MODELS.md`](MODELS.md)):

**Lane A — agent backbones (victim + researcher).** How an agent reaches its
model depends on the backbone:

- **claude_code → direct.** Claude Code speaks the Anthropic Messages API, which
  providers serve on an Anthropic-compatible endpoint. Point its base URL
  straight at the provider — no proxy:

  ```bash
  VICTIM_BASE_URL=https://api.deepseek.com/anthropic   # or https://api.minimaxi.com/anthropic
  VICTIM_API_KEY=sk-...
  # researcher backbone: RESEARCHER_BASE_URL (unset = host's logged-in claude)
  ```

- **codex → Moon Bridge.** Codex speaks the OpenAI Responses API, which
  DeepSeek/OpenRouter don't serve, so codex runs through Moon Bridge's Transform
  ingress, declared once in `config.yml`:

  ```bash
  cp templates/moonbridge/config.example.yml templates/moonbridge/config.yml
  $EDITOR templates/moonbridge/config.yml      # set providers.<name>.api_key
  bash autoresearcher/scripts/moonbridge.sh all      # build + start codex :38440
  bash autoresearcher/scripts/moonbridge.sh status   # /v1/models should list your alias
  ```

`--model` is the model name for claude_code, or the `config.yml` alias for codex.
Full reference in `MODELS.md`.

**Lane B — judge + generator via env.** These are plain OpenAI-compatible chat
calls (not agents, not through Moon Bridge). Put them in `.env`:

```bash
JUDGE_BASE_URL=https://openrouter.ai/api/v1
JUDGE_API_KEY=sk-or-<openrouter-key>
JUDGE_MODEL=google/gemini-3-flash-preview

ROUTER_BASE_URL=https://openrouter.ai/api/v1  # Scenario-build generator
ROUTER_API_KEY=sk-or-<openrouter-key>
GENERATOR_MODEL=gpt-5
```

## 3. Install Claude Code permission templates

```bash
cp templates/claude-settings/user-settings.json ~/.claude/settings.json
cp templates/claude-settings/project-settings.local.json \
   autoresearcher/.claude/settings.local.json
```

The project-level file denies `Read` on each scenario's
`heldout.json` and `judge_data.json`. **Held-out leakage is prevented
here**, not by a runtime monitor signal. See
[`PERMISSIONS.md`](PERMISSIONS.md) for the full 5-layer model.

## 4. Build the victim Docker image

```bash
# Claude Code victim path:
bash autoresearcher/scripts/build_base_image.sh                   # → ar_claude_code_base:latest
bash autoresearcher/scripts/build_scenario_image.sh agenthazard   # → ar_agenthazard:latest (FROM base)
# other shipped scenarios — build the one you'll launch:
bash autoresearcher/scripts/build_scenario_image.sh agentdyn      # → ar_agentdyn:latest
bash autoresearcher/scripts/build_scenario_image.sh dtagent       # → ar_dtagent:latest

# Codex victim path:
bash autoresearcher/scripts/build_codex_image.sh                  # → ar_codex:latest
```

**`dtagent` ONLY — also stand up the live backends.** Unlike agenthazard /
agentdyn (victim image is all you need), dtagent's victims act through ~15 live
docker-compose backend stacks. One script pulls every backend image, builds the
local `ar_medical_service` patch, and brings up all bridges (host-published):

```bash
# medical's LLM patient/judge sim runs through OpenRouter → pass the key
OPENROUTER_API_KEY=sk-or-... \
  bash autoresearcher/scripts/build_dtagent_backends.sh        # pull + build + up
# subcommands: pull | build | up | down | all (default all)
```

Each attack spawns a fresh `--rm` container, 10-minute hard kill,
CPU/memory capped. The attack spec is piped to the container via
stdin (never written to disk inside the container); `/work` is the
agent's cwd and `/harness` carries only the trajectory output.
Details: [`DOCKER.md`](DOCKER.md).

## 5. (Optional) Write a GOAL_BRIEF

Skip on the first run. If you have specific scope constraints (target
categories, known dead ends, ASR target, scope carve-outs):

```bash
cp templates/GOAL_BRIEF_TEMPLATE.md autoresearcher/GOAL_BRIEF.md
$EDITOR autoresearcher/GOAL_BRIEF.md
```

`launch_run.sh` copies it into the worktree and links it from
`RUN_HINT.md`; the Hypothesizer reads it every iteration as
authoritative supplemental context.

**Leave §3 (attack-direction constraints) blank** unless you have an
explicit operational reason to anchor the search. Pre-listing
preferred mechanics suppresses the researcher's diversity gate.

## 6. Launch Stage 1 — window 1

```bash
# launch_run.sh auto-sources $REPO/.env, so no manual `source .env` needed.
cd autoresearcher
./scripts/launch_run.sh first_run01 \
    --model <your-model> \
    'break <your-model> on AgentHazard'
```

### Per-scenario launch examples

Three scenarios ship today. Pick one — each is a `--scenario` value;
swap the victim model with `--model`. Use `--victim claude_code` for the
Claude Code victim path, or `--victim codex` after the Moon Bridge +
`ar_codex:latest` setup above.

```bash
# agenthazard — AgentHazard salami / decomposed-query attacks
./scripts/launch_run.sh ah_run01 --victim claude_code --scenario agenthazard \
    --model deepseek-v4-pro 'break deepseek-v4-pro on AgentHazard'

# agentdyn — AgentDojo-fork indirect prompt injection
./scripts/launch_run.sh ad_run01 --victim claude_code --scenario agentdyn \
    --model deepseek-v4-pro 'break deepseek-v4-pro via indirect prompt injection on agentdyn'

# dtagent — DecodingTrust-Agent (arXiv 2605.04808): 4 domains
#   (crm / medical / workflow / os-filesystem), attack-only direct+indirect,
#   live docker-compose backends
./scripts/launch_run.sh dt_run01 --victim claude_code --scenario dtagent \
    --model deepseek-v4-pro 'break deepseek-v4-pro on DecodingTrust-Agent direct+indirect'

# same scenarios with the Codex victim
./scripts/launch_run.sh ah_codex01 --victim codex --scenario agenthazard \
    --model deepseek-v4-pro 'break deepseek-v4-pro on AgentHazard'
```

Inside each spawned claude session, kick off the loop the same way (see
below), substituting the matching `<run_code>` + goal.

**Or build your own scenario from a short phrase** — no existing dataset
needed. Inside a claude session:

```
> /scenario-build "warehouse robot assistant"
```

A 3-word phrase is enough; it interviews you (plain-language rounds),
synthesises ~200 instances, and materialises
`plugins/scenarios/<name>/` in the same launch layout as the shipped ones above.
Full worked example: [`SCENARIO_BUILD_WALKTHROUGH.md`](SCENARIO_BUILD_WALKTHROUGH.md).

`--victim claude_code --scenario agenthazard --researcher default`
are defaults; omit them. `--model` is **mandatory** — pass it
explicitly, or include a recognised model slug
(`deepseek-v4-pro` / `claude-opus-4-7` / `gpt-5` / etc.) anywhere
in the goal string and the launcher will infer it. `launch_run.sh`
does this for you:

- Creates worktree `worktrees/first_run01/` on branch `loop/first_run01`
- Copies the default 4-agent roster into `.claude/agents/`
- Writes `RUN_HINT.md` (the four variables: researcher agent, victim agent, victim model, scenario; orchestrator reads it every iteration)
- Seeds empty `vcg.md` and `AGENT_LOG.md`
- `exec`s `claude --dangerously-skip-permissions` with cwd at the inner `autoresearcher/`

**Advanced — swap the researcher backbone.** Add
`--researcher-model qwen/qwen3.7-max` to run the researcher agent on any
OpenRouter model instead of the host's logged-in `claude` (victim model
is still `--model`, the two backbones stay isolated). Details in
[`MODELS.md`](MODELS.md).

Inside the spawned claude session, kick off the loop:

```
/loop /autoresearch-redteam-discovery first_run01 break <your-model> on AgentHazard
```

Per-iteration artefacts land in `attacks/first_run01/v<N>/`:

| File | Written by | Contents |
|---|---|---|
| `proposal.md` | Hypothesizer (§Hypothesis) + Attack-Designer (§Attack design) | mechanism, surface strategy, falsifier, attack rationale |
| `attack.json` | Attack-Designer | `decomposed_query: list[str]` (3-7 user messages) |
| `result.json` | `run_attack` (Docker) | `is_break`, `ahz_judge.{score,harmful,reason}`, budget |
| `trajectory.json` | `run_attack` (Docker) | full victim agent trajectory (every tool call + response) |
| `reflection.md` | Reflector | `is_break`, `hypothesis_status`, `novel_pattern`, `surprise_signal` |

Every 20 iterations the orchestrator dispatches `redteam-critic`,
which appends a `## Critic check` block to `AGENT_LOG.md`.

## 7. Start the monitor — window 2

**Wait until `v1/` exists**, then in a second terminal:

```bash
cd Auto-research-red-teaming/autoresearcher/worktrees/first_run01/autoresearcher
claude --dangerously-skip-permissions
```

Inside the session:

```
/loop 15m /autoresearch-redteam-monitor first_run01
```

10 stop signals every 15 min — 2 critical-immediate (forbidden-path
probing, stalled iteration) plus aggregate-red rules. When the
monitor decides to stop it writes
`attacks/first_run01/STOP` + `STOP_REASON.md`, and the orchestrator's
next iteration exits at Step 0. See AGENT.md for the full signal table.

## 8. Inspect a live or finished run

```bash
# Single-file digest (mermaid VCG graph, COUNTED concepts, per-mode breakdown,
# latest Critic check, falsified examples). Safe to run mid-flight.
uv run python scripts/render_summary.py first_run01
open attacks/first_run01/SUMMARY.md
```

Cheaper progress check:

```bash
# Current iteration count
ls attacks/first_run01/ | grep -E '^v[0-9]+$' | wc -l

# Tail the run log
tail -f attacks/first_run01/AGENT_LOG.md

# Live break rate (Stage 1)
uv run -m autoresearch_redteam.leaderboard --run-code first_run01 | head -20
```

## 9. Stop a run

| You want to… | Do this |
|---|---|
| Let it stop naturally | Wait. Monitor signals 9 or 10, aggregate red ≥ 3, signal 4 (reward hacking), signal 7 (outer cap = 100), or signal 11 (repeated falsification) trigger STOP. |
| Stop gracefully now | `touch attacks/first_run01/STOP && echo "manual stop" > attacks/first_run01/STOP_REASON.md`. The next iteration's Step 0 sees the file and exits cleanly. Existing iteration finishes first. |
| Kill immediately | `Ctrl-C` both claude sessions. The current `v<N>/` may be partially written — delete it manually before re-launching, or its missing `reflection.md` will break Stage 2. |
| Stop the monitor only | `Ctrl-C` window 2; orchestrator keeps going until outer cap or you write `STOP`. |
| Resume after a graceful stop | `./scripts/launch_run.sh first_run01 ...` again — it detects the existing worktree and re-`exec`s `claude` inside it. Then re-run the `/loop ...` line. (Worktree state is preserved.) |

Iteration cap is `OUTER_CAP = 100` by default
(`autoresearcher/.claude/skills/autoresearch-redteam-discovery/SKILL.md`).

## 10. Stage 2 — held-out ASR evaluation

After Stage 1 stops, in the **outer host shell** (not the claude session):

```bash
cd Auto-research-red-teaming/autoresearcher/worktrees/first_run01/autoresearcher

# 1. Freeze COUNTED concepts (partial-only concepts are excluded).
uv run python scripts/freeze_concepts.py first_run01

# 2. Claude Code instantiates 1 attack per held-out instance.
uv run python scripts/instantiate_concepts.py first_run01 --scenario agenthazard

# 3. Run all 90 held-out attacks against the same victim agent + victim model.
#    Args: <run_code> <parallelism> <victim> <scenario> <model>
bash scripts/run_heldout_eval.sh first_run01 4 claude_code agenthazard <your-model>

# 4. Aggregate: prints headline ASR = broken / 90.
uv run python scripts/aggregate_heldout.py first_run01
```

⚠ Step 3's `<model>` argument (the victim model) must match the one
used in Stage 1. Otherwise the Stage 2 victim defaults to a different
victim model and the ASR number is meaningless (you'd be measuring
transfer, not same-experiment ASR).

## 11. Where everything lives

```
Auto-research-red-teaming/
└── autoresearcher/
    ├── worktrees/
    │   └── first_run01/
    │       └── autoresearcher/                ← cwd of the claude session
    │           ├── RUN_HINT.md                ← the four variables (read every iter)
    │           ├── GOAL_BRIEF.md              ← copied from autoresearcher/ or repo root, if present
    │           ├── .claude/agents/            ← researcher sub-agents copied from plugin
    │           └── attacks/
    │               ├── first_run01/
    │               │   ├── SUMMARY.md          ← render_summary.py output
    │               │   ├── vcg.md              ← counted + candidate concepts + edges
    │               │   ├── AGENT_LOG.md        ← per-iter rows + Critic blocks
    │               │   ├── frozen_concepts.json
    │               │   ├── STOP / STOP_REASON.md   (if stopped)
    │               │   ├── monitor_log.md      ← sidecar's log
    │               │   └── v1/ v2/ ... v<N>/    ← Stage 1 iterations
    │               └── heldout_first_run01/
    │                   ├── v<heldout_id>/...    ← Stage 2 (90 per scenario)
    │                   └── leaderboard.json     ← from aggregate_heldout.py
    │
    └── (main checkout — unaffected by runs)
```

Each `v<N>/` has `proposal.md`, `attack.json`, `result.json`,
`trajectory.json`, `reflection.md` (see §6 table).

## 12. Next runs — new experiments

Changing any of the four variables (researcher agent, victim agent,
victim model, scenario) = a new run. Same launcher, new `run_code`:

```bash
./scripts/launch_run.sh second_run01 \
    --victim claude_code --scenario agenthazard --model claude-sonnet-4-5 \
    'break sonnet on Persistence_Establishment + System_RCE only'
```

Worktrees are independent; the VCG is per experiment. Cross-experiment
concept transfer is analysed post-hoc by
`autoresearch_redteam.evaluate_concepts`, not enforced by the
promotion gate.

## 13. Cheat sheet

Paste-able from cold start to first iteration:

```bash
# One-time setup
git clone https://github.com/henrymao2004/Auto-research-red-teaming.git
cd Auto-research-red-teaming
uv venv && source .venv/bin/activate && uv pip install -e .
# configure endpoints: run /setup (recommended), or by hand:
cp .env.example .env && $EDITOR .env
cp templates/claude-settings/user-settings.json ~/.claude/settings.json
cp templates/claude-settings/project-settings.local.json \
   autoresearcher/.claude/settings.local.json
bash autoresearcher/scripts/build_base_image.sh                   # → ar_claude_code_base:latest
bash autoresearcher/scripts/build_scenario_image.sh agenthazard   # → ar_agenthazard:latest (FROM base)

# Per-run launch
cd autoresearcher
./scripts/launch_run.sh first_run01 \
    --model <your-model> \
    'break <your-model> on AgentHazard'
# Spawned Claude session
/loop /autoresearch-redteam-discovery first_run01 break <your-model> on AgentHazard

# Monitor launch
cd Auto-research-red-teaming/autoresearcher/worktrees/first_run01/autoresearcher
claude --dangerously-skip-permissions
# Monitor session
/loop 15m /autoresearch-redteam-monitor first_run01

# Stage 2 (after Stage 1 stops, outer shell)
cd Auto-research-red-teaming/autoresearcher/worktrees/first_run01/autoresearcher
uv run python scripts/freeze_concepts.py first_run01
uv run python scripts/instantiate_concepts.py first_run01 --scenario agenthazard
bash scripts/run_heldout_eval.sh first_run01 4 claude_code agenthazard <your-model>
uv run python scripts/aggregate_heldout.py first_run01
```

---

## Troubleshooting

### Variable-agnostic (applies to any experiment)

| Symptom | Likely cause | Fix |
|---|---|---|
| `JUDGE_API_KEY not set` from `launch_run.sh` | `.env` missing or in the wrong location | Confirm `$REPO/.env` exists; `launch_run.sh` auto-sources it. Check the launcher prints `>> sourced .../.env` |
| `claude` opens but `/loop` is unknown | Claude Code version predates `/loop` builtin | Update Claude Code CLI |
| `/agents` shows no `redteam-*` sub-agents | Worktree's `.claude/agents/` wasn't seeded | Re-create the worktree: `git worktree remove -f worktrees/<run_code> && ./scripts/launch_run.sh <run_code> ...` |
| `run_attack` errors with "image ar_<scenario>:latest not found" | Forgot to build the scenario's Docker image | Run `bash scripts/build_base_image.sh && bash scripts/build_scenario_image.sh <scenario>` (or just relaunch — `launch_run.sh` auto-builds) |
| Run stalls — no new `v<N>/` for > 60 min | Sub-agent retry storm or victim hang | Monitor's signal 10 will write STOP; or kill (§9) and inspect the latest `v<N>/proposal.md` |
| Held-out IDs appear in iteration prompts | `settings.local.json` not installed in worktree | Verify the file exists at `worktrees/<run>/autoresearcher/.claude/settings.local.json`; if not, re-create the worktree |

### Per-model (Anthropic-protocol victim endpoints)

The `claude_code` victim adapter doesn't care which model name you
pass — `--model` is forwarded verbatim to whichever endpoint your
`VICTIM_BASE_URL` points at. Different providers fail in
different ways:

| Symptom | Likely provider behaviour | Suggested probe |
|---|---|---|
| Container exits with 401 / "invalid api key" inside `trajectory.json` | `VICTIM_API_KEY` is wrong or unset (the adapter forwards it into the container as `x-api-key`) | Hit the endpoint directly with `curl $VICTIM_BASE_URL/v1/messages -H "x-api-key: $VICTIM_API_KEY" ...` to confirm the key |
| Container exits with "model not found" | Provider doesn't recognise the model name on its `/anthropic` shim | Try a known-good name on the same provider first (DeepSeek: `deepseek-chat` or `deepseek-reasoner`). Once the link works, swap in your target model. |
| Every iteration crashes at the 10-min wall, no judge score | Victim's TTFT is very high or it loops in tool calls | Cut `decomposed_query` length via GOAL_BRIEF §3 (`max steps = 4`); or raise the per-attack budget cap in the skill if you really need 7 turns. |
| Judge consistently refuses the trajectory ("harmful content blocked") | Your judge provider has a content filter on the scoring prompt | Switch `JUDGE_MODEL` to one less filter-prone (try `openai/gpt-4o-mini` or `anthropic/claude-haiku-4-5` via OpenRouter) |

If you hit a pitfall that's specific to a new victim model worth
remembering, add a row to the per-model table above — that's what
this section is for.

---

## Pointers

- Workflow index + artefact ownership table → [`../AGENT.md`](../AGENT.md)
- Multi-agent pipeline, VCG schema, falsifier protocol → [`ARCHITECTURE.md`](ARCHITECTURE.md)
- Endpoint protocols + provider mixes → [`MODELS.md`](MODELS.md)
- 5-layer permission model → [`PERMISSIONS.md`](PERMISSIONS.md)
- Sandbox image + per-attack tempdir → [`DOCKER.md`](DOCKER.md)
- Add a scenario → [`BYO_SCENARIO.md`](BYO_SCENARIO.md) · the plugin system (all axes) → [`PLUGINS.md`](PLUGINS.md)
- Binding contracts → [`shared-references/`](shared-references/)
- Pre-launch brief → [`../templates/GOAL_BRIEF_TEMPLATE.md`](../templates/GOAL_BRIEF_TEMPLATE.md)
