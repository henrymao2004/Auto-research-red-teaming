# Plugin system

`Auto-research-red-teaming-in-sleep` is a **general autoresearch-in-red-teaming
system**. The case studies the paper ships (Claude Code / Codex ×
{AgentHazard, AgentDyn, DTAgent}) are just instances of the plugin
system below; nothing in the core orchestrator depends on them.

## The variables of an experiment

An experiment runs a **researcher agent on a research model** and a
**victim agent on a victim model**, plus a **scenario**. Three of these
are registry-discovered plugin axes; the two models are runtime
parameters — there is **no "model plugin"**:

| Variable             | What it is                                                                  | How it's chosen                                          |
| -------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------- |
| **researcher agent** | the agent harness running the attack-discovery method (which sub-agents it dispatches each round) | plugin — `--researcher` (`plugins/researchers/<name>/`)  |
| **research model**   | the LLM the researcher agent (orchestrator + sub-agents) runs on            | runtime — `--researcher-model` / `RESEARCHER_MODEL`      |
| **victim agent**     | the agent harness under attack                                              | plugin — `--victim` (`plugins/victims/<name>/`)          |
| **victim model**     | the underlying LLM the victim agent runs on — the target being attacked     | runtime — `--model` (mandatory, e.g. `deepseek-v4-pro`)  |
| **scenario**         | attack scenario = task suite + attack family + judge                        | plugin — `--scenario` (`plugins/scenarios/<name>/`)      |

Both the **research model** and the **victim model** are runtime
backbones, not plugins. `--model` selects the **victim model only** (the
target being attacked); `--researcher-model` / `RESEARCHER_MODEL` selects
the **research model** (the orchestrator's own backbone, defaults to the
host claude/codex login). How each backbone reaches its provider depends
on its type — **Claude Code connects directly** to a provider's
Anthropic-compatible endpoint (e.g. `https://api.deepseek.com/anthropic`),
**Codex goes through Moon Bridge** (a local proxy translating its
`/v1/responses` calls, since providers don't serve the Responses API
directly) — and the two backbones are fully isolated. Neither is the
judge model (`JUDGE_MODEL`) nor the Stage-2 Claude Code instantiator. The same victim agent running a
different victim model is a different experiment.

## Plugin axes: scenario, victim agent, researcher agent

Plugins are loaded by `src/autoresearch_redteam/registry.py` from
`autoresearcher/plugins/<axis>/<name>/` at runtime.

| Axis                 | Directory                     | Manifest        | What it owns                                                                                                          |
| -------------------- | ----------------------------- | --------------- | --------------------------------------------------------------------------------------------------------------------- |
| **Scenario**         | `plugins/scenarios/<name>/`   | `scenario.yaml` | contract.yaml, dataset, Stage-1/held-out split, judge, **attack family** (schema + sub-agent blurb + how attacks feed in) |
| **Victim agent**     | `plugins/victims/<name>/`     | `victim.yaml`   | victim runtime (Docker spawn / process wrap), trajectory decoding                                                     |
| **Researcher agent** | `plugins/researchers/<name>/` | —               | sub-agent roster (the attack-discovery method) — see below                                                            |

The registry validates the victim-agent/scenario pairing — the
scenario's `native_attack_family` must be in the victim agent's
`supports_attack_families`.

## Researcher agent plugin

The researcher agent plugin defines the research method — which sub-agents
the orchestrator dispatches each iteration. It lives at
`plugins/researchers/<name>/` and ships an `agents/*` sub-agent roster
that `launch_run.sh` copies into the worktree at run time. The roster
format follows the orchestrator the researcher runs on: the `default`
(Claude Code) researcher ships `agents/*.md` files copied into
`.claude/agents/`; the `codex` researcher ships `agents/*.toml` codex
custom agents copied into `.codex/agents/`. Same 4-agent method either
way — only the orchestration substrate differs.

## Shipped plugins

```
plugins/victims/
  claude_code/      Claude Code SDK in Docker
  codex/            OpenAI codex CLI in Docker (adapter.py + docker/
                    in-container runner; shares runner_core.py with
                    claude_code)

plugins/scenarios/
  agenthazard/      shipped example (multi-turn attack family)
  agentdyn/         shipped example (indirect prompt injection)
  dtagent/          DecodingTrust-Agent import (attack-only,
                    4 domains: crm/medical/workflow/os-filesystem)
                    # all three detailed in docs/BUILTIN_SCENARIOS.md;
                    # /scenario-build + /scenario-import produce new
                    # scenarios in the same on-disk layout

plugins/researchers/
  default/          Claude Code roster (agents/*.md → .claude/agents/):
                    6 agents: hypothesizer / attack-designer / reflector / critic +
                    scenario-architect (for /scenario-build) +
                    scenario-importer (for /scenario-import)
  codex/            codex sibling of default (agents/*.toml → .codex/agents/):
                    same 4-agent method, codex native subagent spawn
```

The shipped agent victims (`claude_code`, `codex`) cover the three
shipped scenarios (`agenthazard`, `agentdyn`, `dtagent`). Source of
truth for the launch matrix is `run_attack --list`.

**Planned:** non-agent victims live under `plugins/victims/raw_llm` and
`plugins/victims/raw_vlm`. They cover text-only chat-completions and
VLM targets for chat-level and multimodal jailbreak scenarios; they are
not agent harnesses, so they sit outside the agent-scenario flows
described here.

`dtagent` is an import of **DecodingTrust-Agent**
([arXiv:2605.04808](https://arxiv.org/abs/2605.04808)) — **attack-only**
(direct + indirect ASR, no benign split) across **4 domains** (crm /
medical / workflow / os-filesystem). It judges per instance: every
instance carries its own vendored judge (`judges/<domain>/<id>/judge.py`,
486 in total), dispatched by `scenario.py::judge_trajectory` rather than
a scenario-level LLM judge. Victims act **only** through live
docker-compose backends bridged in-process as MCP tools (see the
`docker_compose_backend` substrate above).

## Contract is open; runner is the part you teach

The contract layer accepts arbitrary slugs and arbitrary new
top-level runtime fields. Specifically:

- `attack_wiring.kind`, `environment_hydration.kind`,
  `interceptor_action.kind`, `trajectory_capture.include`,
  `payload_schema.type` are all open `str` — pick any slug.
- `RuntimeSpec` has `extra="allow"`, so a scenario can add new
  top-level dimensions to `contract.yaml::runtime` without a schema
  edit.
- `payload_schema.json_schema: {...}` is the inline-JSON-Schema
  escape — when present, `ContractDrivenScenario.attack_schema`
  returns it verbatim.

`runtime.tool_env.type` declares **what backs the victim's tools** — the
three shipped scenarios cover the three substrates:

- `agent_builtin` — the victim uses the agent's own shell tools; no
  scenario MCP / backend (agenthazard).
- `in_process_pkg` — in-process SDK MCP tools over an in-memory package
  environment, e.g. AgentDojo's pydantic env (agentdyn).
- `docker_compose_backend` — live `docker-compose` backends reset +
  seeded per instance, bridged in-process as MCP tools (dtagent). Those
  backend servers come in two shapes: **thin-proxy** backends (the server
  forwards to a live compose container) and **local-compute** backends
  (the server runs the backend logic in-process — e.g. `faiss`,
  `psycopg` — with no separate container).

The part that needs teaching is the in-container runner
(`plugins/victims/claude_code/docker/in_container_runner.py`). All
contract-runtime resolution (the dotted-path walks for `attack.*` /
`instance.*` sources) and all SDK driving (user turns, PostToolUse
interceptor splices, trajectory capture) live in this one file:

- `_resolve_wiring`, `_resolve_env_hydration`, `_resolve_interceptors` —
  build the per-attack runtime fields from the contract spec + raw
  attack/instance dicts.
- `_user_turns_for_wiring` — translate the resolved wiring to user
  turns the Claude Agent SDK receives.
- `_apply_interceptor` — the PostToolUse hook that rewrites tool
  responses.
- `_filter_trajectory` — pick out the trajectory keys the contract
  declared in `trajectory_capture.include`.

The `/scenario-extend` skill adds a new branch for each custom slug
to the matching function above, then rebuilds the base image
(`./scripts/build_base_image.sh`) so the new code lands in the
running container. Invoked automatically by `/scenario-build` and
`/scenario-import` when the architect / importer captured anything
outside the built-in slug set.

Scenario-local files (`plugins/scenarios/<name>/judge.py`,
`tools_mcp.py`, `contract.yaml`) are bind-mounted into the
container from the host's `plugins/` tree at run time — no rebuild
needed when you edit those.

## How dispatch works at runtime

1. `scripts/launch_run.sh --victim F --scenario S --researcher R
   --model M <run_code> <goal>` writes `RUN_HINT.md` into the worktree
   and copies the researcher's roster in: `plugins/researchers/<R>/agents/*.md`
   into `.claude/agents/` for the `default` researcher, or `agents/*.toml`
   into `.codex/agents/` for the `codex` researcher.
2. Inside the spawned orchestrator session,
   `/loop /autoresearch-redteam-discovery <run_code> <goal>` reads
   RUN_HINT.md, calls `registry.scenario(S)` to fetch the categories,
   attack schema, sub-agent blurb, and instance loader, then dispatches
   the researcher's sub-agents per iteration. How that dispatch happens
   depends on the researcher orchestrator: the `default` researcher
   dispatches via the **Task tool** (sub-agents from `.claude/agents/`,
   ordering + file ownership enforced by `CLAUDE.md`); the `codex`
   researcher dispatches via codex's **native subagent spawn**
   (agents from `.codex/agents/`, ordering + file ownership enforced by
   `AGENTS.md` — separate sequential spawn calls, never a batched
   fan-out).
3. `uv run -m autoresearch_redteam.run_attack --victim F
   --scenario B --model M` (Step 4) resolves the victim agent +
   scenario again from the registry, builds the victim's input.json via
   `_build_input_spec(contract, attack, instance, model, ...)` (forwards
   the contract's `runtime` block + raw attack + raw instance to the
   victim adapter), drives the victim, calls
   `scenario.judge_trajectory(...)`, returns the universal `EvalResult`.

The registry's `validate_cell(victim, scenario)` (a code-level
function name) is also called by `run_attack` so an attack against an
inadmissible victim-agent/scenario pairing fails fast.

## See also

- [BYO_SCENARIO.md](BYO_SCENARIO.md) — add a new scenario (build /
  import / hand-author), e.g. InjecAgent or a private red-team corpus
- [BUILTIN_SCENARIOS.md](BUILTIN_SCENARIOS.md) — the three shipped example
  scenarios (AgentHazard + AgentDyn + DTAgent)
- [ARCHITECTURE.md](ARCHITECTURE.md) — pipeline overview
