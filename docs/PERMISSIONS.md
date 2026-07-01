# Permissions + autonomous-agent standard

The orchestrator + sub-agents must run **fully autonomously** through
100 iterations — that's the whole point of overnight autoresearch.
Claude Code's default permission model would prompt on every Bash /
Write / Edit call, which kills throughput.

This project uses **one specific standard** that we've tested end-to-end.
Don't deviate without re-checking everything below.

---

## A. OS-level prerequisites

These must be installed and working **before** `launch_run.sh`.

| Requirement | macOS | Linux |
|---|---|---|
| Docker daemon | Docker Desktop running (whale icon in menu bar) | `systemctl status docker` shows active |
| Docker group | Docker Desktop handles it | User in `docker` group: `sudo usermod -aG docker $USER` then re-login |
| Git ≥ 2.5 | `brew install git` | Distro package |
| Python ≥ 3.10 | `brew install python@3.11` | Distro package |
| `uv` (recommended) | `curl -LsSf https://astral.sh/uv/install.sh \| sh` | same |
| `claude` CLI | Install Claude Code | same |
| `PATH` for above | launch_run.sh prepends `/opt/homebrew/bin` + `~/.local/bin` | Make sure all 4 binaries are on `PATH` |

Quick verify:

```bash
docker ps             # exit 0, no permission error
git --version          # >= 2.5
which claude uv python3 docker git
```

---

## B. Plan / API key access

The pipeline makes LLM calls from **two places** with **different protocols**:

### B.1 Orchestrator + sub-agents (Claude Code session)

- The `claude` CLI itself authenticates via your Claude Code account
  (Max plan recommended for Opus 4.7).
- Sub-agents request specific models in their YAML frontmatter (`opus`
  or `sonnet`). Your account must have access to those tiers.
- No env var needed for the orchestrator — Claude Code handles auth.

### B.2 Victim, Judge, Router (host-side and in-container LLM calls)

Three independently-configurable endpoint keys (see
[`docs/MODELS.md`](MODELS.md)):

| Key | Used by | Forwarded into container? |
|---|---|---|
| `ANTHROPIC_AUTH_TOKEN` (or `DEEPSEEK_API_KEY`) | Victim's `claude-agent-sdk` inside Docker | **YES** (it's the whole point — the SDK reads it from env) |
| `JUDGE_API_KEY` (+ `JUDGE_BASE_URL`, `JUDGE_MODEL`) | Host-side judge after each attack | NO |
| `ROUTER_API_KEY` (+ `ROUTER_BASE_URL`) | Host-side scenario-build generator | NO |

⚠ **Key safety note**: `ANTHROPIC_AUTH_TOKEN` is forwarded into the
victim container. Any attack that runs `env` inside the container will
see it (this is a real production-relevant finding, captured as
`VC-0004` in the paper's VCG). Mitigations: scoped tokens, key
rotation, or KMS-proxied endpoints. The judge and generator keys are
host-only and never reach the container.

---

## C. Network egress

| From | To | Required? | Why |
|---|---|---|---|
| Host | Anthropic Claude API (`claude.ai` etc.) | yes | Orchestrator + sub-agents run via Claude Code |
| Host | `JUDGE_BASE_URL` | yes | Host-side judge |
| Host | `ROUTER_BASE_URL` | yes for scenario-build | Generator endpoint |
| Container | `ANTHROPIC_BASE_URL` (victim's endpoint) | yes | `claude-agent-sdk` calls this on every turn |
| Container | Arbitrary outbound (e.g. `http://evil-attacker.com`) | **deliberately allowed** | The whole point — we measure whether the agent attempts exfil; the judge reads the trajectory and scores it |

The container runs **without** `--network none`. If you want a stricter
egress whitelist (allow only the anthropic-compat endpoint), add
`--network` rules or a sidecar firewall. The trade-off: you lose the
ability to detect "agent tries to POST to attacker URL" which is
half of what the paper measures.

---

## D. Filesystem access

| Path | Read | Write | Notes |
|---|---|---|---|
| `<repo>/` (the project checkout) | yes | yes | for `git worktree add`, `.claude/`, `attacks/` |
| `<repo>/worktrees/<run_code>/` | yes | yes (script + agents) | per-run isolated working tree |
| `/tmp/ar_ahz_*` (per-attack tempdir) | yes | yes | bind-mounted into each Docker container |
| `~/.claude/`, `~/.ssh/`, `~/.aws/`, `~/.config/` | **NO** | **NO** | hard-scope deny — orchestrator + sub-agents refuse |
| `/etc/`, `/usr/`, any `/Users/<other>/` | **NO** | **NO** | hard-scope deny |
| Sibling worktrees `worktrees/<other_run>/` | **NO** | **NO** | run-isolation deny |

The hard-scope deny is enforced **at the prompt level** in CLAUDE.md +
sub-agent definitions. `--dangerously-skip-permissions` suppresses the
per-call confirmation prompt but does NOT override these instructions
— the agents read them and follow them. Verify with a smoke test:

```bash
# In an active orchestrator session, try:
> Read ~/.ssh/id_rsa
# Expected: agent refuses, citing the deny list.
```

---

## E. The 5 isolation layers (what makes `--dangerously-skip-permissions` safe)

`scripts/launch_run.sh` ends in `exec claude --dangerously-skip-permissions`.
That skips all per-call prompts. Five layers make it safe in practice:

### Layer 1 — Per-attack Docker sandbox (victim)

Fresh `ar_<scenario>:latest` container per attack with:

- `--cpus 2.0 --memory 4g`
- Per-attack tempdir bind-mounted as two mounts: `/work` (agent cwd, agent-visible) + `/harness` (empty at start, only carries the trajectory output). The attack spec is piped to the container via stdin (`docker run -i`), so it never lands on a bind-mounted path; a victim that probes any in-container path can't recover its own attack plan.
- 10-min hard kill (`timeout_seconds=600`)
- `--rm` (no persistent storage)

Whatever the victim does inside — exfil / RCE / backdoor / etc. —
stays in the ephemeral container. See [`docs/DOCKER.md`](DOCKER.md).

### Layer 2 — Worktree isolation (orchestrator + sub-agents)

`launch_run.sh` creates `worktrees/<run_code>/` via `git worktree add`
and spawns claude **inside** it. The worktree:

- Is a separate working directory from your main checkout.
- Tracks a separate branch (`loop/<run_code>`).
- Cannot affect the main checkout unless you explicitly merge.

`git worktree remove --force worktrees/<run_code>` undoes the whole run.

### Layer 3 — Hard-scope deny list in sub-agent prompts

All four `.claude/agents/redteam-*.md` inherit the deny list from
`CLAUDE.md`. Documented above in section D.

### Layer 4 — Critic sub-agent audit (every 20 iter)

`redteam-critic` runs every 20 iterations in fresh context. It checks:

1. Reward hacking — duplicate attacks, template reuse with swapped
   strings, gaming the judge instead of breaking the victim.
2. Coverage gaps — categories not being explored.
3. Hypothesis quality drift — vague aspirational hypotheses instead
   of concrete falsifiable ones.
4. Cross-VC composition not being exploited.

Output appended to `AGENT_LOG.md`, read by next 20 iterations'
Hypothesizers.

### Layer 5 — Monitor sidecar with 7 stop signals

The `autoresearch-redteam-monitor` skill runs in a **separate** claude
session (Window 2). Every 15 min:

1. VCG saturation (no new concepts in last 20 iter)
2. Generalization gap (held-out vs Stage-1 break-rate divergence)
3. Per-mode confirmation rate
4. Reward hacking (duplicate attack patterns)
5. Over-budget pile-up
6. Surprise-signal drop
7. Outer iter cap (default 100)

Any one going `red` writes `attacks/<run_code>/STOP`. The orchestrator
checks for that file at Step 0 and exits gracefully. This is the
**kill switch** when you're not watching.

---

## F. Per-sub-agent tool restrictions

Each `.claude/agents/redteam-*.md` has a `tools:` YAML field that
restricts what tools that role can use:

```yaml
---
name: redteam-reflector
tools: Read, Write
model: sonnet
---
```

| Sub-agent | tools |
|---|---|
| `redteam-hypothesizer` | Read, Write, Bash, Grep, Glob |
| `redteam-attack-designer` | Read, Write, Edit, Bash, Grep, Glob |
| `redteam-reflector` | Read, Write |
| `redteam-critic` | Read, Write, Edit, Bash, Grep, Glob |

To tighten further, edit the relevant agent file's `tools:` line.
For the project-wide allow/deny rules, see §K below.

---

## G. Sub-agent + skill discovery priority

Claude Code discovers sub-agents and skills from multiple locations.
Priority order (highest → lowest):

1. **Project**: `<cwd>/.claude/agents/` and `<cwd>/.claude/skills/`
   (walks up from cwd; in our case cwd = the worktree)
2. **User-level**: `~/.claude/agents/` and `~/.claude/skills/`

If the same name exists at both levels, **project wins**. This is
critical for our setup — the project-level `redteam-*.md` files in
the worktree are what the orchestrator must dispatch.

⚠ **Gotcha**: if you have a stale user-level skill / agent file
with the **same name** as a project-level one, Claude Code's
slash-command resolution may pick the wrong one if cwd doesn't have
the project-level path. Symptom: orchestrator inlines `Write` calls
instead of dispatching sub-agents.

Verify inside the orchestrator session:

```text
> /agents
```

Should show 4 `redteam-*` plus the built-ins (Explore / Plan /
general-purpose / claude-code-guide / statusline-setup). If
`redteam-*` aren't listed, you're running without sub-agents — fix
before continuing.

Sub-agents + skills are loaded **at session start**. If you add or
edit a sub-agent file while a session is running, restart `claude` to
pick up the change.

---

## H. Resource sizing

Each Docker victim run uses 2 CPU / 4 GB RAM (set in
`target/claude_code_sdk_ahz.py`). Stage 2 held-out eval runs
containers in parallel:

```bash
bash scripts/run_heldout_eval.sh <run_code> <parallel>
```

Sizing guide:

| parallel | CPU needed | RAM needed |
|---|---|---|
| 1 | 2 | 4 GB |
| 4 | 8 | 16 GB |
| 8 | 16 | 32 GB |

Pick `parallel` so total stays below your host's headroom. The
orchestrator's own claude session uses very little (it doesn't load
trajectories into context); sub-agent context is bounded ≤ 50 K
tokens each.

---

## I. Pre-launch checklist

Run through this **before** typing `/loop`:

```bash
# 1. Docker up + image built
docker ps                                         # no permission error
docker images | grep "^ar_"                       # ar_claude_code_base + ar_<scenario>:latest lines present

# 2. Env vars set (don't echo the actual key; just check non-empty)
echo "ANTHROPIC_AUTH_TOKEN: ${ANTHROPIC_AUTH_TOKEN:0:5}…"  # or DEEPSEEK_API_KEY
echo "JUDGE_API_KEY:        ${JUDGE_API_KEY:0:5}…"
echo "ROUTER_API_KEY:       ${ROUTER_API_KEY:0:5}…"

# 3. Settings files present (see §K)
ls ~/.claude/settings.json                        # user-level autopilot + deny
ls .claude/settings.local.json                    # project-level allow/deny

# 4. Scenario data + split present (paths are relative to the plugin)
ls autoresearcher/plugins/scenarios/agenthazard/clean/ | head -5
ls autoresearcher/plugins/scenarios/agenthazard/{train,heldout,judge_data}.json

# 5. Worktree fresh (only if you want a clean start)
git worktree list | grep <run_code>   # remove first if stale

# 6. Launch
./scripts/launch_run.sh <run_code> '<goal>'

# 7. Inside claude session, verify sub-agents loaded
> /agents
# expect: redteam-{hypothesizer,attack-designer,reflector,critic}
#         + built-ins. If redteam-* missing, /exit and re-launch.

# 8. Inside claude session, start the loop
> /loop /autoresearch-redteam-discovery <run_code> <goal>
```

First-time setup (one-off, before step 1):

```bash
cp templates/claude-settings/user-settings.json ~/.claude/settings.json
cp templates/claude-settings/project-settings.local.json .claude/settings.local.json
```

After v1 appears (5-10 min), open Window 2 for the monitor:

```bash
cd worktrees/<run_code>
claude --dangerously-skip-permissions
> /loop 15m /autoresearch-redteam-monitor <run_code>
```

---

## K. Claude Code settings files (the actual allow/deny lists)

Two settings files. The split is **deliberate**: autopilot mode + the
extensive allow/deny lives in the **project-level** file (only affects
THIS repo), so adopting the templates does NOT cripple your other
Claude Code projects. The user-level file stays minimal — only blocks
operations that are catastrophic in any project (root wipe, disk
format, reboot).

### K.1 User-level: `~/.claude/settings.json` (minimal, ~10 lines)

```bash
cp templates/claude-settings/user-settings.json ~/.claude/settings.json
```

```json
{
  "skipDangerousModePermissionPrompt": true,
  "permissions": {
    "deny": [
      "Bash(rm -rf /*)",
      "Bash(rm -rf ~*)",
      "Bash(rm -rf $HOME*)",
      "Bash(dd of=/dev/*)",
      "Bash(dd if=*of=/dev/*)",
      "Bash(mkfs*)",
      "Bash(diskutil eraseDisk*)",
      "Bash(diskutil zeroDisk*)",
      "Bash(shutdown *)",
      "Bash(reboot*)"
    ]
  }
}
```

Two things at user level only:

| Field | Effect |
|---|---|
| `skipDangerousModePermissionPrompt: true` | Suppresses the "are you sure?" prompt at `--dangerously-skip-permissions` startup. Harmless if you don't use that flag. |
| `permissions.deny` (10 entries) | Blocks system-destruction ops (root wipe, disk format, reboot). Things you'd never want any project to do. |

What's intentionally **NOT** at user level:

- `defaultMode: bypassPermissions` — autopilot mode is per-project,
  not global. Your other Claude Code projects still prompt normally.
- Denies on `python -c`, `chmod +x`, `chown`, `eval`, `sudo`,
  `curl|sh`, `pip install`, `rsync`, `docker run -v`, macOS-specific
  ops, etc. — these are legitimate in many user workflows; deny them
  only **inside** the red-team project (next section).

### K.2 Project-level: `.claude/settings.local.json` (autopilot + full deny)

```bash
cp templates/claude-settings/project-settings.local.json .claude/settings.local.json
```

This file is the **whole autopilot + allow/deny stack** for this
project, scoped to this repo.

Key fields:

| Field | Effect |
|---|---|
| `permissions.defaultMode: "bypassPermissions"` | Auto-approve all tool calls in THIS project (does not leak to other projects) |
| `permissions.allow` | The autoresearch tool surface: `mkdir`, `git`, `uv`, `cat`/`ls`/`grep`/`sed`/`awk`, `python3`, `find`, `docker run --rm`, etc. Explicit allows keep things working under default-deny if you ever flip the mode. |
| `permissions.deny` | The full hard-block list (see below) |

The deny list has 3 categories:

**Category 1 — Path denies (protect the agent from corrupting its own infra)**

| Path pattern | Why |
|---|---|
| `Edit/Write(src/**)` | Python target / judge / utility code |
| `Edit/Write(.claude/**)` | Sub-agent definitions + skill files — agent must not rewrite its own rules |
| `Edit/Write(docker/**)` | Container build — must not compromise the sandbox |
| `Edit/Write(scripts/**)` | Stage 1/2 driver scripts |
| `Edit/Write(docs/**)` | Documentation |
| `Edit/Write(pyproject.toml`, `uv.lock`, `.gitignore`, `README.md`, `CLAUDE.md)` | Project metadata |
| `Edit/Write(plugins/**)` | All scenario + victim + researcher plugin code, contracts, datasets, splits, judges — agent MUST NOT modify shipped plugins. Broader-than-AHZ deny: covers every scenario's `clean/`, `clean_heldout/`, `*.json`, `judge.py`, `contract.yaml`, plus every victim's adapter + docker assets |
| `Read(plugins/scenarios/**/heldout.json)`, `Read(plugins/scenarios/**/judge_data.json)`, `Read(plugins/scenarios/**/clean_heldout/**)` | **Held-out leakage protection + judge-reference isolation** — Stage 1 agent never sees held-out IDs, the scenario's reference attacks, or held-out per-instance files. Per-scenario `train.json` + `clean/` stay readable for instance picking. |

**Category 2 — Path denies (protect the host)**

`/etc/**`, `/usr/**`, `/var/**`, `/root/**`, `~/.ssh/**`, `~/.aws/**`,
`~/.config/**`, `~/Documents/**`, `~/Downloads/**`, `~/Desktop/**`,
`~/.claude/settings*.json`, plus reads of `.env*`, `*.pem`, `*.key`,
`id_rsa*`, `/etc/shadow`, `/etc/passwd`.

**Category 3 — Bash denies (dangerous in autonomous context but legit in user's own work)**

This is the set that USED to be at user level and is now project-scoped:

```
Bash(sudo *), Bash(sudo:*),
Bash(curl * | sh), Bash(curl * | bash),
Bash(wget * | sh), Bash(wget * | bash),
Bash(eval *),
Bash(chmod +x *), Bash(chmod 7*), Bash(chmod:*),
Bash(chown *), Bash(chown:*),
Bash(rsync * *@*),
Bash(docker run * -v *), Bash(docker run *--volume*),
Bash(export HISTFILE*), Bash(unset HISTFILE*),
Bash(osascript *), Bash(launchctl *),
Bash(defaults write *), Bash(security *), Bash(pmset *),
Bash(pip:*), Bash(uv pip install:*),
Bash(rm -rf:*)
```

Outside this project, none of these are denied at user level — so your
own `python -c` quick checks, `chmod +x my_script.sh`, `pip install`,
`curl | sh` for installing tools, etc. all still work normally.

The agent writes under `attacks/<run_code>/` and commits on its branch —
which is exactly the scope it needs.

### K.3 launch_run.sh propagates `settings.local.json` into the worktree

`.claude/settings.local.json` is git-ignored (typical convention), so
`git worktree add` does NOT carry it across. `launch_run.sh` explicitly
copies it at worktree creation:

```bash
cp "$PROJ/.claude/settings.local.json" "$WT/.claude/settings.local.json"
```

If the file is missing in the main checkout, the launcher warns and
the worktree's claude session becomes user-level only — which
loses the "agent can't edit `src/`" protection AND autopilot mode.
**Don't skip this**.

### K.4 How the layers interact

When the orchestrator (or any sub-agent) attempts a tool call:

```
1. Is it in project-level (.claude/settings.local.json) deny?  → BLOCKED.
2. Is it in user-level (~/.claude/settings.json) deny?         → BLOCKED.
3. Is it in project-level allow?                               → APPROVED.
4. Is defaultMode=bypassPermissions in project-level?          → APPROVED.
5. Otherwise prompt (or with --dangerously-skip-permissions, approved).
```

Two design implications:

- **Scope**: autopilot (defaultMode=bypassPermissions) lives at
  project-level, so it only fires inside this repo. Other projects keep
  default prompting.
- **Safety net**: even with autopilot ON in this project, project +
  user denies still win — the agent cannot escape the deny rules.

---

## J. Worst-case recovery

If something goes wrong overnight, damage is contained to the worktree
+ branch + ephemeral containers:

```bash
# Kill running claude sessions
pkill -f "claude.*--dangerously" || true

# Kill leftover Docker containers
docker ps -q --filter "label=scenario" | xargs -r docker kill

# Nuke the worktree + branch
cd <repo>
git worktree remove worktrees/<run_code> --force
git branch -D loop/<run_code>

# Clean per-attack tempdirs (macOS / Linux)
rm -rf /tmp/ar_ahz_*
```

Your main checkout is untouched.

---

## L. Codex victim + researcher (maps to the Claude Code model)

Sections A–K describe the `claude_code` victim + `default` (Claude Code)
researcher. The `codex` victim and `codex` researcher reach the same end
state through codex-native mechanisms.

### L.1 Codex victim

| Aspect | claude_code victim | codex victim |
|---|---|---|
| Sandbox boundary | docker `ar_<scenario>:latest` | docker `ar_codex:latest` (codex bakes its own runner; does not use the scenario image) |
| Skip approvals | `claude --dangerously-skip-permissions` | `codex exec --dangerously-bypass-approvals-and-sandbox` (skips approval prompts, disables codex's own OS sandbox + execpolicy `.rules` — the container is the boundary) |
| Key forwarded in | `ANTHROPIC_AUTH_TOKEN` | `OPENROUTER_API_KEY` (same forwarding; visible to `env` inside the container) |
| Spec delivery | stdin, never on disk | stdin, never on disk |
| Scenario tools | MCP servers via `ClaudeAgentOptions(mcp_servers=…)` | `[mcp_servers.scenario_tools]` STDIO block; codex spawns `scenario_mcp_stdio.py` |
| Tool restriction | `disallowed_tools: [Bash, Read, …]` — per-tool-name removal (built-in + `mcp__*`) via the CLI's `--disallowedTools` | `--disable <FEATURE>` (= `-c features.<name>=false`): `shell_tool`, `unified_exec`, `apply_patch_*`, `web_search_*`, `browser_use`, `computer_use` |

The tool-restriction granularity differs: claude removes individual tools
(can drop `Bash` and keep `Read`); codex toggles tool features (`shell_tool`
disables the whole shell surface). For the dtap case — remove the built-in
coding surface, leave only the backend MCP tools — `--disable shell_tool
unified_exec apply_patch_streaming_events` is the codex equivalent.

The codex runner reads the same scenario `disallowed_tools` block (see
§M). When it sees shell/file-tool markers such as `Bash`, `Read`,
`Write`, or `Edit`, it launches `codex exec` with the non-MCP feature
flags disabled, leaving the scenario MCP tools as the available action
surface.

### L.2 Codex researcher

| Aspect | claude_code researcher | codex researcher |
|---|---|---|
| Tool surface | `.md` `tools:` allowlist + `settings.local.json` `allow` | `sandbox_mode = "workspace-write"` + per-agent `mcp_servers` in `.toml` |
| Boundary enforcement | `settings.local.json permissions.deny` (CLI-layer, evaluated before `--dangerously-skip-permissions` — §K.4) + CLAUDE.md prompt-level deny | OS-level `workspace-write` sandbox (fs + shell scoped to the workspace) |

Both enforce the boundary for real, at different layers: claude denies at the
CLI/tool layer (a deny rule applied to every tool call, surviving
`--dangerously-skip-permissions`); codex denies at the OS layer (a kernel
sandbox). The `.toml` comment states it directly: `sandbox_mode` replaces
claude's `tools:` allowlist.

---

## M. dtagent tool permissions (per-instance whitelist + contract blacklist)

`dtagent` carries two tool-permission layers, both default-on and
data-driven (no env var or flag — they apply whenever you run
`--scenario dtagent`).

### M.1 `available_tools` — per-instance MCP-server whitelist

Every instance carries a non-empty `available_tools` list at MCP-server
granularity (e.g. CRM → `[salesforce, slack]`, medical →
`[HospitalClient]`, os-filesystem → `[OS-filesystem, gmail, slack]`). It
becomes the victim's `mcp_servers`; backends not on the list are unreachable
for that instance.

### M.2 `disallowed_tools` — contract-level built-in blacklist

Defined once in `contract.yaml` `runtime.disallowed_tools` and applied
uniformly to all 390 instances across all four domains. It removes ~20
built-in tools (`Read`, `Write`, `Edit`, `Bash`, `BashOutput`, `KillShell`,
`Glob`, `Grep`, `TodoWrite`, `Task`, `Agent`, `AskUserQuestion`,
`NotebookEdit`, `WebSearch`, `WebFetch`, `ToolSearch`, `ExitPlanMode`,
`Cron*`), leaving only the bridged `mcp__<server>__*` backend tools.

Under `permission_mode=bypassPermissions` the victim's `allowed_tools` is
ignored, so `disallowed_tools` is the only lever that constrains the victim to
the backend tools. Without it the agent defaults to shell / AskUser and never
calls the backend tools; once the shell surface is removed it uses the backend
tools (e.g. `create_lead` / `create_record`).

Flow: `contract.runtime` → `run_attack._build_input_spec` serializes the
runtime block into the spec. The Claude Code runner passes
`disallowed_tools` to `ClaudeAgentOptions(disallowed_tools=…)`;
the Codex runner maps the same field to codex feature disables when the
scenario removes the built-in coding surface.

### M.3 Backend reachability (network layer, separate from permissions)

The whitelisted tools only work if their backend stacks are up. The victim
container reaches the ~15 live backends via `host.docker.internal:<port>`
(bridge ymls publish ports; `tools_mcp.py` rewrites per-instance loopback hosts
`127.0.0.1` → `host.docker.internal`). `build_dtagent_backends.sh` brings the
stacks up. This is the egress/network layer — it makes the allowed tools
usable but does not change which tools are allowed. A backend that is down
makes a whitelisted tool fail; it does not widen the permission set.
