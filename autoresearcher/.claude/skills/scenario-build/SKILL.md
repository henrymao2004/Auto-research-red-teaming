---
name: scenario-build
description: Interactively bootstrap a new scenario plugin from a free-text idea. Dispatches scenario-architect for contract authoring, then synthesize_instances.py for instance generation, then materializes plugins/scenarios/<name>/. End state — plugin loadable by registry, launchable via launch_run.sh.
argument-hint: "<free-text scenario description, including a slug name>"
---

# Scenario Build — Interactive bootstrap of a new scenario plugin

This skill turns a free-text scenario idea into a materialized
`plugins/scenarios/<name>/` directory that the registry can discover
and `scripts/launch_run.sh` can launch. The heavy lifting is split
between:

1. The `scenario-architect` sub-agent — interviews the human and
   produces a validated `contract.yaml` draft in `/tmp/`.
2. `scripts/synthesize_instances.py` — turns the contract into
   `clean/`, `clean_heldout/`, `train.json`, `heldout.json`,
   `judge_data.json`.
3. The `templates/scenario-plugin-template/` skeleton — `scenario.py`
   + `scenario.yaml` manifest.

Sub-agent dispatch point: Step 2.

---

## Step 1 — Parse args

`$ARGUMENTS` is the free-text scenario description. Extract a slug-ish
`scenario_name` (snake_case) from it; if you cannot infer one, ask via
`AskUserQuestion`. Validate:

```bash
[ -d "autoresearcher/plugins/scenarios/<scenario_name>" ]
```

If that directory already exists, dispatch `AskUserQuestion` asking
the user to confirm overwrite (destructive) or pick a new name. Do
not silently overwrite.

Record the chosen name as `SCENARIO_NAME` and the CamelCase form as
`SCENARIO_NAME_CAMEL` (e.g. `prompt_injection_doc` → `PromptInjectionDoc`).

## Step 2 — Run the architect interview inline

**Do NOT dispatch via Task tool.** `AskUserQuestion` does not
render interactively when called from a sub-agent in Claude Code
— the sub-agent would emit the question as plain text and the
user can't pick options. Instead, **you (the skill orchestrator
running in the main session) drive the interview directly** using
the architect playbook.

1. Read the playbook at
   `autoresearcher/plugins/researchers/<active_researcher>/agents/scenario-architect.md`
   (default researcher: `default`). It documents the interview
   structure (4-6 rounds, what each round must capture, style
   rules, validation behavior).
2. Read these existing contracts as few-shot examples before
   asking the user any questions:
   - `autoresearcher/plugins/scenarios/agenthazard/contract.yaml`
   - (any other `contract.yaml` under
     `autoresearcher/plugins/scenarios/`)
   - `autoresearcher/src/autoresearch_redteam/contract.py` schema.
3. Follow the playbook's rounds **yourself**, calling
   `AskUserQuestion` from this session for each question. Every
   `AskUserQuestion` MUST include the one-sentence explanation
   suffix the playbook mandates ("— this becomes
   `contract.<field>` / drives runner behavior X / ..."), so the
   user knows what each answer configures.
4. After each round, write the current best draft to
   `/tmp/<scenario_name>.contract.yaml.draft` and validate:

   ```bash
   ~/.local/bin/uv run python -c "from autoresearch_redteam.contract import load_contract; load_contract('/tmp/<scenario_name>.contract.yaml.draft')"
   ```

   Pydantic errors → target the failing fields in the next round.
5. When the user picks any **custom slug** for any runtime
   dimension (or a custom `payload_schema.type`), append the
   corresponding entry to `/tmp/<scenario_name>.extend.json` as
   the playbook specifies (`surface: runner.* | contract.* |
   plugin.*`).
6. The final round (round 6 in the playbook) is the review-+-
   approve gate. Loop on patch requests until the user approves.
7. **Victim target** (ask once, plain language): *"When you actually
   run this scenario, which agent is under attack — Claude Code, Codex,
   or both? (If unsure, Claude Code — it's the default; you can add the
   other later.)"* Record the answer as `victim_scope`
   (`claude_code` | `codex` | `both`) at the top of
   `/tmp/<scenario_name>.extend.json`. This is **not** a contract field
   — it tells `/scenario-extend` (Step 6.5) whether to apply its **Codex
   peer parity** deltas (expose `build_tools`, add deps to `ar_codex`,
   per-peer drive edits, codex hard limits). If `claude_code` only,
   extend skips all codex work.
8. **Tool environment + judge mode** (ask once, plain language):
   (a) *"What backs the agent's tools?"* → in-process Python package
   (agentdojo-style) | external docker-compose backend services (DTap-style) |
   agent-builtin tools | other; (b) *"One judge for the whole scenario, or does
   each task carry its own judge?"* → scenario | per_instance. Record
   `tool_env_type` and `judge_mode` at the top of
   `/tmp/<scenario_name>.extend.json`. These route `/scenario-extend`: a
   docker-compose env → recipe **3j** (`plugin.tool_env`); per-task judges →
   recipe **3h** (`judge_mode: per_instance` dispatcher + loadability guard).

Match the human's prompt language throughout. Don't over-explain;
let the playbook's per-question explanations do the work.

## Step 3 — Validate final contract

Two checks: (a) Pydantic shape via `load_contract`, and (b) a
**runtime-source lint** that catches the one class of bug the interview
is weakest on — a wiring/hydration/interceptor `source` that doesn't
resolve to a real field. Without (b), a contract can validate, register,
and then fail silently at the FIRST attack run (the runner resolves an
empty payload). This is the backstop for the AgentDojo-style two-channel
case (benign task from `instance.*`, attack from `attack.*`).

```bash
~/.local/bin/uv run python -c "
from autoresearch_redteam.contract import load_contract, validate_runtime_sources
c = load_contract('/tmp/<scenario_name>.contract.yaml.draft')
# auto-stamp the required version field if the architect left it unset
issues = validate_runtime_sources(c)
errs = [i for i in issues if i.startswith('ERROR')]
for i in issues: print(i)
import sys; sys.exit(1 if errs else 0)
"
```

- Exit 0 (and no `ERROR:` lines) → proceed to Step 4. Surface any
  `WARN:` lines to the user ("the source <x> doesn't match a declared
  field — confirm it's intended").
- Non-zero (Pydantic failure OR any `ERROR:` source-lint line) →
  re-dispatch `scenario-architect` with the error/lint message appended
  and an instruction `"validation failed: <stderr/lint>. For a source
  error, ask the user which field the attack/instance content actually
  comes from (e.g. 'attack.<payload_field>' if the attacker writes it, or
  'instance.<field>' if it's carried on each test case — AgentDojo's
  driver task is 'instance.user_task.prompt'). Fix and resubmit to
  /tmp/<scenario_name>.contract.yaml.draft."`. **Max 2 retries.** If
  still failing after 2 retries, abort and ask the human to inspect.
- If the draft is missing the required `version` field, stamp
  `version: "1.0"` into it before re-validating (no need to re-interview
  for this — it's a constant).

## Step 3.5 — Generator endpoint check

`synthesize_instances.py` needs the **generator** endpoint (`ROUTER_BASE_URL`
+ `ROUTER_API_KEY` + `GENERATOR_MODEL`). Endpoint config lives in `.env` —
the user normally sets it once via **`/setup`**.

- If `ROUTER_BASE_URL` + `ROUTER_API_KEY` are already set, continue.
- If not, tell the user to run `/setup` (the single place that
  configures + validates endpoints). For a temporary session, you may ask
  via `AskUserQuestion` (OpenRouter / OpenAI / Anthropic; UI
  Type-something covers custom/internal proxies) and export
  `ROUTER_BASE_URL` + `ROUTER_API_KEY` for this session — but `/setup`
  is the recommended path so the user isn't asked for keys in two
  places. If the generator key ends up unset, stop with a clear error
  rather than letting the synth 401 mid-batch.

## Step 4 — Synthesize instances

Ask via `AskUserQuestion` how many instances to synthesize. Options:
`100`, `200`, `500`, `1000`, `other` (default `200`).

```bash
# NOTE: scripts/synthesize_instances.py is a planned tool and may not
# yet exist. If it is missing, print a clear message naming the path
# and skip Steps 4-5; the human can re-run /scenario-build after the
# synthesizer is added. Do not block plugin materialization (Step 6)
# behind this — the contract is the real artefact, instances can be
# dropped in later.
~/.local/bin/uv run python scripts/synthesize_instances.py \
    --contract /tmp/<scenario_name>.contract.yaml.draft \
    --n <N> --split 0.9 \
    --out-dir /tmp/<scenario_name>_synth
```

The synthesizer is expected to write:
- `clean/<category>/<id>.json`        — train metadata (researcher-visible)
- `clean_heldout/<category>/<id>.json` — held-out metadata
- `train.json`                         — train split index
- `heldout.json`                       — held-out split index
- `judge_data.json`                    — host-only evaluator data

## Step 5 — Review 3 representative instances

```bash
# Pick three at random from /tmp/<scenario_name>_synth/clean/**
~/.local/bin/uv run python -c "
import json, random, glob
files = glob.glob('/tmp/<scenario_name>_synth/clean/**/*.json', recursive=True)
for p in random.sample(files, min(3, len(files))):
    print('---', p, '---')
    print(json.dumps(json.loads(open(p).read()), ensure_ascii=False, indent=2))
"
```

Show the output to the user, then `AskUserQuestion`:
- **approve** → continue to Step 6
- **patch contract** → re-dispatch architect with the human's
  patch description, then re-run Steps 3-5
- **regen** → re-run Step 4 with a fresh seed

## Step 6 — Materialize the plugin

Copy the template into place:

```bash
cp -R templates/scenario-plugin-template/ \
    autoresearcher/plugins/scenarios/<scenario_name>/
```

Then:

1. **Write the contract**:
   ```bash
   cp /tmp/<scenario_name>.contract.yaml.draft \
       autoresearcher/plugins/scenarios/<scenario_name>/contract.yaml
   ```

2. **Replace placeholders** in the copied `scenario.py` and
   `scenario.yaml`. The skill reads the values it needs out of the
   already-materialized `contract.yaml` (loaded via
   `from autoresearch_redteam.contract import load_contract`) so the
   manifest stays in sync with the contract:
   - `{scenario_name}` → `<scenario_name>` (snake_case)
   - `{SCENARIO_NAME_CAMEL}` → `<SCENARIO_NAME_CAMEL>`
   - `{ATTACK_FAMILY}` → `contract.attack_family` (becomes
     `scenario.yaml::native_attack_family` — required by
     `registry.validate_cell`)
   - `{SCENARIO_DESCRIPTION}` → one-line description (ask the user
     via AskUserQuestion if not derivable from the goal string)

   Drop the `.j2` extension on `contract.yaml.j2` (the template is
   documentation; the architect-written contract overwrites it).

3. **Move synthesized data** from `/tmp/<scenario_name>_synth/` into
   the plugin dir:
   ```bash
   mv /tmp/<scenario_name>_synth/{clean,clean_heldout,train.json,heldout.json,judge_data.json} \
       autoresearcher/plugins/scenarios/<scenario_name>/
   ```
   Skip silently if Step 4 was skipped.

4. **Judge wiring** — `scenario.py` (already copied from the
   template) delegates `judge_trajectory` to a sibling `judge.py`.
   The framework does NOT pick a judge implementation for you; it
   only provides the file location + interface contract. Any judge
   type the architect captured (LLM-prompt, function-call match,
   regex, env-state diff, custom Python — whatever the user
   designed in Round 3) is supported the same way:

   ```bash
   sed "s/{scenario_name}/<scenario_name>/g" \
       templates/scenario-plugin-template/judge.py.stub \
       > autoresearcher/plugins/scenarios/<scenario_name>/judge.py
   ```

   If `contract.judge.prompt_template` is set (LLM-prompt judge),
   additionally:
   - `AskUserQuestion` for the prompt text (inline OR an existing
     markdown file path).
   - Write it to `judge/<contract.judge.rule>.md` under the plugin
     dir (create `judge/` if missing).
   - Stamp `contract.yaml::judge.prompt_hash`:
     ```bash
     ~/.local/bin/uv run python -c "
     from autoresearch_redteam.contract import compute_prompt_hash
     print(compute_prompt_hash('autoresearcher/plugins/scenarios/<name>/judge/<rule>.md'))
     "
     ```
     Then `Edit` `contract.yaml` to insert the hash.

   Surface in your final output: `judge.py` is a STUB that raises
   `NotImplementedError`. The user implements
   `judge_trajectory(instance, trajectory_payload, ...) -> {harmful,
   score, reason, ...}` per the interface contract in the stub's
   docstring. Reference implementations:
   `plugins/scenarios/agenthazard/judge.py` (LLM-prompt) and
   `plugins/scenarios/agentdyn/judge.py` (function-call match).

5. **MCP tools stub** — if the contract sets
   `runtime.mcp_tools_module`, the architect wrote a stub at
   `/tmp/<scenario_name>.tools_mcp.py.stub`. Copy it into the plugin
   dir at the path implied by the module name (typically just
   `tools_mcp.py` in the plugin root):
   ```bash
   cp /tmp/<scenario_name>.tools_mcp.py.stub \
       autoresearcher/plugins/scenarios/<scenario_name>/tools_mcp.py
   ```
   Surface this in your final output: the stub's
   `build_mcp_server(instance, env_state)` raises
   `NotImplementedError`. The user must implement it (wrapping their
   domain tools as `@tool`-decorated callables backed by
   `env_state`) before the cell can run end-to-end. See
   `plugins/scenarios/agentdyn/tools_mcp.py` for a reference
   implementation.

6. **Scenario Dockerfile** — if the user picked `docker_image` with
   a custom name (e.g. `ar_<scenario>:latest`), generate a Dockerfile
   at `plugins/scenarios/<scenario_name>/Dockerfile`:
   ```dockerfile
   FROM ar_claude_code_base:latest
   # add scenario-specific deps here, e.g.:
   # RUN pip install --no-cache-dir <upstream-pkg>
   LABEL scenario=<scenario_name>
   ```
   If the user named no extra deps, the FROM line alone is enough.
   `launch_run.sh` auto-builds via
   `scripts/build_scenario_image.sh <name>` on first launch.

7. **Victim adapter compatibility check** — if the contract's
   `victim_environment.agent_type` requires capabilities no currently-
   ready victim adapter declares for the scenario's `attack_family`,
   print a warning listing the admissible victim plugin names (or
   `(none yet — write an adapter for attack_family=<X>)`).

## Step 6.5 — Wire user-described custom dimensions

```bash
EXTEND_FILE=/tmp/<scenario_name>.extend.json
[ -f "$EXTEND_FILE" ] && cat "$EXTEND_FILE"
```

**Decision rule — strict, no execution drift:**

- If `extend.json` does NOT exist → skip; the scenario uses only
  built-in kinds. Continue to Step 6.6.
- If `extend.json` DOES exist → **`/scenario-extend` MUST be
  invoked here, via the Skill tool, with the file's contents as
  args. This is mandatory, not a suggestion. Do not surface
  text like "you should run /scenario-extend separately" or
  "/scenario-extend (独立跑)" to the user — that's execution
  drift; the skill orchestrator is supposed to invoke it inline.
  Do not print a TODO list and stop. Invoke it now.**

  Specifically:

  ```
  Skill({skill: "scenario-extend", args: <contents of extend.json>})
  ```

  Block until `/scenario-extend` returns. While it runs, the
  output may include several edits (judge.py body, tools_mcp.py
  body, runner branches, docker rebuilds). Stream the summary
  to the user but do not interrupt.

  On return:
    · If it reports success → continue to Step 6.6.
    · If it reports any failure (validation, docker build, file
      I/O) → surface the error verbatim and STOP the build.
      Do NOT proceed to Step 7 with stubs in place — the
      runner will crash at first iteration.

**Sanity check before continuing:**

```bash
grep -lE "raise NotImplementedError" plugins/scenarios/<scenario_name>/{judge.py,tools_mcp.py} 2>/dev/null
```

If anything matches, `/scenario-extend` left stubs behind.
That's a bug — re-invoke `/scenario-extend` with a message
telling it which file is still a stub. Do not continue.

## Step 6.6 — Make sure at least one victim supports this attack family

The contract's `attack_family` is checked by
`registry.validate_cell` against every victim's
`supports_attack_families`. If no shipped victim declares the
family, `launch_run.sh` will refuse to start a cell.

```bash
FAMILY=$(~/.local/bin/uv run python -c "from autoresearch_redteam.contract import load_contract; print(load_contract('plugins/scenarios/<scenario_name>/contract.yaml').attack_family)")
SUPPORTS=$(grep -lE "^\s*-\s*${FAMILY}\b" plugins/victims/*/victim.yaml 2>/dev/null)
```

If `$SUPPORTS` is empty, no victim is compatible yet. Use
`AskUserQuestion` (closed-set, one option per ready victim):

> "No shipped victim plugin declares `<attack_family>` in its
> `supports_attack_families`. Pick a victim to extend — we'll
> add the family to its victim.yaml so the cell can register."

Options: one per existing victim under `plugins/victims/`
(label = victim plugin name + a short capability hint from its
manifest). After the user picks, `Edit` that victim's
`victim.yaml` to append the family slug under
`supports_attack_families`. Re-run the grep above to confirm.

If the user declines (no victim is honest about supporting this
family), record the gap in your final summary and let the user
write a new victim adapter before launching the cell.

## Step 7 — Register + verify

```bash
~/.local/bin/uv run -m autoresearch_redteam.run_attack --list
```

Verify a row appears like `<scenario_name> (ready) family=<attack_family>`.
If not (registry didn't pick the plugin up), inspect:
- `scenario.yaml` manifest format
- `scenario.py` class name matches the manifest entry
- The new directory is under `autoresearcher/plugins/scenarios/`

Then print the suggested launch command verbatim so the human can copy
it:

```
./scripts/launch_run.sh <run_code> \
    --scenario <scenario_name> \
    --victim <chosen_victim> \
    --model <user-supplied> \
    '<one-line goal>'
```

## Step 8 — Offer to commit, then done

```
Scenario <scenario_name> materialized at autoresearcher/plugins/scenarios/<scenario_name>/.
Ready for /autoresearch-redteam-discovery.
```

Then via `AskUserQuestion`, offer to commit (closed-set):

> "Commit the new scenario now? `git status` shows: <list of
> changed + untracked files>. A commit message draft:
> `Add scenario <scenario_name> via /scenario-build`"
>
>  - "Yes, commit with that message"
>  - "Yes, commit with a different message" → Type-something for the message
>  - "No, I'll commit manually"

If the user picks one of the Yes paths:
```bash
git add autoresearcher/plugins/scenarios/<scenario_name>/
# + any victim.yaml edited in Step 6.6
# + any edits from /scenario-extend: runner_core.py (shared), contract.py,
#   contract_driven_scenario.py, and the victim drive layers it touched —
#   claude_code/docker/in_container_runner.py and/or
#   codex/docker/{runner.py,scenario_mcp_stdio.py}
git commit -m "<message>"
```

DO NOT push regardless — the user keeps that step manual.

---

## File ownership

| File the skill writes | Who else writes it |
|---|---|
| `/tmp/<name>.contract.yaml.draft` | scenario-architect (intermediate drafts; skill copies final) |
| `autoresearcher/plugins/scenarios/<name>/contract.yaml` | skill, copy from /tmp |
| `autoresearcher/plugins/scenarios/<name>/scenario.py` | skill, from template |
| `autoresearcher/plugins/scenarios/<name>/scenario.yaml` | skill, from template |
| `autoresearcher/plugins/scenarios/<name>/judge/*.md` | skill (Step 6.4), text from human |
| `autoresearcher/plugins/scenarios/<name>/{clean,clean_heldout,*.json}` | `synthesize_instances.py`; skill moves into place |

## Failure modes the skill handles

- **architect returns invalid contract** → Step 3 re-dispatches with
  the validation error; max 2 retries.
- **synthesize_instances.py missing** → skip Steps 4-5, materialize
  contract + plugin skeleton only, tell the human to re-run later.
- **scenario_name already taken** → Step 1 prompts for confirm/rename.
- **registry doesn't show the new scenario** → Step 7 tells the
  human which files to inspect.
