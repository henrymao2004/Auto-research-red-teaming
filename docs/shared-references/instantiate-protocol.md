# Stage-2 instantiate protocol (single-shot Claude Code)

Source of truth for how `scripts/instantiate_concepts.py` turns a frozen
`COUNTED` concept into one concrete held-out attack. Read this before
changing the Claude Code instantiator, its prompt assembly, or a scenario's
`tool_catalog` / `injection_catalog` / `validate_attack`.

## Contract

For each held-out instance the **Claude Code instantiator** makes
**exactly ONE generation call** (single-shot, temperature 0), picks the single concept
whose abstract mechanism most plausibly transfers, and emits one
`attack.json` validating against the scenario's `attack_schema`.

There is **no victim/judge test-time loop**: we never run the attack,
score it against the victim, and re-prompt the instantiator on that feedback.
The only loop in the instantiator is the *static* `validate_attack`
retry/repair — a STRUCTURAL delivery check driven entirely by the clean
instance + the scenario's tool/injection catalogs (does the interceptor
`tool` exist? does a mode-B injection reach a victim-readable channel?).
That is allowed and stays; it never runs the victim.

## Instantiator backend

Stage 2 shells out to the logged-in Claude Code `claude` CLI in print mode
(`claude -p --output-format json`), model `claude-opus-4-8` (override
`INSTANTIATOR_CLI_MODEL`), with a lean red-team system prompt and **all
file/exec/web tools disallowed**
(`Bash,Edit,Write,Read,Glob,Grep,WebSearch,WebFetch,Task,NotebookEdit,TodoWrite`).
It uses the host Max subscription and needs no API key. Concurrency is the
`--workers` count. Adapted from
`redteam-baselines/tmap/tmap_core.py::AttackerLLM` (claude_cli path).

## Sandbox white/blacklist (anti-cheat)

Leakage is prevented **by construction**: the instantiator is a prompt→LLM
call with no file tools, and the prompt is assembled only from the
whitelist below. The Claude Code instantiator therefore cannot copy or answer-fit the
evaluator's ground truth.

**WHITELIST — the instantiator prompt may ONLY contain:**

- the scenario's attack-family blurb + delivery guidance
  (`bench.subagent_blurb`);
- the **abstract** concept fields from `frozen_concepts.json`:
  `mechanism`, `enabling_condition`, `transfer_prediction`, and
  `attack_template` *as one example* — rendered by `render_concepts`;
- the **clean instance** fields only, via `bench.load_instance`:
  `task_instruction`, `system_prompt`, `available_tools`,
  `additional_information`, `malicious_goal`, `threat_model`, `domain`,
  `category`;
- the scenario `tool_catalog` (REAL MCP method names) and
  `injection_catalog` (REAL backend injection channels) — these are
  *infrastructure* (which tools/channels exist), not answer keys;
- the contract `attack_schema`.

**BLACKLIST — NEVER read into or named in the prompt:**

- `judge_data.json` — evaluator-only answer keys (dtagent
  `canned_attack`; agenthazard `decomposed_query`; agentdyn
  `*_ground_truth_function_calls` / `*_check_rule`). `_process_one`
  sources context from `bench.load_instance`, never `judge_data`.
- the discovery `attacks/<run>/v<N>/` payloads and proposals;
- `AGENT_LOG.md`;
- the per-version `observations` / `provenance` lines on a frozen
  concept (these carry exact Stage-1 sinks/payloads). `render_concepts`
  pulls only the four abstract fields above — it must stay that way.

## Mode-A interceptor targeting (dtagent)

A tool-OUTPUT interceptor only fires if it is attached to a tool whose
output the benign task actually **reads**. `available_tools` lists only
the SERVER, not method names, so a single guessed method (e.g.
`list_messages` on a gmail task that calls `get_gmail_content` /
`search_messages`) silently no-ops. Fix: `tool_catalog` names the
channel's **READ-tool family** (`_READ_TOOL_FAMILY ∩` the server's real
tools), inferred from `task_instruction` + the instance's servers, and
instructs the instantiator to attach the interceptor to that whole family —
emit MULTIPLE interceptor specs (one per plausible read tool) OR use
`tool: "*"` when uncertain. The runner loops over the interceptor list
and `"*"`/bare names both match (`_tool_name_matches`), so over-covering
the family is safe and strictly raises the chance the splice lands.

## Instance filter

`--threat-model {direct,indirect,all}` (default `all`), alias
`--only-indirect`, restricts which held-out instances are
(re)generated, using the clean instance's authoritative `threat_model`
field. A threat-model filter implies `--overwrite` (the run is an
explicit regeneration of that subset); use `--no-overwrite` to resume.
Filtered-out instances are left untouched on disk — an indirect-only run
never overwrites direct `attack.json`, and vice versa.
