# CLAUDE.md — repo-root navigation

Root of the **Auto-research-red-teaming-in-sleep (AHA)** monorepo. Claude Code
auto-loads this file when a session starts here; the substantive guides live one
level down, so this file is just a map.

## Where things are

- **`autoresearcher/`** — the main project (the autoresearch red-team system).
  Do substantive work from here: it holds `scripts/`, `plugins/`, `src/`.
  - **`autoresearcher/CLAUDE.md`** — the orchestrator's runtime guide. Read it
    before driving a run (it is what the researcher agent follows each iteration).
  - **`autoresearcher/AGENTS.md`** — the Codex-orchestrator sibling of that guide.
- **`AGENT.md`** (repo root) — the full AI-agent overview of the repo: the
  experiment model (researcher agent / victim agent / scenario as plugins;
  research + victim models as runtime params), the plugin registry, and layout.
- **`docs/`** — detailed docs: `ARCHITECTURE.md`, `QUICKSTART.md`, `USAGE.md`,
  `PLUGINS.md`, `PERMISSIONS.md`, `MODELS.md`, `BYO_SCENARIO.md`, plus
  `shared-references/` (the binding per-iteration contracts).
- **`README.md`** — human entry point. **`SECURITY.md`** — security policy.

## Running Stage-1 discovery

Two interchangeable drivers, same scientific contracts:

1. **Default** — the `/autoresearch-redteam-discovery` skill repeated by `/loop`
   (model-driven, one iteration per turn).
2. **Optional Workflow driver** — batched-parallel + resumable, at
   `autoresearcher/plugins/researchers/default/workflows/` (script
   `aha_discovery.js` + the host-side MCP server
   `autoresearcher/src/autoresearch_redteam/discovery_mcp.py`). See that
   directory's `README.md` for how to register the MCP server and launch it.

Both reuse the same four sub-agents, the falsifier protocol, the promotion gate,
and clean/ oracle isolation; neither ever self-stops (only the monitor's `STOP`
file, the outer cap, or the budget halts a run).

## Working here

- Never commit real credentials; follow `SECURITY.md`. Test fixtures contain
  intentional mock/decoy secrets — those are not real.
- The publishable casebook site lives under `docs/` and deploys to a separate
  remote; do not push code changes there.
