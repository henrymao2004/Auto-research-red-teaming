# codex researcher agent

The codex sibling of the `default` (Claude Code) researcher. Same
4-agent roster — Hypothesizer → Attack-designer → Reflector →
(every 10 iter) Critic — and the **same research method**; only the
orchestration substrate differs (codex custom agents instead of Claude
Task sub-agents).

Selected with `--researcher codex` at launch. Like `default`, the
agents are victim-/victim-model-/scenario-agnostic: all scenario-specific
context (attack-family blurb, attack JSON schema, instance path,
category list) is injected by the dispatch prompt the discovery skill
builds from the registry-resolved scenario plugin.

## Layout

```
agents/
  redteam-hypothesizer.toml     # Step 3a (gpt-5.5, high effort)
  redteam-attack-designer.toml  # Step 3b (gpt-5.5, high effort)
  redteam-reflector.toml        # Step 5  (gpt-5.5, LOW effort — cheap parse/classify)
  redteam-critic.toml           # Step 7.5, every 10 iter (gpt-5.5, high effort)
```

Each file is a **codex custom agent** (`name` / `description` /
`developer_instructions` required; `model` / `model_reasoning_effort` /
`sandbox_mode` optional). `launch_run.sh --researcher codex` copies these
into the worktree's `.codex/agents/`, where codex loads them as the
spawnable agent set for the orchestrator session.

## How dispatch works (vs the `default` researcher)

| `default` (Claude Code) | `codex` |
|---|---|
| orchestrator = Opus `/loop`; sub-agents via the **Task tool** | orchestrator = `codex exec`; sub-agents via codex's **native subagent spawn** (`.codex/agents/*.toml`) |
| `tools:` frontmatter allowlist | `sandbox_mode` (fs/shell) + `mcp_servers` per agent |
| ordering + file ownership structurally enforced by Task dispatch | ordering + file ownership enforced by **AGENTS.md** ("mandatory ordered dispatch + else INVALID") — the orchestrator must spawn one agent, wait for its result, then spawn the next |
| reflector = Sonnet | reflector = cheaper effort (swap `model` to a mini codex slug) |

Because codex returns a **consolidated** response only after all
*concurrently* requested agents finish, the ordered protocol (Hypothesizer
fully before Attack-designer; Reflector only after `run_attack`) requires
the orchestrator to issue **separate, sequential** spawn calls — never a
single batched fan-out. `autoresearcher/AGENTS.md` restates this as a hard
rule (an out-of-order or self-authored proposal/attack/reflection makes
the iteration INVALID).

## Model

Build/validate with **gpt-5.5**; swap the three heavy agents to
**gpt-5.5-pro** with a one-line per-agent `model` change once validated.
The Reflector stays on a cheaper model/effort (parse + classify).

## Reused unchanged

The discovery `SKILL.md` (Agent Skills cross-platform standard), the
shared-reference contracts (`falsifier-protocol` / `vcg-promotion` /
`subagent-dispatch`), the worktree / `RUN_HINT.md` / `run_attack` /
`vcg.md` / git / `STOP` machinery, the registry, and the monitor are all
victim-/researcher-agnostic and reused as-is.
