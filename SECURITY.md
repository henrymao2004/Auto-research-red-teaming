# Security

AHA is a red-team harness. It intentionally stores harmful prompts,
attack payloads, and fake credential-looking benchmark seeds. Do not run
it against systems you do not own or have permission to test.

## Sandbox boundary

- Victim agents run in Docker containers with per-attack temporary
  workdirs.
- The attack spec is piped to the container over stdin rather than
  written into the agent-visible workspace.
- Scenario plugins can mount MCP tools and local benchmark backends; DTap
  uses local docker-compose services for its backend simulations.
- Claude Code project settings deny reads of held-out files and
  evaluator-only answer keys during Stage 1.

The sandbox is an engineering boundary, not a formal security boundary.
Run on a dedicated machine or account when evaluating untrusted scenarios.

## What runs locally

- `launch_run.sh` creates a git worktree under `autoresearcher/worktrees/`.
- `run_attack` starts Docker containers for victim execution.
- Stage 2 uses a separate `claude -p` instantiator with file and exec
  tools disallowed.
- DTap scenarios may start local backend services and open localhost
  ports.

## Benchmark seed strings

Some vendored benchmarks contain strings shaped like AWS, Stripe,
GitHub, or SendGrid keys. These are upstream benchmark seed data used to
test whether agents leak or misuse sensitive-looking content. They are
not required for real cloud access and should never be replaced with real
credentials.

GitHub secret scanning may flag these strings in public forks. Treat
alerts as benchmark false positives only after confirming the exact file
is vendored scenario data.

## Reporting issues

Please open a GitHub issue with:

- affected commit hash,
- scenario/victim/model,
- command used,
- whether Docker or DTap backends were running,
- relevant logs with real API keys removed.

For private security reports, email the maintainer listed in the paper or
repository profile.
