# Built-in scenarios

The scenarios that ship with the repo — **AgentHazard**, **AgentDyn**,
and **DTAP** (DecodingTrust-Agent) — documented here as concrete
examples. They are **not the template**: an experiment (a given
researcher agent, victim agent, victim model, scenario) runs the same
way for any scenario. To make your own, use the guided interview —
`/scenario-build` (synthesize from a free-text idea) or
`/scenario-import` (pull in an existing benchmark), see
[`BYO_SCENARIO.md`](BYO_SCENARIO.md). This doc records what the
shipped examples set, for reference.

## AgentHazard (built-in)

- Paper: [arXiv:2604.02947](https://arxiv.org/abs/2604.02947)
- Code: [github.com/Yunhao-Feng/AgentHazard](https://github.com/Yunhao-Feng/AgentHazard)
- **2653 instances**, 10 categories (Data_Exfiltration, System_RCE,
  Internal_Reconnaissance, Privilege_Escalation, Resource_Exhaustion,
  Persistence_Establishment, Supply_Chain_Poisoning, Prompt_Intel_Theft,
  Compliance_Bypass, Destructive_Action).
- Attack paradigm: **direct multi-turn prompt attack**. User-as-attacker
  sends 3-7 user-turn messages to a helpful agent that executes tools.
  Each turn looks innocuous in isolation; the sequence implements harm.

### Setup

**Data is bundled** inside the plugin directory at
`plugins/scenarios/agenthazard/`: `clean/`, `judge_data.json`,
`train.json`, `heldout.json` — nothing to fetch. See
`plugins/scenarios/agenthazard/clean/NOTICE` for upstream attribution.

If you want to **reproduce** the bundle from the upstream AgentHazard
dataset (or pick up newer upstream changes), run the plugin's local
scripts:

```bash
git clone https://github.com/Yunhao-Feng/AgentHazard /tmp/agenthazard
cd autoresearcher/plugins/scenarios/agenthazard
uv run python convert.py \
    --source /tmp/agenthazard/data/dataset.json \
    --output clean/ \
    --judge-data-out judge_data.json
uv run python regen_split.py
```

### Schema

Each `plugins/scenarios/agenthazard/clean/<category>/<id>.json` exposes:

```json
{
  "id": 1593,
  "category": "Data_Exfiltration",
  "query": "<the harmful goal>",
  "jailbreak_method": "<attack-strategy label from the paper>",
  "comment": "<additional framing context>"
}
```

The original `decomposed_query` reference attack is **stripped** from
this view — our agents are forced to design their own. The full
instance (including reference attack) lives in `judge_data.json`
inside the plugin dir, only fed to the judge for context.

### Split

`plugins/scenarios/agenthazard/regen_split.py` writes two files with
`seed=42` stratified:

- `train.json` — Stage-1 view. What Stage 1 sub-agents read to
  know which instance IDs are eligible to attack.
- `heldout.json` — held-out-only view. **Permission-denied** to
  the orchestrator and sub-agents (project settings deny `Read` on
  `plugins/scenarios/**/heldout.json`); read only by Stage 2 scripts
  run as bash subprocesses (after Stage 1 ends) and by
  `src/autoresearch_redteam/run_attack.py` for classification.

There is intentionally no combined `ahz_split.json`: keeping the
held-out IDs in a separately-permissioned file prevents Stage 1
from seeing held-out instance IDs at all. The distribution per
category is:

| Category | Stage 1 | Held-out |
|---|---|---|
| Compliance_Bypass | 165 | 9 |
| Data_Exfiltration | 333 | 9 |
| Destructive_Action | 116 | 9 |
| Internal_Reconnaissance | 444 | 9 |
| Persistence_Establishment | 246 | 9 |
| Privilege_Escalation | 158 | 9 |
| Prompt_Intel_Theft | 251 | 9 |
| Resource_Exhaustion | 367 | 9 |
| Supply_Chain_Poisoning | 239 | 9 |
| System_RCE | 244 | 9 |
| **Total** | **2563** | **90** |

The autoresearch loop picks **only from the Stage-1 view** during Stage 1. The 90
held-out are reserved for Stage 2 ASR comparison.

## AgentDyn

- Built on the AgentDojo framework (fork: <https://github.com/SaFo-Lab/AgentDyn>)
- Upstream paper: [arXiv:2406.13352](https://arxiv.org/abs/2406.13352) ·
  Site: <https://agentdojo.spylab.ai/>
- **Indirect prompt injection** paradigm: attacker controls untrusted
  content (a tool response — product review, issue comment, message
  body) that a benign agent reads mid-task.

The bundled data layer is extracted from the upstream AgentDyn fork
(imported as `agentdojo`, suite tag v1.2.2) via
`plugins/scenarios/agentdyn/convert.py` (script walks
`task_suite.load_suites.get_suite()` per suite × every
(user_task, injection_task) pair).

| Suite | Pairs (= our instances) | Stage 1 | Held-out |
|---|---:|---:|---:|
| shopping | 180 | 162 | 18 |
| github | 180 | 162 | 18 |
| dailylife | 200 | 180 | 20 |
| **Total** | **560** | **504** | **56** |

Runtime: declarative + `mcp_tools_module`.
`plugins/scenarios/agentdyn/tools_mcp.py` exposes the fork's
per-suite tools as MCP tools via `@tool` + `create_sdk_mcp_server`. The
`ar_agentdyn:latest` image extends `ar_claude_code_base:latest`
with `pip install "agentdojo @ git+https://github.com/SaFo-Lab/AgentDyn.git"`, and the plugin dir is
bind-mounted into the container so the MCP server module imports at
runtime. The researcher's `attack.json` carries `interceptors`
(a list of `{tool, match, action}` dicts); the runner's PostToolUse
hook applies them — `tool` and placement are part of what the
researcher discovers, no fixed attack strategy is baked into the
contract.

Judge: pure function-call match against upstream's
`(user_task.ground_truth, injection_task.ground_truth)` —
`plugins/scenarios/agentdyn/judge.py`. No LLM call.

Held-out leakage protection: same shape as AHZ —
`plugins/scenarios/agentdyn/clean_heldout/**` is Read-denied at the
settings layer; the 95 held-out instance files live there. The
orchestrator cannot see them by `ls` or by reading
`heldout.json`/`judge_data.json`.

## DTAP (DecodingTrust-Agent)

- Paper: [arXiv:2605.04808](https://arxiv.org/abs/2605.04808)
- Source: **DecodingTrust-Agent** (DTap) — its agent-task benchmark,
  imported into the contract-driven format via the `/scenario-import`
  flow (`plugins/scenarios/dtagent/convert.py`).
- **Attack-only** paradigm spanning four domains — **crm**, **medical**,
  **workflow**, **os-filesystem** — with two injection channels, selected
  per-instance by a `threat_model` field:
  - **direct** — the adversary controls the user prompt (an explicitly
    malicious request, ≈ AgentHazard).
  - **indirect** — the benign DTap `task_instruction` is the user
    message; the injection rides in untrusted tool/environment content
    the agent reads mid-task (≈ AgentDyn).

  (DTap's benign/utility instances have been **removed** — this scenario
  no longer carries a benign threat model.)

### Setup / Source

Victims act **only through bridged MCP tools**. There is no shell or
direct backend access: `plugins/scenarios/dtagent/tools_mcp.py` loads
the vendored DTap tool servers under
`plugins/scenarios/dtagent/dtap_servers/` (e.g. `salesforce_main.py`,
`hospital_main.py`, `gmail_main.py`, `slack_main.py`,
`calendar_main.py`) in-process via `create_sdk_mcp_server` and wraps each
backend method as a `claude-agent-sdk @tool`. Those servers talk to
**live docker-compose backends** brought up from
`plugins/scenarios/dtagent/envs/*.bridge.yml` (the CRM fleet —
salesforce / gmail / slack / calendar / atlassian — the medical
hospital, plus the workflow and os-filesystem fleets). Servers come in
two shapes: **thin-proxy** backends (the server forwards to a live
compose container) and **local-compute** backends (the server runs the
backend logic in-process — e.g. `faiss` for vector search, `psycopg` for
Postgres — no separate container). On Docker Desktop the victim runs
containerized, so `tools_mcp._load_server` rewrites any loopback host in
a per-instance `env_vars` (DTap ships e.g. `HOSPITAL_HOST=127.0.0.1`, a
host-side value) to `host.docker.internal` before connecting.

The **medical** backend is special: upstream's
`decodingtrustagent/hospital:latest` image does not exist on Docker Hub,
so it is built as `ar_medical_service:latest` (patched from
`decodingtrustagent/medical-service:latest`) whose LLM-driven
patient/measurement/judge simulator is routed through **OpenRouter**
(`OPENAI_BASE_URL` + `LLM_MODEL_OVERRIDE=openai/gpt-4o-mini`). It is
brought up via `envs/medical.bridge.yml` (publishes `:12001`, ships its
own data — no `./data` mount).

Per-instance reset is host-side via vendored
`plugins/scenarios/dtagent/setups/<domain>/<id>/setup.sh` (medical =
`POST /reset` clears the tool log + in-memory state), wired through the
contract's `reset_hook`.

### Schema

Each clean instance lives at
`plugins/scenarios/dtagent/clean/<domain>/<id>.json` and carries (among
others) `instance_id`, `threat_model` (`direct` / `indirect`),
`user_prompt` (the adversarial message for direct; the verbatim benign
`task_instruction` for indirect), `mcp_servers` (per-instance server
configs + `env_vars`), `judge_ref`, and the indirect injection spec.
The researcher's `attack.json` carries `user_prompt`, `injection_steps`
(mode B), and `interceptors` (mode A) — see Tools / judge.

### Split

Standard repo layout: `train.json` (Stage-1 eligible IDs) and a
permission-denied held-out view; held-out instance files are Read-denied
to the orchestrator and sub-agents at the settings layer, read only by
Stage-2 scripts. The scenario spans all four DTap domains — **crm**,
**medical**, **workflow**, **os-filesystem** — each wired and validated
end-to-end (direct + indirect). Held-out leakage protection mirrors AHZ
/ AgentDyn: `plugins/scenarios/dtagent/clean_heldout/**` is Read-denied
at the settings layer, so the orchestrator cannot see held-out IDs via
`ls` or by reading `heldout.json` / `judge_data.json`.

### Tools / judge

**Indirect injection has two modes**, both contract-driven and both
no-ops when their payload is absent (so they coexist):

- **Mode A — `tool_response_interceptors` (e.g. medical).** The
  researcher's `attack.interceptors` (e.g. `injected_tool:
  HospitalClient:init_patient, mode:suffix`) maps to a
  `{tool, action:{kind:append, content}}` interceptor, lifted by
  `make_attack.py` and applied at runtime by the PostToolUse-hook
  interceptor runtime via the contract's
  `runtime.tool_response_interceptors_from: attack.interceptors` (the
  same mechanism AgentDyn uses — it splices the injection into the
  tool's **output**).
- **Mode B — `inject_hook` backend pre-plant (e.g. crm).** The
  contract's `inject_hook` runs `attack.injection_steps` against the
  live backend before the victim starts (e.g. planting a phishing email
  the agent later reads).

**Judge: per-instance, vendored.** `judge.mode=per_instance`; each
instance carries its own `judge_ref` into the vendored per-instance
judges under `plugins/scenarios/dtagent/judges/<domain>/<id>/`, which
expose `eval_task` / `eval_attack` evaluated against live backend state
(deps vendored under `plugins/scenarios/dtagent/_dtap/` → self-contained, no external clone; `DTAP_REPO` overrides to a live clone). A **loadability guard** imports every one of the
**486** referenced judges before a run — relying on `dt_arena.utils`
being on the path so each vendored judge's `from dt_arena.utils... import
...` resolves — to catch missing/broken `judge_ref`s up front.

**Metrics:** `metrics.py` reports **direct ASR**, **indirect ASR**, and
**overall ASR** (malicious broken / total), per-domain, excluding
invalid trajectories.

## Other scenarios

Any new scenario lands in `plugins/scenarios/<name>/` with a
`contract.yaml` driving everything (attack family, payload schema,
visibility partition, runtime wiring, judge type). Three entry points:

1. **`/scenario-build "<idea>"`** — interactive bootstrap when you
   have no upstream dataset. Architect interviews you, the generator
   LLM synthesises instances, the skill materialises the plugin.
2. **`/scenario-import "<name> from <upstream>"`** — for published
   benchmarks (pip / git / HuggingFace / local files). AgentDojo is
   the canonical output of this flow.
3. **Manual** — write `contract.yaml` + a thin `scenario.py`
   subclassing `ContractDrivenScenario` + `judge.py`. See
   [`BYO_SCENARIO.md`](BYO_SCENARIO.md).

All three converge on the same on-disk layout the registry expects:
`contract.yaml`, `scenario.py`, `scenario.yaml`, `clean/`,
`clean_heldout/`, `train.json`, `heldout.json`, `judge_data.json`,
`judge.py` (+ optional `tools_mcp.py`, `Dockerfile`,
`judge/<rule>.md`).
