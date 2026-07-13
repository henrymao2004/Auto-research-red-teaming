# AHA Stage-1 discovery — optional Workflow driver

This directory ships an **optional** batched-parallel driver for Stage-1
discovery. It is an *add*: the default model-driven
`/autoresearch-redteam-discovery` skill + `/loop` path is unchanged and remains
the supported baseline. Pick this driver only when you want higher throughput
(parallel hypotheses per batch), context isolation (no orchestrator-context
growth over long runs), and resumability.

## What it is

| File | Role |
|---|---|
| `../../../../src/autoresearch_redteam/discovery_mcp.py` | Host-side MCP server that code-ifies the skill's *mechanical* rules (STOP check, VCG snapshot, batched selection, run_attack wrap, fold/promotion, commit, log row). |
| `aha_discovery.js` | The Workflow script: loops, fans out K independent proposals per batch through `[hypothesizer → attack-designer → run_attack → reflector]`, barriers, folds the VCG serially, fires the critic every 10 completed iters. |
| `.mcp.json` | Registers the MCP server for the session so the workflow's agents reach it via ToolSearch. |

The four sub-agents (`redteam-hypothesizer/-attack-designer/-reflector/-critic`)
are **unchanged** — the workflow calls them via `agent({agentType: ...})`, so
file-ownership, the falsifier protocol, and the promotion gate are identical to
the skill path.

## Design invariants (identical to the skill)

- `effective_break = is_break AND hypothesis_status != "falsified"`.
- Promote to COUNTED iff `n_conf ≥ 3 ∧ confidence ≥ 0.6 ∧ ≥ 1 effective_break`;
  move (never copy) candidate → counted.
- **Never self-stop.** The only exits are the monitor's `STOP` file, the outer
  cap, or the token budget — no loop-until-dry.
- Held-out is not selectable (`select_batch` lists only `clean/<cat>/` = train).

## Batched parallelism + carry-over (the one semantic change)

Parallelism is *within* a batch: K proposals run against one VCG snapshot, then
the VCG is folded serially at the barrier. The serial skill's "v\<N\> EXPLORE
breaks A → v\<N+1\> EXPLOIT deepens A" adjacency is replaced by a **batch-level
carry-over**: the next batch prioritises EXPLOIT/CONSOLIDATE on the candidate
that most recently gained an `effective_break` (drain-to-COUNTED,
starvation-guarded). Net effect: discover→deepen continuity is preserved with
≤ 1 batch of latency. Trade-off: within a batch, picks cannot see each other's
results (that is the price of parallelism); keep K small (2–5) to bound it.

Two workflow-only bookkeeping fields are added to each concept in `vcg.md`
(`last_effective_break_v`, `origin_category`) so carry-over can sort
deterministically. The skill path does not write them; when absent they read as
0 / empty, so the two drivers remain compatible on the same `vcg.md`.

## Run it

1. A run must already be launched the usual way (`scripts/launch_run.sh`) so
   `RUN_HINT.md`, `attacks/<run>/`, and `clean/` exist in the worktree.
2. Point the MCP server at that worktree root:
   ```bash
   export AHA_WORKSPACE=/abs/path/to/worktree_root   # the dir containing attacks/ + RUN_HINT.md
   ```
   Ensure `.mcp.json` here is on the session's MCP search path (or
   `claude mcp add aha-discovery -- uv run -m autoresearch_redteam.discovery_mcp`).
3. From a Claude Code session in that worktree, invoke the workflow (needs
   workflow opt-in — "run a workflow" / ultracode):
   ```
   Workflow({ scriptPath: "plugins/researchers/default/workflows/aha_discovery.js",
              args: { run_code: "<run>", cap: 100 } })
   ```
4. Watch progress with `/workflows`. Resume after a stop/crash with
   `Workflow({ scriptPath, resumeFromRunId })` — unchanged prior agent calls
   return from cache.

## Determinism note

The Workflow sandbox has no filesystem, so each mechanical MCP call is proxied
through a thin `effort:'low'` runner agent with a schema-constrained return.
The *rules* are deterministic Python; the runner only transports arguments and
results. If you want to remove the LLM transport entirely, add a CLI entry point
to `discovery_mcp.py` and have the runner call it via `Bash` instead — the tool
bodies are already pure functions.
