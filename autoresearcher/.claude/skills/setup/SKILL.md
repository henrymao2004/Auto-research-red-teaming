---
name: setup
description: Configure the LLM endpoints (victim / judge / generator) plus the optional researcher backbone in one guided, validated pass. Asks a few plain-language questions (or takes one key for everything), pings each endpoint, and writes .env at the repo root. Run this once before launching a run; launch_run.sh and every skill read .env afterwards.
argument-hint: "(no args — interactive)"
---

# Setup — configure the LLM endpoints

One guided pass that writes `.env` at the repo root. After this, nothing
else asks you for keys — `launch_run.sh`, `/scenario-build`,
`/concept-eval` all read `.env`.

There are **two config lanes** — that's the whole mental model. The full
reference is [`docs/MODELS.md`](../../../docs/MODELS.md); this skill just
fills it in interactively.

| Lane | Slots | How |
|---|---|---|
| **A — agents** | **victim model** (`--model`) + **research model** (`--researcher-model`), each on claude_code OR codex | claude_code → **direct** endpoint; codex → **Moon Bridge** (`templates/moonbridge/config.yml` + `moonbridge.sh`) |
| **B — env** | **judge model** + **generator model** (plain API calls, not agents) | `.env` (`JUDGE_*`, `ROUTER_*`, `GENERATOR_MODEL`) |

Why two lanes: the victim/research backbones are **agent CLIs** (claude /
codex). A **claude_code** backbone speaks the Anthropic **Messages** API and
reaches its upstream **directly** (`ANTHROPIC_BASE_URL` + key — Anthropic,
OpenRouter's anthropic endpoint, or any anthropic-compat provider); no proxy.
A **codex** backbone needs the OpenAI **Responses** API, which
DeepSeek/OpenRouter don't serve directly — so codex routes through **Moon
Bridge**, a local proxy that translates Responses → the provider/format/key you
pick in one `config.yml`. The judge + generator are **plain chat-completions
calls** (not agents); Moon Bridge doesn't expose `/chat/completions`, so they
stay on env.

Ask every question in plain language: a one-line headline, 1–3 concrete
"for example…" choices, a recommended default with "if you're not sure,
pick this", and reassurance ("you can re-run /setup anytime").

Put the variable name only as a trailing aside, never in the headline.

## Step 1 — Locate `.env`

```bash
REPO=$(cd "$(dirname "$(uv run python -c 'import autoresearch_redteam,os;print(os.path.dirname(autoresearch_redteam.__file__))')")/../.." && pwd) 2>/dev/null || REPO=$(git rev-parse --show-toplevel)
ENV="$REPO/.env"
[ -f "$ENV" ] && echo "found existing $ENV (will back up to .env.bak before writing)"
```

If `.env` already exists, say what's already set (key masked) and ask via
`AskUserQuestion`: **reconfigure everything / fix just one lane / leave it**.

## Step 2 — Lane A: agents (victim + researcher)

The victim and researcher backbones run on whatever provider/format the user
picks. How the key is wired depends on the backbone — claude_code is direct,
codex goes through Moon Bridge:

1. `AskUserQuestion` — **which provider + format issued your key?**
   > "Which service is your model key for? For example: DeepSeek official
   > (Anthropic-format), OpenRouter (one key, most models), OpenAI official,
   > or Anthropic. If unsure, DeepSeek or OpenRouter are the most flexible."
   - deepseek · openrouter · openai · anthropic
2. Ask for the **key** (free text). Ask the **model alias** (default per
   provider, e.g. `deepseek-v4-pro`).
3. Wire it for the chosen backbone:
   - **claude_code → direct.** Point `ANTHROPIC_BASE_URL` + key straight at the
     provider (Anthropic, OpenRouter's anthropic endpoint
     `https://openrouter.ai/api`, or any anthropic-compat provider). No proxy.
   - **codex → Moon Bridge.** Codex needs Responses translation, so write the
     Moon Bridge config + start its ingress:
     ```bash
     cp "$REPO/templates/moonbridge/config.example.yml" "$REPO/templates/moonbridge/config.yml"
     # fill providers.<name>.api_key for the codex (Responses) upstream
     bash "$REPO/autoresearcher/scripts/moonbridge.sh" all      # build + start the Responses ingress
     bash "$REPO/autoresearcher/scripts/moonbridge.sh" status   # verify /v1/models lists the alias
     ```
4. Harness defaults: a **claude_code** agent reads `ANTHROPIC_BASE_URL` (the
   direct upstream); a **codex** agent points at Moon Bridge
   (`host.docker.internal:38440/v1`). See [`docs/MODELS.md`](../../../docs/MODELS.md).

> Local-claude shortcut: if the user just wants the researcher on their
> logged-in `claude` for now, leave `RESEARCHER_*` unset — it uses the host's
> `claude` auth directly.

## Step 3 — Lane B: judge + generator via env

These are plain OpenAI-compatible chat calls (NOT agents, NOT through Moon
Bridge). For each of **judge** and **generator**, ask a small group:

- **Which base URL?** examples: `https://openrouter.ai/api/v1`,
  `https://api.openai.com/v1`, or a local proxy. "If unsure, the example shown
  is the usual pick."
- **The key** (free text) and **the model** (default pre-filled, e.g. judge
  `google/gemini-3-flash-preview`, generator `gpt-5`).

Record `JUDGE_BASE_URL` / `JUDGE_API_KEY` / `JUDGE_MODEL`, plus
`ROUTER_BASE_URL` / `ROUTER_API_KEY` / `GENERATOR_MODEL`.

## Step 3C — Researcher backbone (optional 4th slot)

After the three required slots, ask once via `AskUserQuestion`:

> "Do you want the researcher agent (the orchestrator + its sub-agents
> that *design* the attacks) to run on a specific model, or just use
> the `claude` you're already logged in with? For example, you can run
> the whole research loop on an OpenRouter model like
> `qwen/qwen3.7-max`. If you're not sure, pick 'use my logged-in
> claude' — you can set this later."

- **Use my logged-in claude** → write nothing for this slot (the
  default; the researcher uses the host's `claude` auth).
- **Run on a specific model** → ask the **model slug** (e.g.
  `qwen/qwen3.7-max`, `anthropic/claude-opus-4`) and the **key**
  (default the base URL to OpenRouter's anthropic endpoint
  `https://openrouter.ai/api`; a custom base URL is accepted if they
  have one). Reassure: "this points the orchestrator `claude` at that
  model — the same OpenRouter recipe as the victim."

Make clear the recipes, the same as for the victim:
- **Claude Code backbone** (default researcher) → OpenRouter's
  *Anthropic* endpoint `https://openrouter.ai/api` (returns
  Anthropic-format blocks even for non-Anthropic models).
- **Codex backbone** → OpenRouter's *OpenAI* endpoint (base `https://openrouter.ai/api/v1`,
  chat-completions; configured via the host's codex config, not these
  `RESEARCHER_*` vars).

Record `RESEARCHER_MODEL` / `RESEARCHER_BASE_URL` / `RESEARCHER_API_KEY`
only if they chose a specific model. Note: `launch_run.sh` keeps the
researcher and victim backbones fully isolated — it sets the
researcher's `ANTHROPIC_*` only on the orchestrator `claude` line, never
exported, so the victim eval never inherits it.

## Step 4 — Validate each endpoint (a quick ping)

Before writing, check each configured slot actually answers. Non-blocking
— report OK/FAIL, and on FAIL let the user re-enter or keep anyway.

```bash
# OpenAI-compatible slots (judge, generator): list models is cheap, no tokens.
ping_openai() {  # $1=url $2=key
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
         "${1%/}/models" -H "Authorization: Bearer $2")
  [ "$code" = "200" ] && echo OK || echo "HTTP $code"
}
# Anthropic slot (victim): a 1-token message is the cheapest real check.
ping_anthropic() {  # $1=url $2=key $3=model
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 \
         "${1%/}/v1/messages" \
         -H "x-api-key: $2" -H "anthropic-version: 2023-06-01" \
         -H "content-type: application/json" \
         -d "{\"model\":\"$3\",\"max_tokens\":1,\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}]}")
  { [ "$code" = "200" ] || [ "$code" = "400" ]; } && echo OK || echo "HTTP $code"
}
```

(For the victim's anthropic-compat proxies, both `x-api-key` and
`Authorization: Bearer` are seen in the wild — if `x-api-key` returns
401, retry the ping with `-H "Authorization: Bearer $key"`. A 400 is
fine: it means the endpoint + key are valid and only the tiny test body
was rejected.)

If a researcher backbone was configured (Step 3C), ping it too with
`ping_anthropic` (it's an Anthropic-protocol endpoint, like the victim).

Report a line per configured slot, e.g.
`victim → OK · judge → OK · generator → HTTP 401 · researcher → OK`.

## Step 5 — Write `.env`

Back up first, then write the canonical vars (only the slots configured
this run; leave others as they were):

```bash
[ -f "$ENV" ] && cp "$ENV" "$ENV.bak" && echo "backed up to $ENV.bak"
```

One-key mode writes `UNIFIED_API_KEY` + `UNIFIED_PROVIDER` plus
`VICTIM_MODEL`, `JUDGE_MODEL`, and `GENERATOR_MODEL`. Per-slot mode writes
victim and judge endpoint/model vars plus
`ROUTER_BASE_URL` / `ROUTER_API_KEY` / `GENERATOR_MODEL`. If a researcher
backbone was chosen (Step 3C), also write
`RESEARCHER_MODEL` / `RESEARCHER_BASE_URL` / `RESEARCHER_API_KEY`
(otherwise leave them commented/absent so the researcher uses host
`claude` auth). Match `.env.example`'s layout + comments.

## Step 6 — Show the resolved config

Print the slot table back (keys masked to the last 4) so the user sees
exactly what's set:

```
victim     → <url>   model=<model>   key …abcd
judge      → <url>   model=<model>   key …wxyz
generator  → <url>   model=<model>   key …1234
researcher → <url>   model=<model>   key …5678   (or: host default claude auth)
```

Then: "Done — `launch_run.sh` and every skill read this now. Re-run
`/setup` anytime to change it." Do NOT print full keys. Do NOT commit
`.env` (it's gitignored).
