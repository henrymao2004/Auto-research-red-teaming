<h2 align="center">Agent Hacks Agents</h2>
<p align="center"><b>AHA — Autoresearch Discovers Vulnerabilities in Production Agents</b></p>

<p align="center">
  <img src="assets/aha_overview.png" width="100%" alt="AHA pipeline: scenario and victim setup, Stage-1 falsifiable autoresearch discovery, and Stage-2 held-out evaluation">
</p>

<p align="center">
  <a href="https://arxiv.org/abs/2607.11698"><img src="https://img.shields.io/badge/Paper-arXiv%3A2607.11698-b31b1b?style=flat&logo=arxiv&logoColor=white" alt="Paper"></a> ·
  <a href="https://henrymao2004.github.io/Auto-research-red-teaming/"><img src="https://img.shields.io/badge/Website-live-ea7278?style=flat&logo=githubpages&logoColor=white" alt="Website"></a> ·
  <a href="https://henrymao2004.github.io/Auto-research-red-teaming/#wall"><img src="https://img.shields.io/badge/Casebook-browse-ea7278?style=flat" alt="Casebook"></a> ·
  <a href="AGENT.md"><img src="https://img.shields.io/badge/AI%20Agents-AGENT.md-4B2E83?style=flat&logo=readthedocs&logoColor=white" alt="AGENT.md"></a> ·
  <a href="docs/USAGE.md"><img src="https://img.shields.io/badge/Docs-Usage-4c8c11?style=flat" alt="Docs"></a> ·
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-informational?style=flat" alt="License"></a>
</p>

<p align="center"><i>🤖 Autonomous red-team research that turns a production agent's own failures into reusable vulnerability concepts.</i></p>

> [!CAUTION]
> **Research use.** AHA is a red-team harness — it stores harmful prompts and
> attack payloads and drives real actions inside sandboxed victims. Run it only
> against systems you own or are authorized to test. See [`SECURITY.md`](SECURITY.md).

> 🤖 **AI agents:** read [`AGENT.md`](AGENT.md) instead — structured for LLM
> consumption, not human browsing.

AHA turns production-agent red-teaming into **autoresearch**: a Researcher
iterates — hypothesize an attack, run it against a Docker-sandboxed victim
agent, judge the trajectory, reflect — and accumulates a persistent
**Vulnerability Concept Graph (VCG)** of *why* a family of attacks works,
*when* it fails, and *how* to reinstantiate it. Stage-2 held-out evaluation
then reports Attack Success Rate (ASR) on unseen tasks.

The Researcher plugin, the victim agent, and the scenario are each a
registry-discovered plugin (every scenario is a single `contract.yaml`), so
you can red-team coding agents, tool-using agents, or prompt-injection
environments — or import your own benchmark — without rewriting the loop.

Findings, figures, and the interactive casebook live on the
**[project website](https://henrymao2004.github.io/Auto-research-red-teaming/)**.

## 📢 Latest updates

- **2026-09-21** — Docs and website aligned with the paper.
- **2026-07-13** — 📄 Paper on arXiv: [arXiv:2607.11698](https://arxiv.org/abs/2607.11698).
- **2026-07-07** — 🎉 Initial public release.

## 🏗️ How it works

The pipeline above runs in two stages:

1. **Stage 1 — autonomous discovery.** A `/loop`-driven Researcher
   dispatches role-specialized sub-agents each iteration — Hypothesizer
   (commits a *falsifier* before seeing the attack), Attack-Designer,
   Reflector, and a periodic Critic (every 10 completed iterations) —
   writing a fully inspectable `attacks/<run>/v<N>/` folder and promoting
   only replicated, non-falsified breaks into the VCG. A sidecar monitor
   halts the loop on 10 stop signals. All four sub-agents inherit the
   research model.
2. **Stage 2 — held-out evaluation.** `/concept-eval` freezes the counted
   concepts, instantiates each once against an unseen split (via a sandboxed
   `claude -p` isolated from the victim), and reports headline
   **ASR = broken / |held-out|**.

The **variables of an experiment** — three registry-discovered plugin axes and
two runtime model params, fully isolated from one another:

| Variable | What it is | Chosen by |
|---|---|---|
| **researcher plugin** | sub-agent roster the Researcher dispatches | `--researcher` (default `default`; `codex` ships) |
| **research model** | LLM the Researcher and its four sub-agents run on | `--researcher-model-local` / `--researcher-model` |
| **victim agent** | the harness **under attack** | `--victim` (default `claude_code`) |
| **victim model** | the LLM the victim runs on — the target | `--model` (**mandatory**) |
| **scenario** | task suite + attack family + judge | `--scenario` (default `agenthazard`) |

Full flag reference and the multi-agent architecture diagram are
in [`docs/USAGE.md`](docs/USAGE.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## 🚀 Quick start

Five steps: install, setup, build image, launch, evaluate — full walkthrough in
[`docs/QUICKSTART.md`](docs/QUICKSTART.md), provider setup in
[`docs/MODELS.md`](docs/MODELS.md).

| Step | Command |
|---|---|
| Install | `git clone https://github.com/henrymao2004/Auto-research-red-teaming.git && cd Auto-research-red-teaming && uv venv && source .venv/bin/activate && uv pip install -e .` |
| Setup | Run `/setup`, or copy `templates/model-config/minimal.env` to `.env` (see [`SETUP_GUIDE.md`](SETUP_GUIDE.md)). |
| Build image | `bash autoresearcher/scripts/build_base_image.sh && bash autoresearcher/scripts/build_scenario_image.sh agenthazard` |
| Launch | `cd autoresearcher && ./scripts/launch_run.sh ah_run --victim claude_code --scenario agenthazard --model <victim-model> 'break <victim-model> on AgentHazard'` |
| Evaluate | In the spawned session: `/loop /autoresearch-redteam-discovery ah_run break <victim-model> on AgentHazard`; after stop, `/concept-eval ah_run`. |

**5-minute dry run** (no Docker, no keys — validates the install path):

```bash
bash autoresearcher/scripts/dry_run.sh
bash autoresearcher/scripts/doctor.sh
```

Everyday launch reference: [`docs/USAGE.md`](docs/USAGE.md).

## 📚 Documentation

| Doc | Contents |
|---|---|
| [`docs/USAGE.md`](docs/USAGE.md) | **Operator reference** — full flags, Stage 1/2 tables, architecture diagram, endpoints |
| [`docs/QUICKSTART.md`](docs/QUICKSTART.md) | First-run walkthrough: cold start to held-out ASR |
| [`docs/DRY_RUN.md`](docs/DRY_RUN.md) | Offline 5-minute smoke test |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Multi-agent pipeline, run artifacts, model slots, isolation boundaries |
| [`docs/PLUGINS.md`](docs/PLUGINS.md) | Plugin layout + runtime registry (all three axes) |
| [`docs/BYO_SCENARIO.md`](docs/BYO_SCENARIO.md) | Bring-your-own scenario (build / import / hand-author) |
| [`docs/MODELS.md`](docs/MODELS.md) | Provider / format / key per model slot |
| [`docs/DOCKER.md`](docs/DOCKER.md) | Victim sandbox image and customization |
| [`docs/PERMISSIONS.md`](docs/PERMISSIONS.md) | Claude Code permission model, autonomous-agent standard |
| [`docs/BUILTIN_SCENARIOS.md`](docs/BUILTIN_SCENARIOS.md) | Shipped scenarios (AgentHazard + AgentDyn + DTap): splits, schemas, attack families |
| [`SETUP_GUIDE.md`](SETUP_GUIDE.md) · [`SECURITY.md`](SECURITY.md) · [`CONTRIBUTING.md`](CONTRIBUTING.md) · [`CHANGELOG.md`](CHANGELOG.md) | Setup, security posture, contribution, release notes |

## 📋 Status

Current release: **v0.1.0** ([`CHANGELOG.md`](CHANGELOG.md)).
Shipped victims (`claude_code`, `codex`) and scenarios (`agenthazard`,
`agentdyn`, `dtagent`) are registry-discovered plugins; `run_attack --list` is
the source of truth for the launch matrix.

## Citation

```bibtex
@online{2607.11698,
  author = {Xutao Mao and Rui Qian and Xiang Zheng and Cong Wang},
  title = {Agent Hacks Agents: Autoresearch Discovers Vulnerabilities in Production Agents},
  year = {2026},
  eprint = {2607.11698},
  eprinttype = {arXiv},
}
```

## 🙏 Acknowledgements

- [AgentHazard](https://github.com/Yunhao-Feng/AgentHazard) for the bundled scenario data.
- [AgentDojo](https://agentdojo.spylab.ai/) for the indirect-prompt-injection paradigm.
- [DecodingTrust-Agent (DTap)](https://github.com/AI-secure/DecodingTrust-Agent.git) for the `dtagent` scenario data.
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code), [`claude-agent-sdk`](https://github.com/anthropics/claude-agent-sdk-python), [Codex CLI](https://github.com/openai/codex), and [OpenRouter](https://openrouter.ai) for the runtime stack.
- [Auto-claude-code-research-in-sleep](https://github.com/wanshuiyin/Auto-claude-code-research-in-sleep/tree/main) for inspiration on the README organization.

## License

MIT — see [`LICENSE`](LICENSE).
