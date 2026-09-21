# CLAUDE.md — repo-root navigation

Root of the **Auto-research-red-teaming-in-sleep (AHA)** monorepo. Claude Code
auto-loads this file when a session starts here; the substantive guides live one
level down, so this file is just a map.

## Where things are

- **`autoresearcher/`** — the main project (the autoresearch red-team system).
  Do substantive work from here: it holds `scripts/`, `plugins/`, `src/`.
  - **`autoresearcher/CLAUDE.md`** — the Researcher's runtime guide. Read it
    before driving a run (it is what the Researcher follows each iteration).
  - **`autoresearcher/AGENTS.md`** — the Codex-Researcher sibling of that guide.
- **`AGENT.md`** (repo root) — the full AI-agent overview of the repo: the
  experiment model (researcher agent / victim agent / scenario as plugins;
  research + victim models as runtime params), the plugin registry, and layout.
- **`docs/`** — detailed docs: `ARCHITECTURE.md`, `QUICKSTART.md`, `USAGE.md`,
  `PLUGINS.md`, `PERMISSIONS.md`, `MODELS.md`, `BYO_SCENARIO.md`, plus
  `shared-references/` (the binding per-iteration contracts).
- **`README.md`** — human entry point. **`SECURITY.md`** — security policy.

## Running Stage-1 discovery

Drive `/autoresearch-redteam-discovery` with `/loop` (one iteration per
turn). The Researcher selects the next experiment and dispatches four
sub-agents under the falsifier protocol and promotion gate. Only the
monitor's `STOP` file, the outer cap, or the budget halt a run.

## Working here

- Never commit real credentials; follow `SECURITY.md`. Test fixtures contain
  intentional mock/decoy secrets — those are not real.
- The publishable casebook site lives under `docs/` and deploys to a separate
  remote; do not push code changes there.
