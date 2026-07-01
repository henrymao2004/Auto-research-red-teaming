# Models & API config — pick any provider / format / key

This is the one page for "how do I point each model slot at the provider and
key I want." There are **three primary model slots** plus one generation
endpoint, split into **two config lanes**:

| Slot | What it is | Lane |
|---|---|---|
| **victim model** (`--model`) | the LLM the victim AGENT (claude_code / codex) runs on | **A — agent backbone** |
| **research model** (`--researcher-model`) | the LLM the researcher AGENT runs on | **A — agent backbone** |
| **judge model** (`JUDGE_*`) | scores each attack (plain API call, not an agent) | **B — env** |
| **instance generator** (`ROUTER_*` endpoint + `GENERATOR_MODEL`) | synthesizes `/scenario-build` instances (plain API call) | **B — env** |

The victim/research backbones are **agent CLIs** (claude / codex). The judge and
instance generator are **plain API calls**. Stage 2 uses Claude Code
(`claude -p`) as the held-out instantiator, not an env model slot.

---

## Lane A — agent backbones (victim + researcher)

How an agent reaches its model depends on **which backbone** it is. The split is
about the wire protocol each CLI speaks:

- **claude_code → direct.** Claude Code speaks the Anthropic **Messages API**
  (`/v1/messages`), which providers serve on an Anthropic-compatible endpoint
  (e.g. `https://api.deepseek.com/anthropic`, `https://api.minimaxi.com/anthropic`).
  So claude_code talks **straight to the provider — no proxy**. Point its base
  URL at the endpoint and set the matching key.
- **codex → Moon Bridge.** Codex speaks the OpenAI **Responses API**
  (`/v1/responses`), which DeepSeek / OpenRouter don't serve (DeepSeek official
  → 404, OpenRouter → 500 with tools), so codex can't talk to them directly.
  [Moon Bridge](https://github.com/ZhiYi-R/moon-bridge) is a local
  protocol-translation proxy; its **Transform** mode (`:38440`) translates
  Responses → the upstream you pick.

The split applies to **both roles** by backbone type: a claude_code victim or a
claude researcher goes direct; a codex victim or a codex researcher goes through
Moon Bridge.

### claude_code — direct endpoint

No proxy to run. Set the base URL + key for whichever slot:

| Agent | Base-URL env | Key env |
|---|---|---|
| claude_code victim | `VICTIM_BASE_URL` → `ANTHROPIC_BASE_URL` in the container | `VICTIM_API_KEY` |
| claude researcher (on host) | `RESEARCHER_BASE_URL` (unset = host's logged-in `claude`) | scoped per `claude` line |

```bash
# example: DeepSeek's Anthropic-compatible endpoint
VICTIM_BASE_URL=https://api.deepseek.com/anthropic
VICTIM_API_KEY=sk-...
# or MiniMax:  VICTIM_BASE_URL=https://api.minimaxi.com/anthropic
```

`--model` is forwarded verbatim to that endpoint (e.g. `deepseek-v4-pro`). To
move a backbone to a different provider, change the base URL + key — there is no
config file to rebuild.

### codex — Moon Bridge

Declare your providers + keys + model aliases **once** in `config.yml`, and Moon
Bridge translates codex's Responses calls to whatever upstream you picked.

```bash
# 1. Copy the template and fill in your provider key(s) + model aliases.
cp templates/moonbridge/config.example.yml templates/moonbridge/config.yml
$EDITOR templates/moonbridge/config.yml      # set api_key, pick provider/format

# 2. Build + start the Transform ingress (codex :38440).
bash autoresearcher/scripts/moonbridge.sh all
#   -> ar_moonbridge_responses (Transform, :38440) for codex
bash autoresearcher/scripts/moonbridge.sh status     # health + model list
```

In `config.yml`, each `providers:` entry is one upstream — set its `base_url`
(provider's OpenAI-compatible endpoint), `api_key`, and `protocol`
(`openai-chat` / `openai-response` / `google-genai`). Each `models:` alias is a
name you pass as `--model`.

```yaml
providers:
  deepseek:
    base_url: "https://api.deepseek.com/v1"
    api_key:  "sk-..."
    offers: [ { model: deepseek-v4-pro } ]
models:
  deepseek-v4-pro: { context_window: 1000000, max_output_tokens: 8192 }
```

### How the harness points at it

| Agent | Endpoint | Override |
|---|---|---|
| claude_code victim | `ANTHROPIC_BASE_URL` = the provider's Anthropic endpoint | `VICTIM_BASE_URL` |
| claude researcher (on host) | host's logged-in `claude`, or a direct Anthropic endpoint | `RESEARCHER_BASE_URL` |
| codex victim | `http://host.docker.internal:38440/v1` (Moon Bridge Transform) | `CODEX_RESPONSES_BASE_URL` |
| codex researcher (on host) | `http://localhost:38440` (Moon Bridge Transform) | `CODEX_RESPONSES_BASE_URL` |

`--model` is the model name (claude_code) or the `config.yml` alias (codex).

---

## Lane B — judge + generator through env (plain API)

The judge and scenario instance generator are **not agents** — they're
OpenAI-compatible chat-completions calls. Set any OpenAI-compatible `base_url`
+ key (OpenRouter, official, a local gateway, …):

```bash
JUDGE_BASE_URL=...   JUDGE_API_KEY=...   JUDGE_MODEL=...
ROUTER_BASE_URL=...  ROUTER_API_KEY=...  GENERATOR_MODEL=...
```

`/setup` walks you through both lanes (claude_code endpoints / Moon Bridge for
codex + these env vars) and writes `.env`; `launch_run.sh` auto-sources it.

---

## TL;DR

- **claude_code agents (victim + researcher)** → **direct** to a provider's
  Anthropic-compatible endpoint (`VICTIM_BASE_URL` / `RESEARCHER_BASE_URL`,
  e.g. `https://api.deepseek.com/anthropic`). No proxy.
- **codex agents (victim + researcher)** → **Moon Bridge** `config.yml`
  (`moonbridge.sh all`), because codex's Responses API isn't served by the
  providers directly.
- **Judge + generator** → env (`JUDGE_*` / `ROUTER_*` + `GENERATOR_MODEL`),
  any OpenAI-compatible endpoint, via `/setup`.
