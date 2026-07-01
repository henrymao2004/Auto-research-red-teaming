# Auto-research-red-teaming-in-sleep (AHA)

[![Paper](https://img.shields.io/badge/Paper-arXiv%3ATBD-b31b1b?style=flat&logo=arxiv&logoColor=white)](https://arxiv.org/abs/TBD) · [![AI Agents](https://img.shields.io/badge/AI%20Agents-AGENT.md-4B2E83?style=flat&logo=readthedocs&logoColor=white)](AGENT.md) · [![Cite Paper](https://img.shields.io/badge/Cite%20Paper-BibTeX-4c8c11?style=flat)](#citation)

🌙 *Run autonomous red-team experiments against LLM agents while you sleep.*

🤖 **AI agents:** Read [`AGENT.md`](AGENT.md) instead — structured for LLM consumption, not human browsing.

> 🪶 **Sleep-time autoresearch red-teaming.** Pick a victim agent and model, choose an existing scenario or build/import your own, launch an overnight run, monitor it, and evaluate the resulting attacks on held-out tasks.

AHA is an engineering harness for **black-box red-teaming of LLM agents**. It gives you plugin axes for researcher agents, victim agents, and scenarios; per-attack Docker sandboxes; guided `/scenario-build` and `/scenario-import` flows; monitor sidecars; and one-command held-out evaluation. Use it to test coding agents, tool-using agents, prompt-injection environments, or internal benchmark suites without rewriting the experiment loop each time.

**Use cases**

- Red-team a coding or tool-using agent against a concrete benchmark.
- Import your internal benchmark and run the same discovery/evaluation loop.
- Build a new scenario from a threat idea, then evaluate held-out transfer.

## 🎯 More than just a prompt

**Basic mode** — pick a victim agent + scenario, name the victim model with `--model`, and give an outer goal:

```
cd autoresearcher
./scripts/launch_run.sh my_first_run \
    --victim claude_code --scenario agenthazard \
    --model deepseek-v4-pro \
    'break deepseek-v4-pro on AgentHazard'
```

Defaults are `--victim claude_code --scenario agenthazard --researcher default`; `--model` is **mandatory** (pass it explicitly, or include a recognised model slug in the goal string and the launcher infers it).

**The variables of an experiment.** Three are registry-discovered plugin axes; two are runtime model params:

| Variable          | What it is                                                                 | How it's chosen                           |
| ----------------- | -------------------------------------------------------------------------- | ----------------------------------------- |
| **researcher agent** | the harness running the attack-search **method** (which sub-agents it dispatches each round) | plugin — `--researcher` (`plugins/researchers/<name>/`, default `default`) |
| **research model** | the LLM the researcher agent (orchestrator + sub-agents) runs on | runtime — `--researcher-model` / `RESEARCHER_MODEL` (defaults to the host claude/codex login) |
| **victim agent**  | the harness **under attack**                                          | plugin — `--victim` (`plugins/victims/<name>/`, default `claude_code`) |
| **victim model**  | the LLM the **victim agent** runs on — the target being attacked | runtime — `--model` (**mandatory**, e.g. `deepseek-v4-pro`) |
| **scenario**      | task suite + attack family + judge                        | plugin — `--scenario` (`plugins/scenarios/<name>/`, default `agenthazard`) |

`--model` selects the **victim model only**; the **research model** is set via `--researcher-model` and is fully isolated from the victim backbone; neither is the judge model (`JUDGE_MODEL`) nor the Stage-2 Claude Code instantiator. The same **victim-agent** harness on a different **victim model** is a different experiment.

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
Full worked example: [`docs/SCENARIO_BUILD_WALKTHROUGH.md`](docs/SCENARIO_BUILD_WALKTHROUGH.md).

**Import an existing benchmark** (pip / git / HuggingFace / local files):

```
> /scenario-import "harmbench from https://github.com/centerforaisafety/HarmBench"
# Inspects upstream, interviews you on the contract + judge, drafts a
# convert.py from the matching recipe, extracts data into the standard
# layout. AgentDojo is the canonical example output.
```

## ✨ Features

- 🪶 **Radically general — bring your own anything.** The **researcher
  agent**, the **victim agent**, and the **scenario** are each a
  registry-discovered plugin; every scenario is a single `contract.yaml`.
  Synthesize a scenario from a sentence, import a published benchmark, or
  wire a custom attack channel through an interview — no Python to write —
  and the loop keeps working.
- 💡 **An experiment runs a researcher agent on a research model and a
  victim agent on a victim model**, plus a scenario (task suite + attack
  family + judge). The researcher agent, victim agent, and scenario are
  registry-discovered plugins; the **research model** (`--researcher-model`
  / `RESEARCHER_MODEL`) and the **victim model** (`--model`) are runtime
  params. Judge and instance-generation models are separate slots. Configure all
  providers through `/setup`; the model-slot reference lives in
  [`docs/MODELS.md`](docs/MODELS.md).

## 🚀 Quick start

Five steps: install, setup, build image, launch, evaluate. The full
walkthrough is [`docs/QUICKSTART.md`](docs/QUICKSTART.md); provider
details are in [`docs/MODELS.md`](docs/MODELS.md).

| Step | Command |
|---|---|
| Install | `git clone https://github.com/henrymao2004/Auto-research-red-teaming.git && cd Auto-research-red-teaming && uv venv && source .venv/bin/activate && uv pip install -e .` |
| Setup | Run `/setup`, or copy `templates/model-config/minimal.env` to `.env`; then install `templates/claude-settings/*.json` as shown in [`SETUP_GUIDE.md`](SETUP_GUIDE.md). |
| Build image | `bash autoresearcher/scripts/build_base_image.sh && bash autoresearcher/scripts/build_scenario_image.sh agenthazard` |
| Launch | `cd autoresearcher && ./scripts/launch_run.sh ah_run --victim claude_code --scenario agenthazard --model <victim-model> 'break <victim-model> on AgentHazard'` |
| Evaluate | In the spawned session run `/loop /autoresearch-redteam-discovery ah_run break <victim-model> on AgentHazard`; after stop, run `/concept-eval ah_run`. |

### 5-minute dry run

Validate the install path without DTap, Docker backends, or model keys:

```bash
bash autoresearcher/scripts/dry_run.sh
bash autoresearcher/scripts/doctor.sh
```

The dry run uses bundled AgentHazard metadata, fake model config, and one
synthetic iteration artifact to exercise registry loading and summary
rendering. Details: [`docs/DRY_RUN.md`](docs/DRY_RUN.md).

| Stage                | What it does                                                                                 | Command                                                                                                                  |
| -------------------- | -------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Scenario bootstrap   | Interview → contract.yaml → N synthesised instances → plugin materialised                    | `/scenario-build "<free-text scenario idea>"`                                                                            |
| Stage 1 (autonomous search) | Iterate on the discovery set, saving attacks, trajectories, reflections, and run summaries | `cd autoresearcher && ./scripts/launch_run.sh <run> --model M '<goal>'` → `/loop /autoresearch-redteam-discovery <run> <goal>` |
| Monitor              | Sidecar, 10 stop signals every 15 min                                                        | `/loop 15m /autoresearch-redteam-monitor <run>`                                                                          |
| Stage 2 (held-out eval) | Turn the run artifacts into held-out attacks, execute them, and report headline ASR        | `/concept-eval <run>` (chains the raw scripts)                                                                           |

## 🔄 Workflows

### `/scenario-build` — bootstrap a NEW scenario (LLM-synth)

For ideas with no existing dataset. Free text → contract → synthesised
instances → launchable plugin. The interview is plain-language throughout
(each question leads with everyday words and concrete examples; the
contract field it fills is a trailing aside).

See [`docs/SCENARIO_BUILD_WALKTHROUGH.md`](docs/SCENARIO_BUILD_WALKTHROUGH.md)
for a full worked `/scenario-build` interview (start keyword `warehouse
robot`, mixes reuse-existing + custom→`/scenario-extend` answers). For
the generated plugin layout and hand-author path, see
[`docs/BYO_SCENARIO.md`](docs/BYO_SCENARIO.md).

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
structure is documented in [`docs/BYO_SCENARIO.md`](docs/BYO_SCENARIO.md).

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
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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

## 🧩 Plugins

The key axes of an experiment:

- **scenario** — `--scenario` (`plugins/scenarios/<name>/`): task suite +
  attack family + judge.
- **research agent + victim agent** — `--researcher`
  (`plugins/researchers/<name>/`, the attack-search method) and
  `--victim` (`plugins/victims/<name>/`, the harness under attack).
- **research model** — `--researcher-model` / `RESEARCHER_MODEL`: the LLM
  the researcher agent runs on.
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

See [`docs/PLUGINS.md`](docs/PLUGINS.md) for the registry + Protocol
description, and [`docs/BYO_SCENARIO.md`](docs/BYO_SCENARIO.md) for the
scenario-authoring guide.

## 🏗️ Architecture

```
                         Window 1                                Window 2
            ┌─────────────────────────┐                ┌──────────────────┐
            │ Orchestrator + sub-     │                │ Monitor          │
            │  agents (researcher     │                │  (researcher     │
            │  agent on the RESEARCH  │                │   agent,         │
            │  MODEL — claude/codex   │                │   /loop 15m)     │
            │  via --researcher-model)│                │                  │
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
            │ │  reflector,    │      │
            │ │  sonnet)       │      │
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
model** (`--researcher-model` / `RESEARCHER_MODEL`); the victim agent runs
on the **victim model** (`--model`). The judge and instance generator are
separate host-side calls; Stage 2 uses a separate Claude Code
instantiator. The isolation guarantees are described in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md); endpoint setup is in
[`docs/MODELS.md`](docs/MODELS.md).

## 🔌 Endpoints

The core model slots are configured by **`/setup`**: research model,
victim model, judge model, and the scenario-build generator endpoint.
Full provider and endpoint details
live in [`docs/MODELS.md`](docs/MODELS.md).

## 🏃 Running autonomously

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

See [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md) for the full permission
model.

## 📚 Documentation

| Doc                                                                | Contents                                                                  |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------- |
| [`SETUP_GUIDE.md`](SETUP_GUIDE.md)                                 | Install, model config, Claude settings, image build, and first launch     |
| [`docs/DRY_RUN.md`](docs/DRY_RUN.md)                               | Offline 5-minute smoke test with fake model config and one synthetic iteration |
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md)                         | First-run walkthrough: cold start to held-out ASR, with stop / inspect / troubleshoot |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)                     | Multi-agent pipeline, run artifacts, model slots, isolation boundaries    |
| [`docs/PLUGINS.md`](docs/PLUGINS.md)                               | The plugin layout + runtime registry (all three axes)                     |
| [`docs/BYO_SCENARIO.md`](docs/BYO_SCENARIO.md)                     | Bring-your-own scenario (build / import / hand-author + its attack family) |
| [`docs/MODELS.md`](docs/MODELS.md)                       | pick provider/format/key per slot — claude_code direct, codex via Moon Bridge, env for judge/generator       |
| [`docs/DOCKER.md`](docs/DOCKER.md)                                 | Victim sandbox image, per-attack tempdir, customisation                   |
| [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md)                       | Claude Code permission model, autonomous-agent standard                   |
| [`docs/BUILTIN_SCENARIOS.md`](docs/BUILTIN_SCENARIOS.md)           | The shipped example scenarios (AgentHazard + AgentDyn + DTAP/DecodingTrust-Agent): splits, schemas, attack families |
| [`docs/shared-references/`](docs/shared-references/)               | Internal binding contracts used by the skills and sub-agents              |
| [`templates/GOAL_BRIEF_TEMPLATE.md`](templates/GOAL_BRIEF_TEMPLATE.md) | Pre-launch brief template: target, attack families, dead ends, ASR target, budget, scope |
| [`SECURITY.md`](SECURITY.md)                                       | Sandbox boundary, local execution model, benchmark seed policy            |
| [`CONTRIBUTING.md`](CONTRIBUTING.md)                               | Add scenarios/victims and run smoke checks                                |
| [`CHANGELOG.md`](CHANGELOG.md)                                     | Release notes and supported launch matrix                                 |

## 📋 Status

The shipped agent victims (`claude_code`, `codex`) and shipped scenarios
(`agenthazard`, `agentdyn`, `dtagent`) are registry-discovered plugins;
`run_attack --list` is the source of truth for the current launch matrix.

Current release: **v0.1.0 initial public release**. See
[`CHANGELOG.md`](CHANGELOG.md).

**Planned**

- **`raw_llm`** — text-only chat-completions victim against an
  OpenAI-compatible endpoint. Pairs with chat-level jailbreak scenarios
  (HarmBench, AdvBench, BeaverTails) imported via `/scenario-import`.
- **`raw_vlm`** — VLM victim with `image_url` content blocks. Pairs with
  multimodal jailbreak scenarios (MM-SafetyBench, FigStep, HADES).

## Citation

If you use the paper or this repo, please cite:

```bibtex
@misc{mao2026autoresearchredteaming,
  title         = {Auto-Research Red-Teaming in Sleep},
  author        = {Mao, Xutao and Zheng, Xiang and Wang, Cong},
  year          = {2026},
  eprint        = {TBD},
  archivePrefix = {arXiv},
  url           = {https://arxiv.org/abs/TBD}
}
```

## 🙏 Acknowledgements

- [AgentHazard](https://github.com/Yunhao-Feng/AgentHazard) for the
  bundled scenario data.
- [AgentDojo](https://agentdojo.spylab.ai/) for the
  indirect-prompt-injection paradigm.
- [DecodingTrust-Agent (DTap)](https://github.com/AI-secure/DecodingTrust-Agent.git)
  for the `dtagent` scenario data.
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code),
  [`claude-agent-sdk`](https://github.com/anthropics/claude-agent-sdk-python),
  [Codex CLI](https://github.com/openai/codex),
  and [OpenRouter](https://openrouter.ai) for the runtime stack.
- [Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/tree/main)
  for inspiration on the README organization.

## License

MIT — see [`LICENSE`](LICENSE).
