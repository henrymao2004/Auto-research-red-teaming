# Changelog

## Unreleased

- Added an optional Workflow driver for Stage-1 discovery
  (batched-parallel, resumable), via `discovery_mcp.py` +
  `plugins/researchers/default/workflows/`.
- Added `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` for the research backbone
  (`scripts/launch_run.sh`) and the Stage-2 instantiator
  (`scripts/instantiate_concepts.py`), keeping host auto-memory out of
  research/eval contexts.

## v0.1.0 - initial public release

- Shipped victim agents: `claude_code`, `codex`.
- Shipped scenarios: `agenthazard`, `agentdyn`, `dtagent`.
- Added Stage 1 autonomous discovery loop with Hypothesizer,
  Attack-Designer, Reflector, Critic, and monitor sidecar.
- Added Stage 2 held-out evaluation via Claude Code instantiation.
- Added guided scenario build/import flows.
- Added Docker victim sandboxing and DTap local backend support.
