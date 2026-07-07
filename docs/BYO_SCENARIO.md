# Bring your own scenario

A **scenario** owns the dataset, the Stage-1/held-out split, the judge,
and the **attack family** native to it (multi-turn ratchet, indirect
prompt injection, tool poisoning, memory poisoning, …). The attack
family is intrinsic — different scenarios bring different families. The
two that ship are documented in
[`BUILTIN_SCENARIOS.md`](BUILTIN_SCENARIOS.md); they're examples, not a
template — the steps here work for any scenario.

## Two ways to make one

**Guided interview (recommended) — no Python to write:**

- `/scenario-build "<free-text idea>"` — synthesize a scenario from a
  one-line idea (the generator LLM creates the instances).
- `/scenario-import "<name> from <upstream>"` — pull in an existing
  benchmark (pip / git / HuggingFace / local files).

Both run the **same plain-language interview** and produce the **same
on-disk layout** this document describes. The interview walks the
contract one dimension at a time; its rounds map directly onto the
hand-author sections below:

| Interview round | What it asks | Hand-author section / contract field |
|---|---|---|
| Threat model & attack surface | the attack family, where the attacker's content lives, the one field the attacker writes each round, its shape | §6 · `attack_family`, `attacker_surface`, `payload_schema` |
| Victim environment | which agent is attacked, its tools, any pre-run setup | `victim_environment` |
| Success criterion & judge | when the attack counts as a win, what the referee reads, which numbers get reported | §3 · `success_criterion`, `judge`, `evaluator_only_fields` |
| Visibility / instance schema / content | researcher-visible vs judge-only answer-key, per-field types, difficulty & realism | §4 · `researcher_visible_fields` ↔ `evaluator_only_fields`, `instance_schema`, `synth_requirements` |
| Runtime wiring | how the attack reaches the agent **and where its content comes from** — the two-channel split (a benign task from `instance.*` vs the attacker channel from `attack.*`), any pre-loaded world, any tool-response edits | §6 · `runtime` (`attack_wiring{kind,source}`, `environment_hydration{kind,source}`, interceptor `match`/`action.source`, `trajectory_capture`) |

It validates each round (`load_contract` + `validate_runtime_sources`,
which checks every `*.source` dotted path resolves) and materializes the
plugin. The round-by-round scripts live in
`plugins/researchers/default/agents/{scenario-architect,scenario-importer}.md`.
Anything outside the built-in slugs is wired by `/scenario-extend`
automatically at materialize time.

**Hand-author (reference).** The sections below are the under-the-hood
layout — for writing `contract.yaml` directly or debugging a generated
scenario. They describe exactly what the interview produces.

## 1. Scaffold the plugin

```bash
./scripts/add_scenario.sh <name>
# Creates a minimal plugins/scenarios/<name>/ stub. Use this only if
# you want a blank slate. /scenario-build and /scenario-import both
# produce a richer materialised layout directly.
```

## 2. Implement `scenario.py`

A scenario in v2 is **contract-driven** — `contract.yaml` is the
single declarative source of truth. The Python class just subclasses
`ContractDrivenScenario`, declares its registry name, points at the
contract, and overrides `judge_trajectory` to delegate to the
sibling `judge.py`. Everything else (`attack_schema`,
`subagent_blurb`, `categories`, dataset paths, the default
`build_input_spec`) is derived from the contract by the base class.

Reference: `plugins/scenarios/agenthazard/scenario.py` (~50 lines):

```python
from pathlib import Path
from typing import Any
from autoresearch_redteam.contract_driven_scenario import ContractDrivenScenario
from .judge import judge_trajectory as _judge_trajectory

HERE = Path(__file__).resolve().parent


class YourScenario(ContractDrivenScenario):
    name = "<name>"                          # registry slug
    contract_path = HERE / "contract.yaml"   # source of truth
    _plugin_root = HERE                      # resolves clean/, heldout.json, judge_data.json

    def judge_trajectory(
        self,
        instance: dict[str, Any],
        trajectory_payload: dict[str, Any],
        *,
        judge_model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        return _judge_trajectory(
            instance=instance,
            trajectory=trajectory_payload,        # pass the runner's canonical shape
            judge_model=judge_model,
            api_key=api_key,
            base_url=base_url,
        )
```

The real work is in **`contract.yaml`** — see
`plugins/scenarios/agenthazard/contract.yaml` and
`plugins/scenarios/agentdyn/contract.yaml` for shipped examples, and
`src/autoresearch_redteam/contract.py::ScenarioContract` for the
Pydantic schema. The contract declares: `scenario_name`,
`attack_family`, `attacker_surface` (incl. `controllable_fields`),
`payload_schema` (with optional inline `json_schema` + `blurb`),
`researcher_visible_fields` vs `evaluator_only_fields` partition,
`success_criterion`, `trajectory_observation.collect`, `judge`
(type + rule + optional prompt_template), and the `runtime` block
(`docker_image`, `attack_wiring{kind, source}`,
`environment_hydration{kind, source}`, `mcp_tools_module`,
`tool_response_interceptors` / `tool_response_interceptors_from`,
`trajectory_capture`). The `source` fields are dotted paths
(`attack.<field>` or `instance.<field>`) telling the runner where each
piece of content comes from — `validate_runtime_sources` checks they
resolve, so they can't be left implicit.

If you do not want to learn the schema by reading, run
`/scenario-build` and let the architect walk you through it.

## 3. Implement `judge.py`

Stand-alone module exposing `judge_trajectory(instance, trajectory,
**kw) -> dict`. Use the OpenAI-compatible client from
`plugins/scenarios/agenthazard/judge.py`; configure via
`JUDGE_BASE_URL` / `JUDGE_API_KEY` / `JUDGE_MODEL` env vars.

For rule-based judges that inspect tool calls, the victim runner's
observed trajectory is canonical: `trajectory["tool_calls"]` entries
use `{"name": "<tool>", "arguments": {...}, "id": "..."}`. Upstream
ground truth may use names like `function` / `args`, but judges should
normalize observed calls to `name` / `arguments` before matching. Do
not write new judges that depend on observed `function` / `args`
fields. Use
`autoresearch_redteam.tool_calls.normalize_observed_tool_call` for
this normalization.

## 4. Convert + split scripts

`convert.py` turns your upstream dataset into per-instance JSONs under
`plugins/scenarios/<name>/clean/<category>/<id>.json`. Minimum fields
per instance: `id`, `category`, `query` (the harmful goal). Anything
the judge needs that the agent must NOT see goes into a sidecar
`judge_data.json` (Read-denied to the agent).

`regen_split.py` writes `train.json` + `heldout.json` (no combined
`split.json` — keeping held-out IDs in a separately-permissioned file
prevents Stage 1 leakage).

## 5. `scenario.yaml`

```yaml
name: <name>
description: <one line>
native_attack_family: <name>
scenario: <name>.scenario:YourScenario
categories: [...]
status: ready
```

## 6. Bring the attack family along

If your scenario introduces a **new attack family** (not multi-turn
or IPI), three things change:

- the schema in `attack_schema`
- the `subagent_blurb` (Hypothesizer / Attack-designer prompts)
- the `runtime` block in contract.yaml — both *how* the attack reaches
  the agent (`attack_wiring.kind`) and *where its content comes from*
  (`attack_wiring.source`), plus any pre-loaded world
  (`environment_hydration`) and tool-response edits (`interceptors`).
  For a two-channel scenario — a benign task drives the agent while the
  attack rides a separate channel — `attack_wiring.source` points at the
  instance's task field (`instance.<field>`) and the attack channel is
  wired separately to `attack.<field>`; the runtime round of the
  interview pins down exactly this split, and `validate_runtime_sources`
  rejects a contract whose sources don't resolve.

What does **not** change: sub-agent definitions, VCG schema, Stage 2
scripts, monitor signals. The sub-agents read the family blurb from
the dispatch prompt; they're family-neutral by construction. Stage 2
`instantiate_concepts.py` is contract-driven — it reads
`bench.subagent_blurb` (your family description),
`bench.attack_schema` (your payload JSON Schema), and
`contract.attacker_surface.controllable_fields[0]` (your payload
field name), then asks the Stage-2 Claude Code instantiator to produce attacks matching
your schema and validates with jsonschema. No edits to Stage 2 are
needed for any new scenario family.

The contract layer accepts any slug for `attack_wiring.kind`,
`environment_hydration.kind`, `interceptor_action.kind`,
`trajectory_capture.include`, `payload_schema.type`, and any new
top-level `runtime.*` field (`RuntimeSpec` is `extra="allow"`).
For the **runner** to actually do something with a non-built-in
slug, run `/scenario-extend` — it adds the matching branch to the
in-container runner (`plugins/victims/claude_code/docker/in_container_runner.py`,
in one of `_resolve_wiring` / `_resolve_env_hydration` /
`_apply_interceptor` / `_filter_trajectory` based on the
dimension) and rebuilds the docker base image so the new code
ships. When you go through `/scenario-build` or `/scenario-import`,
this happens automatically at materialize time.

The victim must also declare it supports your new family — add it
to `victim.yaml`'s `supports_attack_families`. The registry's
`validate_cell` will reject the (victim, scenario) pair otherwise.

## 7. Smoke test

```bash
# Verify the scenario loads:
uv run -m autoresearch_redteam.run_attack --list

# Verify split + judge work:
cd plugins/scenarios/<name>
uv run python regen_split.py
uv run python -c "
import sys; sys.path.insert(0, '../../../src')
from autoresearch_redteam import registry
b = registry.scenario('<name>')
print('categories:', b.categories)
print('classify 1:', b.classify_instance(1))
"
```

## Checklist

- [ ] `plugins/scenarios/<name>/scenario.yaml` with `status: ready`
- [ ] `plugins/scenarios/<name>/scenario.py` implementing all required methods
- [ ] `plugins/scenarios/<name>/judge.py` with `judge_trajectory()`
- [ ] `plugins/scenarios/<name>/regen_split.py` writes
  `train.json` + `heldout.json`
- [ ] `plugins/scenarios/<name>/convert.py` turns upstream → `clean/<cat>/<id>.json`
- [ ] Listed by `run_attack --list`
- [ ] Smoke run on `claude_code` (or any victim that supports your
  family) produces a `result.json`
- [ ] Updated the project settings.local.json deny globs already cover
  `plugins/scenarios/**/heldout.json` and
  `plugins/scenarios/**/judge_data.json` — no settings change needed
  per scenario
