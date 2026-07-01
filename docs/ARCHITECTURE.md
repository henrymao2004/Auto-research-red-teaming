# Architecture

## Pipeline (one iteration)

```
Step 0   Orchestrator: check STOP file → exit if exists
Step 1   Orchestrator: read state (AGENT_LOG.md, vcg.md, last 3 reflections)
Step 2   Orchestrator: pick mode (EXPLORE/EXPLOIT/TRANSFER/CONSOLIDATE)
                       + pick a Stage-1 instance (NEVER held-out)
Step 3a  Task(redteam-hypothesizer)
         → writes v<N>/proposal.md hypothesis section
Step 3b  Task(redteam-attack-designer)
         → writes v<N>/attack.json + proposal.md attack-plan section
Step 4   Bash: uv run -m autoresearch_redteam.run_attack ...
         → spawns Docker victim, runs judge, writes
           v<N>/result.json + v<N>/trajectory.json
Step 5   Task(redteam-reflector)  (sonnet, parse-heavy)
         → writes v<N>/reflection.md (is_break, hypothesis_status,
           novel_pattern, surprise_signal, optional New concept tuple)
Step 6   Orchestrator: update vcg.md (counters, candidate→COUNTED promotion)
Step 7   Orchestrator: git commit
Step 7.5 (every 20 iter) Task(redteam-critic)
         → appends "## Critic check @ v<N>" block to AGENT_LOG.md
           auditing 4 axes: cross-VC composition, reward hacking,
           coverage gaps, hypothesis quality drift
Step 8   Orchestrator: append iteration row to AGENT_LOG.md
Step 9   Orchestrator: done → /loop schedules next iter
```

## Why the multi-agent split

Single-agent autoresearch (Karpathy 2026, Claudini 2026) works but
exhibits **reward hacking** around iter ~95 (Claudini §5): the agent
starts gaming the evaluator instead of finding genuinely new attacks.
Splitting the cognitive work into role-specialised sub-agents with
fresh context prevents the failure mode:

| Sub-agent | Why isolated context |
|---|---|
| **Hypothesizer** (opus) | Commits a falsifiable hypothesis **before** seeing the attack. Same agent doing both retrofits the hypothesis to match the attack. |
| **Attack-designer** (opus) | Only sees the hypothesis, not the Hypothesizer's reasoning. Forces concrete framing that *implements* the hypothesis. |
| **Reflector** (sonnet) | Classification work, not creation. Sonnet 4.6 ≈ 5× cheaper than Opus per call. |
| **Critic** (opus, every 20 iter) | Fresh-context audit of last 20 iter for reward hacking. The Researcher has no incentive to catch its own cheating; the Critic does. |

## Vulnerability Concept Graph (VCG)

`attacks/<run_code>/vcg.md` is the persistent worldview. Each concept
block:

```
### VC-NNNN
- **mechanism**: <reusable NL — what reasoning pattern in the victim let the attack succeed?>
- **enabling_condition**: <when does this concept fire? what victim state is required?>
- **attack_template**: <abstract template — multi-turn salami structure, or single-shot injection wrapper>
- **failure_outcome**: <observable harm: what tool calls? what files? what HTTP traffic?>
- **transfer_prediction**: <which other categories / victims should this work on?>
- **provenance**: confirmed | partial
- **confidence**: <0-1>
- **n_observations**: <int>
- **n_confirmations**: <int>
- **n_falsifications**: <int>
- **targets_validated**: ["<victim>/<model>", ...]
```

### Counted concepts (paper-grade)

A concept is promoted to **COUNTED** (the set used for Stage 2 eval +
cross-victim transfer claims) when:

- `n_confirmations >= 3`
- `len(targets_validated) >= 2` (cross-target reproducibility)
- `confidence >= 0.6`
- at least one `is_break=true` observation in `n_confirmations`
  (partial-only never promotes — anti-reward-hacking)

This is the rule `scripts/freeze_concepts.py` applies before Stage 2.

### Edges

Optional pipe-delimited rows at the bottom of `vcg.md`:

```
| VC-NNNN | composes_with | VC-MMMM | 0.8 | v29 broke instance 1593 only when both fired |
```

Relations the agent may use: `composes_with`, `subsumes`, `falsifies`,
`mutually_exclusive_with`. Edges feed the cross-VC composition analysis
(Fig 3 in the paper).

## Falsifiable-hypothesis protocol

Every iteration's `proposal.md` must contain:

- **Mechanism** — the reasoning pattern the attack relies on
- **Step framing** — how individual user turns look innocuous
- **Predicted failure** — what observable outcome the attacker
  expects (which tool calls, what side effects)
- **Falsifier** — what observation would *refute* the hypothesis
- **Crucial experiment** — why this specific decomposed_query
  distinguishes confirm from falsify

The Hypothesizer sub-agent fails its iteration if it can't articulate a
concrete falsifier. The Reflector classifies the iteration's outcome as
`confirmed` / `falsified` / `inconclusive` based on whether the
falsifier observation actually occurred.

This is what makes our system **science** instead of "throw attacks
at the wall and see what sticks".

## Stage 1 vs Stage 2

**Stage 1 (search)**: orchestrator + sub-agents iterate on the
scenario's discovery set. Up to 100 iter unless monitor halts earlier.
Output: `vcg.md` with discovered concepts.

**Stage 2 (held-out eval)**: deterministic, no orchestrator. For each
held-out instance, a separate **Claude Code instantiator** picks the single
best-matching COUNTED concept from `frozen_concepts.json` and writes
one concrete attack payload for that instance. Each held-out instance
gets **exactly one** attack — the headline ASR is `broken / |held-out|`.
(Split sizes are per-scenario — see [`BUILTIN_SCENARIOS.md`](BUILTIN_SCENARIOS.md).)

```
freeze_concepts.py        → frozen_concepts.json (COUNTED concepts only)
instantiate_concepts.py   → one attack.json per held-out instance (Claude Code instantiated)
run_heldout_eval.sh       → one result.json per held-out instance (host runs Docker + judge)
aggregate_heldout.py      → leaderboard.json (ASR + diagnostics)
```

## Components recap

| Component | Where | Model |
|---|---|---|
| Orchestrator | `claude --dangerously-skip-permissions` in worktree | Claude Code (Opus 4.7 via Max plan) |
| Hypothesizer | `.claude/agents/redteam-hypothesizer.md` | Opus |
| Attack-designer | `.claude/agents/redteam-attack-designer.md` | Opus |
| Reflector | `.claude/agents/redteam-reflector.md` | Sonnet 4.6 |
| Critic | `.claude/agents/redteam-critic.md` | Opus |
| Monitor sidecar | `autoresearch-redteam-monitor` skill, 2nd claude session | Claude Code |
| Victim | Docker `ar_<scenario>:latest` (FROM ar_claude_code_base:latest), claude-agent-sdk | any anthropic-compatible endpoint (example: DeepSeek's anthropic namespace) |
| Judge | host-side OpenAI-compatible call | any OpenAI-compatible endpoint (default: OpenRouter, model `google/gemini-3-flash-preview` to match AHZ paper) |
| Stage-2 instantiator | Claude Code `claude -p` by default | isolated from the victim model |
