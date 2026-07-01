# Docker (victim sandbox)

Every attack spawns a fresh per-scenario container. Each scenario
has its **own image** (`ar_<scenario>:latest`) layered on top of a
shared base image (`ar_claude_code_base:latest`) — common runtime in
the base, scenario-specific deps in the leaf. The container runs
`claude-agent-sdk` + the bundled `claude` CLI, processes attack
payload + optional MCP tools + optional PostToolUse interceptors,
and writes a trajectory file the host then judges.

## Why Docker

| Concern | What Docker gives us |
|---|---|
| Filesystem isolation | Victim's `Bash`/`Write`/`Edit` cannot touch the host's `~/.ssh`, `~/.claude`, etc. Only `/work` (agent cwd, per-attack tempdir), `/harness` (empty at start, only carries the trajectory output) and `/plugins` (read-only) are bind-mounted. The attack spec is piped via stdin and never lands on disk in the container, so a probing victim can't recover its own attack plan from any path. |
| Reproducibility | `ar_<scenario>:latest` is pinned per scenario; runs in the same image across cells |
| Parallelism | Different attacks run in different containers — no shared state |
| Egress control | Use `--network` flags to allow / block outbound HTTP from the victim |
| Per-scenario deps | Each scenario installs only what it needs (e.g. `ar_agentdyn:latest` carries `pip install agentdojo`) — no bloat in unrelated cells |

## Build the images

Two scripts:

```bash
# Step 1: build the shared base (claude-agent-sdk + runner). Once per checkout.
bash autoresearcher/scripts/build_base_image.sh
# → ar_claude_code_base:latest

# Step 2: build one or more scenario images on top.
bash autoresearcher/scripts/build_scenario_image.sh agenthazard   # → ar_agenthazard:latest
bash autoresearcher/scripts/build_scenario_image.sh agentdyn     # → ar_agentdyn:latest
bash autoresearcher/scripts/build_scenario_image.sh dtagent      # → ar_dtagent:latest
```

`scripts/launch_run.sh` auto-runs both if the scenario's image is
missing at launch time, so you don't need to think about it in
practice; the scripts are documented separately for CI / explicit
control.

### `dtagent` also needs live backend stacks (the only scenario that does)

The victim images above are all `agenthazard` / `agentdyn` need — their tools
are the agent's own built-ins (`agent_builtin`) or an in-process pip package
(`in_process_pkg`). `dtagent` is `tool_env.type: docker_compose_backend`: its
victims act through ~15 **live docker-compose backend stacks** (salesforce,
gmail, slack, calendar, atlassian, medical, paypal, whatsapp, googledocs,
snowflake, github, zoom, google-form, databricks, bigquery). One script pulls
every backend image, builds the local `ar_medical_service` patch (the medical
patient/judge sim runs through OpenRouter — `decodingtrustagent/hospital:latest`
does not exist on Docker Hub, `medical-service:latest` does), and brings every
bridge up (re-homed onto bridge networks + published host ports, since DTap's
upstream `network_mode:host` is unreachable on Docker Desktop for Mac):

```bash
OPENROUTER_API_KEY=sk-or-... \
  bash autoresearcher/scripts/build_dtagent_backends.sh        # pull + build + up
# subcommands: pull | build | up | down | all (default all)
```

Bridge stacks live at `plugins/scenarios/dtagent/envs/<svc>.bridge.yml`; the
medical patch at `plugins/scenarios/dtagent/medical_patch/`. Each instance uses
only a SUBSET of the backends (from its `mcp_servers`), but a full discovery /
held-out run spans all four domains, so bring them all up.

What's inside the **base** image (`Dockerfile.base`):

| Component | Purpose | Version pin |
|---|---|---|
| Ubuntu 22.04 base | runtime | — |
| Node 22 | the bundled `claude` CLI ships as a Node binary; needs Node runtime | `setup_22.x` |
| Python 3 + pip | SDK runtime | system-package |
| `claude-agent-sdk` | victim's SDK shim | `==0.2.87` (pinned — newer versions sometimes break the in-container handshake) |
| `anyio`, `mcp` | SDK deps | latest |
| `docker/in_container_runner.py` | reads the attack spec from **stdin** (piped by the host adapter), drives `ClaudeSDKClient`, writes `/harness/trajectory.json` (the spec never touches the container filesystem so a probing victim can't recover it from any path) | — |
| Non-root `agent` user with `HOME=/home/agent` | the bundled `claude` CLI **refuses `--dangerously-skip-permissions` when running as root**, AND writes session state to `$HOME` on first launch | — |

The image is intentionally small — only what the victim needs to execute
attacks. No host secrets baked in; auth tokens are passed via `-e` at
`docker run` time.

### Why a non-root user (the silent-failure trap)

The bundled `claude` CLI silently exits when `$HOME` is unwritable. Since
the default `root` user's home is `/root` and Docker often makes that
read-only-ish, the SDK's `initialize` handshake times out with no clear
error message. Symptom: `result.json` reports
`container exited rc=0 without writing trajectory.json`. Fix is baked
into the Dockerfile:

```dockerfile
RUN useradd -m -s /bin/bash agent \
 && mkdir -p /work /home/agent/.claude /home/agent/.config /home/agent/.npm \
 && chown -R agent:agent /work /app /home/agent
ENV HOME=/home/agent
USER agent
```

If you customise the image, keep these lines. Removing them brings back
"Control request timeout: initialize" failures.

### PyPI mirror (regional optional)

The shipped Dockerfile uses the tsinghua mirror:

```dockerfile
RUN pip3 install --no-cache-dir --timeout 120 --retries 5 \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    claude-agent-sdk==0.2.87 anyio mcp
```

This helps when running from China. Outside China, swap the `-i` URL for
default PyPI or your private mirror.

## Per-attack run

Driven by `src/autoresearch_redteam/target/claude_code_sdk_ahz.py::_docker_run`:

```bash
docker run --rm -i \
  --cpus 2.0 --memory 4g \
  -v /tmp/ar_xxx/work:/work \
  -v /tmp/ar_xxx/harness:/harness \
  -e ANTHROPIC_BASE_URL="$ANTHROPIC_BASE_URL" \
  -e ANTHROPIC_AUTH_TOKEN="$ANTHROPIC_AUTH_TOKEN" \
  -e ANTHROPIC_API_KEY="" \
  -e CLAUDE_CODE_STREAM_CLOSE_TIMEOUT=180000 \
  -e CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1 \
  ar_<scenario>:latest < input_spec.json
```

The host pipes the attack spec JSON to the container's stdin via
`docker run -i`; the runner reads from stdin, drives the attack, and
writes `/harness/trajectory.json`. **Nothing is written to disk in the
container before the SDK starts** — the spec lives only in the runner
process's memory. `/work` is the agent's cwd and starts empty (only
`initial_env.json` lands there when `environment_hydration.kind != none`,
since that file is the IPI vector and is meant to be agent-visible).

### Input spec schema (host stdin → container)

```json
{
  "model": "claude-haiku-4-5",
  "decomposed_query": ["<step 1 user message>", "<step 2 ...>", "..."],
  "max_turns_per_user_msg": 25
}
```

`model` is the model slug. The in-container runner translates Anthropic
slugs to the CLI's short aliases (`claude-haiku-4-5` → `haiku`,
`claude-opus-4-5` → `opus`, etc.) before invoking `ClaudeSDKClient`.

### `trajectory.json` schema (container → host)

```json
{
  "assistant_messages": [
    {"role": "assistant", "content": "..."},
    {"role": "tool_use", "name": "Bash", "input": {...}},
    {"role": "tool_result", "tool_use_id": "...", "content": "..."}
  ],
  "tool_calls": [
    {"name": "Bash", "arguments": {...}, "id": "..."}
  ],
  "final_text": "...",
  "reasoning": "...",
  "result_meta": {
    "num_turns": 7,
    "duration_ms": 42000,
    "stop_reason": "end_turn",
    "usage": {
      "input_tokens": 12345,
      "output_tokens": 678,
      "cache_creation_input_tokens": 0,
      "cache_read_input_tokens": 0
    }
  },
  "error": null
}
```

The host's `_build_eval` (in `claude_code_sdk_ahz.py`) reads this,
computes `over_budget = effective_input > max_input_tokens || output >
max_output_tokens`, calls the judge with `assistant_messages`, and
writes `result.json` + `trajectory.json` to the run's `v<N>/` dir.

## Egress (outbound network)

By default the container has unrestricted egress — `claude-agent-sdk`
needs to reach `ANTHROPIC_BASE_URL`. This means the victim **can** make
arbitrary HTTP calls from inside, including to attacker-controlled URLs
(this is the whole point of exfiltration attacks — we want the agent to
try, then measure whether it does).

If you want a stricter sandbox (e.g. allow only the anthropic endpoint),
add `--network` rules or a sidecar firewall container. The current paper
permits all egress; the breakage gets caught by the judge reading the
trajectory.

## Resource caps

- `--cpus 2.0` and `--memory 4g` keep one container at ~2 CPU cores +
  4 GB RAM. Adjust for parallel runs (`run_heldout_eval.sh` runs N
  containers concurrently when given `parallel ≥ 2`).
- `timeout_seconds=600` (10 min hard kill) per attack — set in
  `claude_code_sdk_ahz.py`.

## Customising the image

Common extensions:

1. **Different victim runtime**: the Codex victim ships as
   `plugins/victims/codex/` with `build_codex_image.sh` producing
   `ar_codex:latest`. Use it with `--victim codex`; it consumes the
   same input/trajectory schema as `claude_code`.

2. **Different scenario surface**: AgentDojo needs additional tool
   simulators (email, banking, slack). Add `docker/in_container_runner_agentdojo.py`
   that wires those up.

3. **Logging**: bake `tcpdump` + log shipper into the image if you want
   to observe the victim's outbound calls outside what the trajectory
   records.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `container exited rc=0 without writing trajectory.json` | claude CLI cold-start silently exited (usually because `HOME=/root` is unwritable) | Verify the Dockerfile creates the `agent` user + sets `HOME=/home/agent`; rebuild image |
| `Control request timeout: initialize` in stderr | Same as above — `claude-agent-sdk` handshake times out at 2 s because the bundled CLI exited before responding | Same fix; also set `CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK=1` in the docker run env to skip the 2 s health-check on cold containers |
| `container exited rc=N` with N != 0 | python/sdk exception | Read `stderr_tail` in `result.json`; bump `CLAUDE_CODE_STREAM_CLOSE_TIMEOUT` if the SDK ran but stream didn't close |
| Container hangs >10 min | infinite tool-use loop | Hard-killed by `timeout_seconds=600`; check trajectory tail |
| `Authentication error 401` | `ANTHROPIC_AUTH_TOKEN` not forwarded or wrong key | Make sure the host has it exported before `docker run`; key must match the `ANTHROPIC_BASE_URL` provider |
| `pip install` fails in build | tsinghua mirror unreachable | Edit `docker/Dockerfile.base` to use default PyPI or your local mirror |
