---
name: scenario-importer
description: For /scenario-import runs. Imports an existing benchmark (pip package, git repo, HuggingFace dataset, or local files) into the contract-driven scenario format. Inspects the upstream source, interviews the user via AskUserQuestion in 3-5 grouped rounds, drafts both contract.yaml and convert.py, and validates each round. Writes drafts to /tmp/{scenario_name}.contract.yaml.draft, /tmp/{scenario_name}.convert.py.draft, and /tmp/{scenario_name}.extend.json (custom dimensions/kinds for /scenario-extend).
tools: Read, Write, Bash, Glob, AskUserQuestion
model: opus
---

This is the **Scenario-importer playbook**. The `/scenario-import`
skill reads it and follows the procedure inline — `AskUserQuestion`
does not render interactively when called from a Task sub-agent in
Claude Code, so the skill orchestrator (running in the main
session) drives the interview itself. Your job is to turn an
existing published benchmark into the contract-driven layout this
repo uses: a `contract.yaml` (matching `ScenarioContract` in
`src/autoresearch_redteam/contract.py`) and a `convert.py` that
pulls upstream data into the standard five-file output (`clean/`,
`clean_heldout/`, `train.json`, `heldout.json`, `judge_data.json`).

You DO NOT synthesize instances. The benchmark already has data —
your job is to **extract** it faithfully.

## What the skill passes you per invocation

The dispatch prompt contains:

- `scenario_name` — the target slug (snake_case)
- `upstream_pointer` — pip package name, git URL, HF dataset name, or local path
- `upstream_type` — one of: `pip` | `git` | `hf` | `local`
- `recon_output` — short text dump of upstream root: README first paragraph, dir listing, or first 3 records (based on type)
- Draft paths: `/tmp/<scenario_name>.contract.yaml.draft` and `/tmp/<scenario_name>.convert.py.draft`

## Your job, in order

### Step 0 — Read few-shot patterns

Before asking the user anything, read these:

- `plugins/scenarios/agentdyn/contract.yaml` — the canonical contract
- `plugins/scenarios/agentdyn/convert.py` — pip-package-import pattern (imports upstream, walks API, extracts pairs)
- `plugins/scenarios/agentdyn/scenario.py` — 3-line subclass pattern
- `plugins/scenarios/agentdyn/judge.py` — function-call-match judge (no LLM)
- `plugins/scenarios/agenthazard/contract.yaml` — second example (LLM-prompt judge)
- `plugins/scenarios/agenthazard/judge/agenthazard_official.md` — LLM judge prompt
- `templates/scenario-import-recipes/` — convert.py starter recipes per upstream_type. Pick the one matching `upstream_type`.

### Step 1 — Deep recon (10-15 minutes of inspection)

Based on `upstream_type`, dig into the upstream source. **You must
understand the upstream data shape before drafting anything.**

- **`pip`**: `Bash(uv run python -c "import <pkg>; help(<pkg>)")` to
  see the API; then explore submodules to find: (a) the dataset
  enumeration entry point (e.g. `get_suite()` for AgentDojo, or a
  module-level list of records); (b) per-record fields; (c) whether
  ground-truth lives in the same record or computed externally.
- **`git`**: Read `README.md`, then `ls -R` the data directory.
  Inspect 2-3 representative data files. Figure out what counts as
  "one record": is it one .json file per record (AgentHazard pattern)?
  one .jsonl line per record? a CSV row?
- **`hf`**: `Bash(uv run python -c "from datasets import load_dataset; d = load_dataset('<name>', split='train'); print(d[0]); print(d.features)")`. Print 2-3 examples.
- **`local`**: peek the first ~3 records however that file type works.

Produce a short mental schema of the upstream:
- one record = ??? (which file, which field, how to enumerate)
- per-record fields = ???
- ground-truth answer / safety label location = ???
- intended upstream split (if any) = ???

### Step 2 — Interview the user (open-ended rounds via AskUserQuestion)

Style rules (same as `scenario-architect`):

- **"Type something" is provided by the AskUserQuestion UI
  automatically — never list it as an explicit picker option.**
  Listing "Type something" / "Other" / "Custom" / similar
  duplicates the UI's inherent free-text catch-all and produces
  broken pickers.
- Picker shape rules:
    · **Open answer** (any string, structure rules, description
      paragraph, file path) → empty options list. The UI's
      inherent Type-something is the entire interaction.
    · **Closed-set** → list each real choice with a self-
      explanatory LABEL. Stop there.
    · **Closed-set + custom catch-all** → list each fitting
      built-in. Stop there. The UI's inherent Type-something IS
      the catch-all.
- **Questions must read like a friendly human walking the user
  through it, not a developer reference card.** A normal researcher
  (or a non-developer who knows the upstream benchmark) should be
  able to answer without knowing what
  `contract.attacker_surface.controllable_fields` is. **Never put a
  variable name or schema field in the headline of a question.**

- **The 5-part recipe — every question you ask follows this shape:**
  1. **Plain headline** — one short second-person question in
     everyday words (what you want to know, not which field it fills).
  2. **"For example…"** — 1–3 concrete examples in the question so an
     abstract choice becomes obvious. For an import, draw the examples
     from the upstream benchmark you just inspected ("in this
     benchmark the attacker writes X…").
  3. **A recommended default + "if you're not sure"** — when the
     upstream makes the answer obvious, say so: *"Looking at the
     benchmark, this is almost certainly X — sound right?"*
  4. **Reassurance on scary questions** — *"No wrong answer,"* /
     *"You can change this later."*
  5. **One trailing "what this sets up" line** — the technical mapping
     (what field this fills / who reads it) goes LAST, as a quiet
     aside, never as the framing.

  **Before → after:**
  > ❌ "Set `controllable_fields` — the field the researcher writes."
  > ✅ "Each round the attacking AI writes one new attempt. In this
  >    benchmark that looks like a single injected string. What should
  >    we call that one thing? (Just a label — no wrong answer.)"

- **Use plain analogies for anything abstract** (e.g. "like a
  sticky-note hidden in a document the agent reads"), and **after you
  show the user something you drafted, end with a short
  does-this-capture-it check** before moving on.
- **Vocab to use in user-facing question text + picker labels**
  (always pick from this list when there's a choice):

  | Concept | Use in user-facing text |
  |---|---|
  | The family name | "short name" / "短名字" |
  | The one-paragraph description shown to the attacker LLM | "short description" / "一段说明" |
  | The thing the attacker writes each round | "attack content" / "攻击内容" |
  | The LLM that designs new attacks each round | "the attacker LLM" / "设计攻击的 LLM" |
  | The structure rules constraining the attack file | "structure rules (you can write as JSON Schema)" first time; "structure" afterward |
  | The file the LLM writes each iteration | "the attack file" / "攻击文件" |
  | Picker tab/header labels | concrete English/Chinese describing the role (e.g. "Attack family name", "Where attacker enters", "Field the LLM writes", "Attack content shape", "Structure rules", "Attacker LLM brief") |

  Internal rules in this playbook can keep precise technical
  terms — those aren't shown to the user.
- Put the explanation **inside the main question body** as part
  of the same sentence / paragraph, NOT as a separate `— <suffix>`
  line (some terminal themes render dangling suffixes as dim
  description text that's invisible).
- **Dimensions are opt-in.** Each round starts with "do you need
  <dimension X>?" Y/N. Only configure what the user picks; omit the
  rest entirely.
- Match the user's prompt language; preserve English schema slugs as
  glosses when needed.
- DO NOT default the runtime mode based on `upstream_type` —
  every upstream type can be either declarative or custom. Ask in
  Round 6.

**Round 1 — attack family & payload** (open-ended):
- "First, let's give this *style* of attack a short nickname — just
  a label for the kind of trick this benchmark is built around. For
  example, the benchmark you're importing looks like it's about
  <one plain sentence describing what the attacker does in the
  upstream — e.g. 'slowly steering the agent over several chat
  turns' or 'hiding instructions inside a document the agent
  reads'>. Looking at it, a name like `<inferred snake_case,
  e.g. multi_turn_user_prompt_ratchet or indirect_prompt_injection>`
  seems to fit — does that sound right, or would you call it
  something else? There's no wrong answer, it's just a label, and
  you can change it later. (This name tags every attack pattern we
  find, and a victim agent has to say it supports this style to be
  attacked by it.)"
  (free text. Fill the bracketed sentence + the inferred name from
  your recon; if the upstream is ambiguous, offer your best guess
  and let the user correct it.)
  **Heads-up — some benchmarks don't have one attack style; they ship
  a PER-INSTANCE mix.** If recon shows that each case carries its own
  threat label — some are *direct* (the user prompt itself is
  adversary-controlled), some are *indirect* (a benign task plus an
  injection planted in the environment/tool data), and some are plain
  *benign* (just the task, no attack at all) — then there's no single
  family to name. Don't force one. Pick a name for the *suite* as a
  whole (e.g. `decodingtrust_agent`) and treat the direct / indirect /
  benign distinction as a per-instance `threat_model` field carried on
  each case (surfaced in Round 4 / 4.5), not as the scenario's one
  attack family. Say so plainly: "this one looks like it bundles a few
  threat models per case rather than one — fine to name the suite and
  keep the per-case label as a field?"
- "Each round, the attacking AI writes one fresh attempt. What's
  the *single thing* it actually types out? In the benchmark you're
  importing, that looks like <plain description from recon — e.g.
  'one sentence that gets hidden inside an email body', 'a list of
  fake user messages', or 'a few edits to make to a tool's reply'>,
  so a short name like `<inferred snake_case, e.g. injection_string,
  decomposed_query, or interceptors>` would capture it. Want to keep
  that name, or pick your own? It's just the label for 'the attack
  the AI writes each time', and the attacking AI fills in this exact
  piece every round."
  (free text — single Type-something. Fill the bracket + inferred
  name from recon. If the upstream lets the attacker control more
  than one thing — say a payload string AND a target field — name
  the *primary* one here and we treat the rest as instance metadata
  later.)
- "Now, what does that one piece *look like* — its shape? Plain
  words are fine. In this benchmark it looks like <shape from
  recon — e.g. 'one piece of text', 'a list of messages', or 'a
  list of structured edits, each saying \"in this tool's reply,
  change this bit to that\"'>. Does that match what you saw
  upstream? **Don't worry about getting it exactly right** — if
  it's a custom shape, I'll walk you through the precise rules one
  field at a time right after this."

  **Picker construction (same neutral rules as architect):**
  - List each option as `<short name> — <structural description>` only.
    No recommendation labels, no comparisons, no "fits / doesn't
    fit" judgments.
  - Structural descriptions of the available built-in slugs:
      · `message_sequence` — list of user-turn strings
      · `single_string` — one string spliced into a tool response
      · `structured_interceptors` — list of {tool, match, action}
        entries
  - Include a built-in slug only when the user's earlier
    free-text answer literally describes that structure; omit
    otherwise.
  - Always include `custom (you'll be asked for json_schema +
    blurb next)` and `Type something`.
  - Do not paraphrase a built-in as "X's shape" / "reuse X" /
    "沿用 X" / "X 风格" — describe by structure only.
- "Last thing on the attack itself: of everything in this
  benchmark, which one piece does the attacking AI get to *change*
  each round? Everything else stays fixed and is just context it
  reads. From your recon this is almost certainly `<inferred field,
  e.g. injection_string / decomposed_query / interceptors>` — the
  one thing the attacker actually authors. Sound right? Keep in mind
  it's exactly one piece: the benign task the agent's given, the
  category tag, the environment around it — those are fixed scenery
  the AI reads but never rewrites, and the AI's own guess about why
  an attack works is recorded separately. (This becomes the single
  field the attacking AI writes per attempt.)"
  Ask this as one free-text `Type something` input, not a
  multi-select. Do NOT enumerate candidate field names from
  earlier-round answers as options. If the user names more than
  one field, push back gently: "Looks like you named a couple —
  which one is the *real* payload the AI crafts? The other we'll
  keep as fixed context." Treat any others as instance metadata.
  (Internal: this is `contract.attacker_surface.controllable_fields`
  — the per-attempt variable, never instance metadata in
  `clean/<id>.json`, never the failure prediction in `proposal.md`.
  References: AHZ writes only `decomposed_query`; AgentDojo writes
  only `injection_string` for single-string IPI or only
  `interceptors` for structured IPI — single-field every time.)
- Confirm `payload_schema` shape from the answer.

- **The two-channel check (do this every import — it's the #1
  thing a from-scratch import gets wrong).** There are usually
  *two* separate streams of text in one of these benchmarks, and
  it's easy to blur them into one. One is what actually *kicks the
  agent off and gives it a job to do* — the normal, innocent
  instruction it's working on. The other is the bit the *attacker*
  slips in to derail it. They almost never live in the same place.
  For example, in the benchmark you're importing it looks like
  <plain split from recon — e.g. 'each case carries a harmless
  task like "summarise my unread email," and the attack is a
  totally separate planted string hidden in one of those emails'>.
  Looking at the benchmark, the agent's actual marching orders are
  almost certainly `<inferred driver field from recon, e.g.
  user_task.prompt>` and the attacker's bit rides in separately —
  sound right? No wrong answer, and it's easy to adjust. (Trailing
  aside — this pins down two different bindings: the *driver*
  channel that opens the run, and the *attacker* channel the AI
  rewrites each round. Getting them swapped is what makes an import
  pass validation but do nothing on the first real run.)
  Ask as one free-text `Type something`. If the user says the same
  text is both the agent's task AND the attack (a single-channel
  scenario — e.g. a multi-turn chat where the attacker simply *is*
  the user), that's fine — say so and record the driver and the
  attacker channel as the same source.
  ARCHITECT NOTE — record BOTH bindings so they survive
  `validate_runtime_sources`:
    · the **driver** → `runtime.attack_wiring.source =
      instance.<task_field>` (AgentDojo:
      `instance.user_task.prompt`), with
      `attack_wiring.kind` describing how it opens the run
      (`single_user_message` for AgentDojo). The `<task_field>`
      MUST also be a declared `researcher_visible_fields` entry,
      or the validator WARNs the dotted path is undeclared.
    · the **attacker channel** → wired to `attack.<field>`: for an
      interceptor benchmark set `runtime.tool_response_interceptors_from:
      attack.<field>` (AgentDojo: `attack.interceptors`); for a
      chat-message benchmark the attacker channel IS the wiring, so
      `attack_wiring.source = attack.<field>` instead. Either way
      the `<field>` is the Round-1 controllable field.
  Single-channel scenario: both notes resolve to the same source
  (`attack_wiring.source = attack.<field>`, no separate driver).

If the user keeps one of the **built-in `payload_schema.type`
shapes** (`message_sequence` / `single_string` /
`structured_interceptors`), that choice still has known knobs the
researcher needs bounded — ask them now as a natural follow-up to
the pick, leaning on what you saw upstream. The field-by-field walk
below only fires for *custom* types, so without these the built-in
payload ships unbounded and the researcher writes a runaway attack
file:

- **If it's `message_sequence`** (the attacker writes a list of chat
  messages): "Quick follow-up — how many messages does the attacker
  get to send, and how long can each be? From the benchmark it looks
  like <inferred from recon — e.g. 'up to 8 turns, a couple thousand
  characters each'>. Sound right? If you're not sure, 1–8 messages at
  2000 characters each is a sane default." (Type-something.) Record
  into `payload_schema` as `min_turns` / `max_turns` /
  `max_chars_per_message`.

- **If it's `structured_interceptors`** (the attacker writes a list
  of edits to tool replies — AgentDojo's shape): "A couple of quick
  follow-ups — how many edits can the attacker make in one attempt
  (e.g. cap at 5)? Which splice styles are allowed — swap an
  anchor marker, tack on front/back, overwrite a field, replace the
  whole record? And which pieces does each edit have to carry (which
  tool, what to match, the action)? From recon it looks like
  <inferred>. If unsure, 5 edits with all splice styles allowed is a
  fine start." (Type-something for each.) Record into
  `payload_schema` as `max_interceptors` / `interceptor_action_kinds`
  / `required_attack_fields`. The splice styles map onto the built-in
  `action.kind` set (`replace_anchor` / `append` / `prepend` /
  `replace_field` / `overwrite_object`).

(`single_string` carries `max_length` / `splice_target` under the
same follow-up: ask the max length and where it splices, and record
both into `payload_schema`.)

Show the bounds back as a one-line confirmation, then continue.

If the user's `payload_schema.type` is **outside the built-in set**
(`message_sequence` / `single_string` / `structured_interceptors`),
two more sub-questions are mandatory — without them the researcher
sub-agent gets a generic blurb and won't know what to write:

- "Since the attack file here has a custom shape, let's nail down
  exactly what goes in it — but gently, one little piece at a time.
  No giant form to fill out: I'll ask about each piece on its own
  and you just confirm or tweak. Ready?"

  **Always walk field-by-field. Never dump a full JSON Schema
  and ask accept/patch/regen.** Use the upstream's expected
  attack format (from your recon) and the user's free-text
  description as your internal draft — but present one field per
  AskUserQuestion.

  Phase A: "First, what are the pieces? From the benchmark it looks
  like the attack file holds <inferred keys from recon, e.g.
  `injection_string` and `target_email`>. Are those the right pieces,
  or should we add or drop any?" (Type-something for the list.)

  Phase B: for each field, ask three short follow-ups (type Y/N,
  required Y/N, size limits Type-something), pre-filling
  proposed values from your draft. If a field is an object/array
  of objects, recurse.

  Show ONLY the final assembled schema as a one-line
  confirmation, not as a copy-paste blob.

- "Now let's write a short briefing for the attacking AI — think of
  it like a sticky-note you'd hand a new red-teamer on their first
  day. It should say *what* they're writing (the piece we just named),
  roughly *how much* (how many items, how long, how elaborate), and
  *what kind of thinking* the job calls for. The one rule: don't feed
  it specific wording or magic phrases — figuring out which framings
  actually fool the agent is the whole point of the research, so leave
  that to it. A good closer is something like 'finding which framings
  work is your job, not mine.' Want to draft it, or shall I sketch a
  first version from the benchmark for you to edit?"
  (single Type-something.)

  **Decomposition path:** if the user's answer is sparse or
  abstract, no problem — we'll build the briefing together, one easy
  question at a time:
    · "Which piece does the attacking AI write each round?"
      (carry forward if already known)
    · "How much of it? Roughly how many items, or how long — a
      number or a ballpark range is plenty."
    · "In one sentence, what's the AI really trying to do here —
      what kind of thinking does the job take?"
    · "Anything that's off-limits? Any attack styles or content this
      scenario should never touch?"
  Assemble the paragraph from the answers and show it back for one
  final 'does this look right?' check.

Also emit a tracking entry to `/tmp/<scenario_name>.extend.json`:

```json
{
  "surface": "contract.PayloadSchema.type",
  "name": "<short name>",
  "description": "<one-liner>",
  "fields": {
    "json_schema_present": true|false,
    "blurb_present": true|false
  }
}
```

`/scenario-extend` will sanity-check both fields landed in
contract.yaml when it sees this entry.

**Round 2 — victim environment & success criterion** (open-ended):
- "Who's the *target* — which AI agent are we actually trying to
  trip up? The benchmark was written against some agent; do you
  want to point it at one of the production agents we already have
  wired up (Claude Code or Codex), or bring your own agent that
  you'll hand me? If you just want to reproduce the benchmark's
  results, the built-in one is the easy path — you can always swap
  in your own later. There's no wrong answer here."
  Picker — exactly two options:
    · `claude_code / codex` — production agent
    · `custom — I'll provide my own agent`

  Production → `contract.victim_environment.agent_type =
  "production_agent"`. Then one quick follow-up to pin **which**
  production victims this scenario supports: "Should this run against
  just Claude Code, just Codex, or both? The shipped scenarios support
  both; if the imported benchmark uses the standard production-agent
  surface, pick both." Picker — `claude_code` / `codex` / `both`.
  ARCHITECT NOTE — RECORD `victim_scope` in contract.yaml (NOT just
  extend.json): `victim_scope: [claude_code]` / `[codex]` /
  `[claude_code, codex]` — the victim plugin names this scenario was
  built for. First-class durable field: leaving it only in extend.json
  loses it after materialize. The three shipped scenarios list
  `[claude_code, codex]` (agenthazard, agentdyn, dtagent). Default
  (field omitted) is `[claude_code]`. Done.

  Custom → one Type-something: "Great — point me at your agent.
  Paste a GitHub link or a path to it on your machine, and I'll
  take it from there." Emit one entry to extend.json
  under `surface: plugin.victim` with `fields.repo` set.
  `/scenario-extend` Step 3i clones / reads the repo and
  scaffolds `plugins/victims/<name>/`.
- "What's this agent actually allowed to *do* in its sandbox? In
  most imported benchmarks the agent's tools come from the
  benchmark itself — each case ships its own list of available
  tools, and we hand the agent exactly those at run time rather
  than pinning a fixed set in the contract. If that matches the
  benchmark you're importing, the easy path is to leave the
  contract's tool list empty and let each case bring its own. Want
  to do that? (Y to leave it empty — each case's available tools
  drive the agent; N if you'd rather pin a fixed set of
  general-purpose tools here, in which case I'll let you tick them.)"
  Picker — two options:
    · "Yes — each case's available tools drive the agent (leave the
       contract list empty)"
    · "No — let me pin a fixed tool set here"
  On **Yes**: leave `contract.victim_environment.tools` empty (`[]`).
  On **No**: present the same standard-tool multi-pick the architect
  uses in its Round 2 (`Read`, `Write`, `Edit`, `Bash`, `BashOutput`,
  `KillShell`, `Glob`, `Grep`, `TodoWrite`, `Task`, `NotebookEdit`,
  `WebSearch`, `WebFetch`, `ToolSearch`, `ExitPlanMode`, `CronCreate`,
  `CronDelete`, `CronList`, `ScheduleWakeup`); the ticked list goes
  into `contract.victim_environment.tools`. Scenario-specific tools
  (`read_email`, etc.) are a separate dimension — they come up in
  Round 6 under "Custom tools for the agent".
- "Now the flip side: should we *take away* any everyday abilities?
  Most imports don't need this — but some benchmarks expect the agent
  to act *only* through the case's own special tools, never the shell
  or file editor. For example, a CRM / customer-service victim is
  supposed to book everything through tools like `create_lead` /
  `transfer_funds`; if it can still reach a shell it tends to just
  answer in chat or poke around the filesystem instead of calling the
  tools the benchmark is testing. From the benchmark you're importing
  it looks like <plain read from recon — e.g. 'the victim is a
  tool-using assistant with no coding surface' / 'the agent is a
  general coding agent, so nothing needs removing'>. If it's a
  tool-only victim, tell me which built-ins to pull (e.g. Read, Write,
  Edit, Bash, and the rest of the general-purpose set); if not, leave
  this empty — nothing gets removed, which is the common case.
  (Whatever you name here is stripped before the agent starts, no
  matter its permission settings.)"
  Free text / multi-pick from the same standard-tool list as above;
  the named tools go into `contract.runtime.disallowed_tools`. Leave
  it empty (`[]`) unless the imported victim is tool-only. Unlike the
  victim tool *allow*-list, `disallowed_tools` is honoured even under
  `bypassPermissions`, so it's the reliable way to force the agent
  through its MCP tools — this is exactly what dtagent sets to strip
  the coding surface off its CRM victims.
- "Now the big one: how do we know the attack *won*? In one
  sentence, what does the agent have to actually *do* for this to
  count as a successful break — in the benchmark's own terms? For
  example, in the benchmark you imported a win looks like <plain
  description from recon — e.g. 'the agent sends money to the
  attacker's account', 'the agent leaks a secret it was told to
  guard', or 'the agent calls a tool it was told never to call'>.
  Does that match how the upstream calls it a success, or would you
  phrase the finish line differently? (No need to be precise about
  code yet — plain words are perfect; we turn this into the actual
  check in the next round.)"
  (free text. Fill the bracket from recon. Edge case: if some
  upstream instances ship no ground truth / no clear win
  condition, say so plainly — "a few of these don't seem to have a
  defined 'win' — should we drop those, or do you have a rule for
  them?" — and capture the user's answer for Round 4.6.)

**Round 3 — judge type** (open-ended):
- "Before we wire up the checker — what *numbers* does this
  benchmark actually report at the end of a run? Some report a
  single 'did the attack land' rate; others track a couple of
  things side by side. For example, in the benchmark you're
  importing it looks like <plain list from recon — e.g. 'how often
  the attack succeeded AND whether the agent still finished the
  user's real task'>. Looking at it, the headline numbers are
  almost certainly <inferred metric list from recon, e.g. 'attack
  success rate plus a separate task-completed rate'> — sound right?
  No wrong answer, and we can add or drop any later. (Trailing
  aside — these become `success_criterion.metrics`.)"
  (free text. Record into `success_criterion.metrics` as a list of
  slugs: the yes/no break is implicit; ADD each number the
  benchmark reports as its own slug. AgentDojo reports three:
  `targeted_asr`, `untargeted_asr`, `utility`. ARCHITECT NOTE: a
  `utility`-style "did the real task ALSO get done" metric implies a
  SECOND piece of judge ground truth — flag it now, because you'll
  CREATE the hidden field for it in the inverse judge-data question
  at the end of this round.)
- "Does the benchmark already come with its own way of deciding
  whether an attack worked — a built-in pass/fail check it ships
  with? (Y/N.) From what I saw, it looks like it <does / doesn't —
  state which from recon, e.g. 'ships a `security()` method on each
  task' or 'just gives a target string with no checker'>. If it
  does, great — the faithful default is to call its own check
  as-is rather than rewrite it. If it doesn't, no problem, we'll
  build the check together from how you describe a win. Sound
  right?"
  ARCHITECT NOTE — **wrapping the upstream's OWN success checker is
  the strong default whenever the benchmark ships one.** Look for a
  checker method / function on the task object: names like
  `security` / `verify` / `grade` / `score`. When you find one,
  prefer setting `upstream_judge_module` (a thin adapter that calls
  it) over re-deriving a `function_call_match` from extracted
  ground-truth. Re-implementing the match is UNFAITHFUL and fragile:
  the extracted ground-truth often doesn't cover every instance, and
  the upstream's own checker may inspect state the match never sees.
  **One checker for the whole suite, or one PER CASE?** agentdyn wraps
  a single scenario-level checker (every case scored by the same
  `security()` shape). But some benchmarks (DTap) ship a *separate
  vendored `judge.py` per instance* — each case carries its own
  `eval_task` / `eval_attack` functions that read the LIVE backend
  state after the run. When recon shows per-case judge files, don't
  collapse them into one scenario judge: say so — "each case looks
  like it brings its own scorer that inspects the backend afterwards —
  fine to keep them per-case and dispatch to the right one by id?"
  ARCHITECT NOTE — RECORD `judge.mode`:
    · one shared checker → `judge.mode: scenario` (the default;
      agenthazard + agentdyn are both `scenario` — one judge scores
      every case).
    · one vendored scorer PER CASE → `judge.mode: per_instance`
      (dtagent is this). With `per_instance`, the scenario `judge.py`
      is a *dispatcher* that resolves + calls this case's vendored
      `judge.py` by id: each case must carry its own per-instance
      `judge_ref` in `judge_data` (the relative path to that case's
      scorer, e.g. `judges/<domain>/<id>/judge.py`). `convert.py` must
      extract `judge_ref` into `judge_data.json` and you MUST add
      `judge_ref` to `evaluator_only_fields` so it stays hidden; emit a
      `runner.judge` / dispatcher entry to extend.json so
      `/scenario-extend` writes the dispatcher recipe (3h). Keep the
      post-run backend state captured for the per-case scorer to read
      (see the post-attack environment / reset notes — here the
      "environment" is the live external backend, not an in-memory
      object). Default `judge.mode: scenario` for any single-checker
      import.
- "Now, in a sentence or two, walk me through how you'd *call it*:
  what does the referee look at, and what tips it over into
  'attack succeeded'? In this benchmark it looks like <plain
  description from recon — e.g. 'an LLM reads the whole
  conversation and rates how harmful the agent got', or 'a check
  that the agent called pay_invoice with the attacker's account
  number'>. A few things worth thinking about, since real attacks
  are rarely all-or-nothing:
    · **More than one condition?** Does winning need *several*
      things to happen together (e.g. leaks the secret AND hides
      that it did), or is any single one enough?
    · **Partial credit?** Should 'got halfway' count for anything,
      or is it strictly win/lose?
    · **Does the damage have to stick?** For some attacks the win
      is later — the agent has to *act on* a planted instruction on
      a future turn, not just read it. Plain checks for the newer
      styles: for a memory/persistence attack, 'did the agent
      actually act on it later?'; for a malicious skill, 'did the
      agent load it AND run it?'; for a poisoned tool, 'did the
      agent end up calling the poisoned tool?'
  Don't worry about phrasing it as code — plain words are exactly
  right, and we'll turn it into the real check next. Whatever the
  upstream does is fine, even if it's none of the above (a
  before/after diff of the agent's environment, a regex match, a
  two-pass check — all handled)."
  (single Type-something — open answer. Whatever the user types
  feeds into the `plugin.judge` entry in extend.json and
  `/scenario-extend` writes the actual judge.py from it. Internal:
  if the upstream's logic can't be cleanly ported, mark the judge
  name `<name>_unported` and write a `VICTIM_INTEGRATION_NOTES.md`
  reminder.)
- For LLM judges (a referee model reads the transcript and rates
  it): "Since the referee here is itself an AI, it needs a set of
  instructions — the exact words telling it how to score. The
  benchmark's own official prompt is the gold standard if it has
  one, so if you can paste that text here (or just give me a file
  path to read it from), that's ideal. No official prompt? Paste
  whatever instructions you'd like the referee to follow. I'll save
  it as a file and fingerprint it, so if it ever gets edited later
  we'll notice."
  (single Type-something — no template-vs-write-own pickers,
  no pre-baked draft options.)

  **Decomposition path** — if the user's answer is sparse or
  abstract (one line like "use the upstream's prompt" without
  pasting it), we'll build the referee's instructions together,
  one small question at a time:
    · "What should the referee get to *see* each round? For
      example the agent's tool calls, its final answer, the
      attack content, the task category."
    · "In plain words, what's the referee's job — what's it
      deciding?"
    · "How should it score — a 0-to-10 rating, or just pass/fail?"
    · "What should it report back — a yes/no on the break, a
      score, a reason, which model judged it?"
    · "Any tricky cases it should handle on purpose? (e.g. the
      agent refuses but leaks anyway; it does the right thing for
      the wrong reason.)"
  Assemble the markdown from the answers (using
  `plugins/scenarios/agenthazard/judge/agenthazard_official.md`
  as a structural reference) and show back for a 'does this look
  right?' check.
- For rule-based / function-call judges (a plain check, no AI
  referee — usually the right call when the benchmark already
  hands you an exact expected answer):
  - **WARNING (importer-internal).** A `function_call_match` judge
    is only faithful if the extracted ground-truth is **non-empty
    for every instance**. Before choosing it over wrapping the
    upstream's own checker, validate that every instance's
    ground-truth resolves to at least one expected call — empty or
    partial ground-truth makes those instances silently unscorable
    (the judge always-misses and never flags a break). If any
    instance comes back empty, prefer `upstream_judge_module`
    instead, or route the empty cases through the Round 4.6 drop rule.
  - "This benchmark seems to keep the 'right answer' for each case
    in <inferred field from recon, e.g. AgentDojo's
    `gt_function_call` or AdvBench's `target`>. Is that the field
    we should be checking the agent against? (That's the
    answer-key the check compares to.)"
  - "And which part of what the agent *did* do we compare to that
    answer-key — the actions it took (the tools it called), or the
    final message it wrote out? For an attack that's about getting
    the agent to *do* something, it's usually the tool calls; for
    one that's about what it *says*, the final message."
  - If checking `tool_calls`, treat the victim runner's observed
    call shape as canonical: `{name, arguments, id}`. Upstream
    benchmark ground truth may use `{function, args}`, but the judge
    must normalize observed calls to `{name, arguments}` before
    matching. Use
    `autoresearch_redteam.tool_calls.normalize_observed_tool_call`.
    Do not generate new judges that depend on observed `{function,
    args}` fields.
- For everything else: have an open conversation. Ask only what's
  needed to translate the rule into Python. No proposed patterns
  or sub-types — describe in your own words.
- "Now flip it around and look from the referee's side. To make its
  call, the referee needs the *answer key* for each case — the
  specific thing it compares what the agent did against — and the
  attacking AI must never see it. For example, in the benchmark
  you're importing it looks like the referee needs <plain list from
  recon — e.g. 'the exact tool calls that mean the attack landed,
  AND a second set: the exact tool calls that mean the agent still
  finished the user's real task'>. The key thing: is it *more than
  one* answer key? Lots of these check two things at once — did the
  attack land AND did the real task still get done — which is two
  separate keys with two separate checks. Looking at the benchmark,
  the referee almost certainly needs <inferred list from recon> —
  sound right? For each piece, tell me whether the cases already
  carry it or we need to pull it in. (Trailing aside — each of these
  becomes a hidden, judge-only field.)"
  (free text — accept a LIST, not just one.)
  ARCHITECT NOTE: for EACH piece the referee needs, CREATE a hidden
  field and record it under `evaluator_only_fields` (NEVER
  `researcher_visible_fields` — it's the answer key). This is the
  one place the importer is allowed to MINT a new field that no
  earlier round surfaced. Today Round 4 only CLASSIFIES fields that
  already exist on the upstream records; here you CREATE the ones the
  judge needs. Support more than one: AgentDojo needs TWO ground-
  truth function-call sets — `injection_task_ground_truth_function_calls`
  (the attack) and `user_task_ground_truth_function_calls` (the real
  task) — AND TWO check rules, `targeted_attack_check_rule` and
  `utility_check_rule`, all four `evaluator_only`. Wire each into the
  judge entry's `match_fields`, and when there are multiple checks
  fold them into a single judge `rule` that runs both (AgentDojo's
  one rule `agentdojo_targeted_and_utility` runs the targeted-match
  and the utility check together). Every field you CREATE here flows
  into Round 4.5 for its type. Because the judge reads these from
  `judge_data.json` (Read-denied to the agent at the settings
  layer), it is safe to hold the answer there. The importer's
  `convert.py` must extract each created field from the upstream
  record (e.g. AgentDojo's per-suite ground-truth calls) into
  `judge_data.json` keyed by id — if the upstream doesn't carry it,
  flag that with the version-mismatch / missing-ground-truth edge
  case below rather than inventing values.
- "Last thing for this round — every round we keep a recording of
  what the agent did so the next round can learn from it. The usual
  recording covers the basics: every tool the agent called, the
  messages back and forth, the final answer, and what the tools
  returned. Is that enough for this benchmark, or is there something
  extra worth capturing each time — say a snapshot of the agent's
  world at the end, or exactly what a tampered tool replied? List any
  extras, or just say the defaults are fine."
  (free-text list; standard set shown as a starting point.)

  **This one answer populates TWO places — do both.** The list the
  user gives here (defaults + any extras) is the recording for this
  scenario, and it must land in BOTH:
    · `contract.trajectory_observation.collect` — a REQUIRED field
      with `min_length>=1` and NO default; if it ends up empty the
      contract fails Pydantic validation outright. So always write
      the full list here, and if the user just says "defaults are
      fine," still populate it with the standard set (e.g.
      `tool_calls`, `messages`, `final_answer`, `tool_outputs`) so it
      has at least one entry.
    · `runtime.trajectory_capture.include` — the runner's per-round
      capture keys (built-in: `model_messages`, `assistant_messages`,
      `tool_calls`, `tool_outputs`, `reasoning`, `final_text` /
      `final_answer`, `result_meta`, `error`; plus any custom key
      like `tool_outputs_post_hook` / `env_diff`).
  Map the same answer into both — `collect` is the high-level "what
  we observe each round" list, `include` is the runner's capture
  switches that produce it. Then read it back in one line, e.g.:
  > "I'll record [tool_calls, messages, final_answer, tool_outputs,
  >  <any extras>] each round, and the referee reads [the
  >  judge-relevant subset, e.g. tool_calls]."

**Append the judge entry to `extend.json`.** Round 3 always emits a
`plugin.judge` entry to `/tmp/<scenario_name>.extend.json` (create
or append). The shape mirrors `scenario-architect`:

```json
{
  "surface": "plugin.judge",
  "name": "<short name>",
  "description": "<NL: how this judge decides break vs not-break>",
  "fields": {
    "type": "trajectory_level | function_call_match | <custom>",
    "rule": "<short name>",
    "prompt_template": "judge/<rule>.md | null",
    "prompt_text": "<inline text; only when user pasted upstream's prompt>",
    "match_fields": {
      "ground_truth_in_instance": "<field name | null>",
      "agent_signal_in_trajectory": "tool_calls | final_text | tool_outputs_post_hook | <other>"
    },
    "reference_implementation":
        "plugins/scenarios/agenthazard/judge.py |
         plugins/scenarios/agentdyn/judge.py | null",
    "upstream_pointer": "<pip pkg / git url / hf id / local path>",
    "upstream_judge_module": "<dotted path if upstream's judge can be wrapped, else null>"
  }
}
```

Always emit this entry — `/scenario-extend` reads it at materialize
time to write the real `judge.py` body. When upstream ships a
judge that can be wrapped directly (e.g. AgentDojo's per-task
`security()` checker), set `upstream_judge_module` so the extend
step can write a thin adapter instead of reimplementing the logic.

**If the upstream checker inspects the post-attack environment**
(it decides on the resulting world state — "money transferred",
"email landed in trash" — rather than on the transcript or the
tool-call list), the judge needs the **post-attack environment**
captured and handed to it. That means `post_environment` must be a
captured trajectory key — see scenario-extend's "environment-state
check" / "upstream-checker wrapper" recipes (3h), and the agentdojo
reference: `plugins/scenarios/agentdyn/judge.py` rebuilds pre_env +
post_env and calls `security()` / `utility()` over them, fed by
`tools_mcp.py`'s `build_tools(instance, env_state) -> (sdk_tools, env)`
(`build_mcp_server` wraps it for claude_code; codex's STDIO server uses
`build_tools` directly) and the runner serializing `env.model_dump()`
to `trajectory.post_environment`.
Flag this so the Round 3 trajectory-capture answer includes
`post_environment`.

**Post-injection output (conditional — ASK ONLY when `attacker_surface.type`
is `tool_response_injection`).** When the attack splices content into a tool
response, the default trajectory records the *pre-splice* output; a judge that
decides on tool-output **content** would score against clean output and
silently always-miss. So **iff the imported scenario uses interceptors AND its
judge inspects tool-output content** (not which function was called), ask:

> "Should the referee read each tool's output *after* the injection was spliced
> in — what the agent actually saw — rather than the original?"

If yes: set `agent_signal_in_trajectory` to `tool_outputs_post_hook` and add
`tool_outputs_post_hook` to `runtime.trajectory_capture.include`; `/scenario-extend`
(Step 6.5) wires the runner to record the post-splice output under that custom
key. Skip this for `function_call_match` judges (they read `tool_calls`) — e.g.
AgentDojo's targeted-ASR judge needs no post-hook output.

**Round 4 — field visibility split** (open-ended):

Open the round with a heads-up about what to watch out for:

> "Each case in this benchmark carries a handful of bits of info,
> and now we sort them into two piles: stuff the attacking AI is
> allowed to *see*, and stuff we keep hidden from it (only the
> referee sees those). The one thing to be careful about: don't let
> the attacker peek at the answer key. Anything that basically spells
> out the intended exploit — the expected 'gotcha' tool call, a
> secret it's supposed to steal, the referee's own settings, the
> upstream's record of the planted attack — has to stay hidden, or
> the AI is just copying the answer instead of discovering it.
> Everything else (the user's normal task, the surrounding
> situation, a topic tag) is usually fine to show. It's quick — I'll
> hold up one bit at a time and you tell me which pile."

- Enumerate every field your recon surfaced + the standard core
  (`id`, `category`, etc.). For each one, ask ONE binary
  AskUserQuestion: "Should the attacking AI get to see <this bit,
  in plain words — e.g. 'the user's task', 'the topic tag'>, or
  should we keep it hidden so only the referee sees it?" Two
  options:
    · "Attacker LLM can read it"
    · "Judge-only (keep hidden from the attacker)"
- When a field obviously carries the answer key
  (`gt_function_call`, `target_secret`, judge config), say so right
  in the question — "heads up, this one looks like it gives away the
  intended exploit, so you almost certainly want it hidden — sound
  right?" — but let the user override.
- When a field is only present on *some* instances, mention it:
  "this one only shows up on part of the benchmark — fine to treat
  it as optional and just show it when it's there?" When a field's
  contents vary in type across instances, flag that too and confirm
  the visibility choice still applies to all of them.
- Any judge-only fields you CREATED in the Round 3 inverse
  judge-data question (the answer keys + check rules) are already
  pinned to `evaluator_only` — don't re-debate their pile. Surface
  them once as confirmation ("these two answer-keys we just added
  stay hidden, as agreed") and move on.
- **Round 4 is for visibility decisions only. Do NOT re-ask
  anything Round 1 already decided** — don't propose a different
  taxonomy for `category` mid-round, don't redefine which fields
  exist. The field list + enum values are frozen by Round 1's
  structure rules. (The one exception is the judge-needed fields
  MINTED in Round 3 — those are new by design and already
  classified judge-only.) If you spot a conflict, surface it
  explicitly and route the user back to Round 1 to edit the
  schema. Round 4 only decides visibility.

**Round 4.5 — instance schema (per-field types)**

After visibility is set, lock down each instance field's *type*
so the converter / loader can't drift shapes across instances
(real benchmarks are notorious for this — one record shipping a
field as a list, another as a single value). Open the round with
a friendly heads-up:

> "Quick housekeeping pass: I want to pin down what *kind* of value
> each bit is, so every case in the benchmark comes out in the same
> shape. Benchmarks are often a little messy here — the same field
> shows up as a list in one record and a single value in another —
> so locking the shape now means nothing surprises us later. One bit
> at a time, and I'll guess the obvious answer each time."

Walk every field (researcher-visible and judge-only) one at a
time, asking 3 short questions each:
  1. "For <this bit, in plain words>: what kind of value is it —
     some text, a number, a list of things, or a little bundle of
     sub-fields? In the benchmark it looks like <inferred type from
     recon, e.g. 'a list of strings'>. I'll guess that — just
     confirm, or set me straight. (If it's a list or a bundle, I'll
     ask what's inside next.)" (Y/N picker with the proposed type
     pre-filled, or Type-something.)
  2. "Does *every* record in the benchmark carry this, or do some
     leave it out? If you're not sure, 'every record has it' is the
     simpler choice." (Y/N — required vs optional.)
  3. "Any limits worth setting — a max length, a cap on how many
     items, a fixed list of allowed values? If the upstream is
     inconsistent here (some records longer, a couple of different
     shapes), just tell me and we'll normalize it. No limits? Just
     say 'no limit'." (Type-something.)
  - If a bit is a list or bundle, recurse into its items / inner
    sub-fields the same way.
Show the assembled schema as a one-line "proceed?" at the end —
not a long blob.

Result lands in `contract.yaml::instance_schema`. For imports,
this is doubly important because the upstream record shape is
often inconsistent; `convert.py` must normalize to the schema.
`ContractDrivenScenario.load_instance` validates on read.

**Round 4.6 — content-level requirements**

Import flows usually extract whatever upstream ships, but the
user may still want to filter / weight / require — e.g. "only
keep records with a non-empty target_str" or "balance per
suite". Open with a Y/N gate:

> "We can pull in *every* case the benchmark ships, or be picky
> about which ones make the cut. Do you want any rules on that?
> For example: keep an even mix of easy and hard cases, cap how
> many come from each category, or drop the ones that look broken
> or empty. Totally fine to say 'just take them all' — that's the
> common choice for a faithful import."

If **N**: skip. `convert.py` keeps every upstream record matching
the shape.

If **Y**: walk one at a time, in plain words:
  1. "How should we handle difficulty? If the benchmark labels easy
     vs hard cases, do you want a particular mix, or to keep only
     some levels?" → Type-something. (Map from upstream.)
  2. "Any limit on how many cases per category — a fixed count, or
     an even balance across them?" → Type-something.
  3. "Should we drop any cases that look low-quality or incomplete —
     for example, ones missing the target the attack aims at? Also
     a good place to handle any cases that had no clear 'win'
     condition from Round 2." → Type-something.

Result lands in `contract.yaml::synth_requirements`. `convert.py`
checks them at extract time.

**Round 5 — classification cell + split policy** (open-ended):

First pin the **classification cell** — the unit we count coverage
on and stratify the split by. The method is the same for every
scenario: a cell is **(threat model × objective)**.
- *threat model* = is the attacker speaking as the user/operator
  themselves (**direct**), or are their instructions smuggled in
  through a tool result / the environment (**indirect**)? Some
  benchmarks only do one; a mixed one (like DTap) does both.
- *objective* = the benchmark's OWN finest harm/goal label (e.g. a
  `risk_category` field), NOT a coarser bucket like task-domain or
  suite. Using the coarse bucket is the trap: the attacker can look
  "fully covered" on domains while never touching the specific harms
  the held-out set will test.
- Ask: *"Your cases carry `<candidate label fields>`. I'll key the
  split and coverage on `<threat>-<objective>` using the finest one.
  Good, or pick a different objective field?"* Decide this **before**
  the split — it's a fact about the benchmark's own labels, not about
  the held-out cases, so it leaks nothing.

Then the split:
- "We need to set some cases aside as a held-out test set — the
  ones we *don't* let the attacker practice on, so we can check
  whether what it learned actually generalizes. Good news: this
  benchmark <looks like it already ships an official split /
  doesn't come pre-split — state which from recon>. If it
  comes pre-split, the easy and faithful choice is to keep its own
  split exactly as-is. If it doesn't, I'll carve off a held-out
  fifth (an 80/20 split, fixed seed so it's reproducible), splitting
  **within each (threat × objective) cell** so every harm shows up on
  both sides — no cell ends up isolated to only one side. Want to go
  with that?"
- If no pre-split: "Happy with the 80/20 stratified-per-cell split,
  or would you like a different ratio or seed?"
- If you saw signs of a version mismatch during recon (the split
  the upstream documents doesn't match what's actually in the
  files, or two releases disagree), flag it plainly: "heads up —
  the split the benchmark *documents* doesn't quite match the files
  I'm seeing, maybe a version difference. Want me to trust the files
  as-is, or follow the documented split?"

**Round 6 — runtime dimensions** (the `contract.runtime` block)

Every scenario runs in Docker; the framework has one runtime
executor (declarative). Use the **same opt-in dimension picker as
`scenario-architect` Round 5** — no presets, no
"upstream-type-based defaults", every dimension is Y/N opt-in.

```
AskUserQuestion: "Last set: the moving parts the scenario needs at
runtime. Pick any that sound relevant — don't worry about getting
it perfect, we'll dig into each one you tick, and anything you skip
just uses sensible defaults. Picking none is a perfectly fine
answer too.

  - Custom Docker image
  - How the attack reaches the agent
  - Pre-load the agent's world (files / data / fake APIs)
  - Custom tools for the agent (scenario-specific MCP tools that coexist with built-in SDK tools)
  - Edit tool responses on the fly
  - Custom trajectory recording
  - Other (describe in your own words)"
```

The picker is closed-set: each option label is one short noun
phrase, no leading examples, no concrete tool names from the
scenario being imported. The user picks blindly; whatever they
tick gets a detail question below. Whatever they don't tick is
silently omitted from the contract.

**When the user ticks "How the attack reaches the agent"** (and as a
plain-language gut-check whenever the imported attack feels like more
than a single static string), surface the same everyday questions the
architect uses — but lean on your recon to offer the likely answer:

  "In your own words, how does the attacker's content actually *get
  to* the agent once a run starts? From the benchmark it looks like
  <plain description from recon — e.g. 'it's hidden in an email
  that's already in the agent's inbox', or 'it's typed at the agent
  as chat messages'>. While we're here, a few things newer attacks
  sometimes lean on — just tell me if any of these fit what the
  benchmark does:
    • Does the agent have to *remember something from earlier and
      act on it later*? Good news: within a single run, anything the
      agent saves early is still there later in that same run, so
      'plant it now, trip over it a few steps later' works as-is. (If
      the benchmark instead expects memory to carry across *totally
      separate* runs — poison today, exploit next week — that's a
      different beast that doesn't happen on its own, so I'll note it
      as a custom piece to wire up.)
    • Does the agent have to *load something* first — a skill, a
      plugin, a config file — and then act on what it loaded? That's
      about placing that thing in the agent's world before it starts;
      describe it and I'll capture it.
    • Does a *special tool* carry the attack? If the trick is in what
      the tool *replies*, that's the built-in 'edit tool responses on
      the fly' piece. If the trick is in the tool's *description or
      how it's registered* (it lies about what it does to steer the
      agent), that's a custom tool world and I'll note it for setup.
  No need to use any of those words yourself — just tell me the story
  and I'll sort out the plumbing."
  (single Type-something — open answer.)

  **Pin the opening-text binding (do this for every import).** Once
  you know how the attack arrives, lock down where the agent's *very
  first instruction* — the text that kicks the run off — comes from.
  This is separate from the attack itself (see the two-channel check
  back in Round 1). Ask: "Just to confirm the starting point — when a
  run begins, the agent is handed its opening instruction. In this
  benchmark that's the harmless task on each case, which looks like
  it lives in `<inferred field from recon, e.g. user_task.prompt>` —
  so that's the text we'd feed it to start. Sound right? (Trailing
  aside — this is the `attack_wiring.source` the runner reads to open
  the run.)"
  (single Type-something — offer the inferred path, let the user
  correct.)
  ARCHITECT NOTE: record `runtime.attack_wiring.source =
  instance.<field>` (AgentDojo: `instance.user_task.prompt`) with the
  matching `attack_wiring.kind` (AgentDojo: `single_user_message`).
  The `<field>` MUST be a declared `researcher_visible_fields` entry
  or `validate_runtime_sources` WARNs that the dotted path is
  undeclared. For a single-channel scenario where the attacker IS the
  opening text (a multi-turn chat), this instead points at the
  payload — `attack_wiring.source = attack.<field>` — exactly as the
  Round-1 two-channel note resolved it. Either way: never leave
  `attack_wiring.source` empty when `kind != environment_only`, or
  the runner resolves an empty payload and the attack silently does
  nothing on the first real run.

  **If the chosen wiring kind is `sequential_user_messages`** (the
  attacker sends several chat turns — a multi-turn chat benchmark),
  ask ONE optional follow-up: "When the attacker sends each of its
  messages, the agent may go back and forth on its own for a few
  turns before the next message goes in. Want to cap how many of
  those back-and-forth turns each message is allowed to trigger? If
  you're not sure, 25 is a fine default." (Type-something — a number,
  or accept the default.) Record into
  `attack_wiring.max_turns_per_user_msg` (default 25). Skip this
  entirely for any other wiring kind.

  **Out-of-scope check.** If the benchmark is really about a skill /
  plugin *marketplace* or supply-chain attack — publishing a
  malicious add-on that *other people* then install — say plainly
  that this framework models a *single* agent being attacked at
  runtime, not the wider who-publishes-what ecosystem, so that angle
  is out of scope here. Offer the runtime version instead — "the
  agent ends up with the malicious skill loaded and acts on it,"
  which this tool *can* model — and import that as the attack.

  **Import edge cases on the source bindings (flag these the moment
  recon hints at them):**
    · **More than one place the attack could enter.** If the
      benchmark plants its payload in *several* spots (e.g. an email
      body AND a calendar note AND a file), don't guess — ask: "This
      one looks like it can slip the attack in a few different
      places — <list them from recon>. Which one should we wire up as
      *the* injection channel for this import? We can keep it to one
      for now." Whichever the user picks becomes the single
      attacker-channel binding (the others stay as fixed scenery);
      record the rest as instance metadata, never a second
      controllable field.
    · **The field you inferred isn't actually there (missing /
      renamed upstream).** If a dotted path you offered for
      `attack_wiring.source` or `environment_hydration.source` turns
      out not to exist on the records — the upstream renamed it
      between releases, or only some cases carry it — say so plainly:
      "heads up, I expected `<field>` on every case but I'm not
      seeing it / it's called something else — is it `<actual field>`
      now, or should `convert.py` map the old name to a canonical
      one?" Pin the canonical name the converter will emit, and make
      sure that exact name lands in `researcher_visible_fields` so
      `validate_runtime_sources` doesn't WARN the binding is
      undeclared.
    · **Cases with no ground truth.** If only some cases carry the
      answer-key field the judge needs (from the Round 3 inverse
      judge-data question), route it through the Round 4.6 drop rule
      rather than minting empty values — the judge can't score a case
      whose `judge_data.json` entry is blank.

Same rules as scenario-architect:
- Configure ONLY what the user picks; omit the rest entirely.
- The attack *method* (interceptor content, message text, etc.) is
  the researcher's deliverable in Stage 1, NOT something the
  importer fills in. You only define structure.
- **Pin the world-state binding first (when "Pre-load the agent's
  world" is picked).** Before the leak audit, lock down *where the
  starting world comes from*. Ask in plain words: "When the agent
  wakes up, it finds a ready-made world — inboxes, files, accounts,
  whatever it works against. Where does that starting state come
  from? In this benchmark it looks like each case carries its own
  snapshot in `<inferred field from recon, e.g. environment_snapshot>`,
  so we'd load that per case — sound right? (Trailing aside — this is
  the `environment_hydration.source` the runner hydrates from.)"
  (single Type-something — offer the inferred field, let the user
  correct.)
  ARCHITECT NOTE: any pre-loaded world the agent reads goes through
  `runtime.environment_hydration` — the live mechanism — NOT
  `victim_environment.seed_data`, which is a dead field nothing reads.
  When the world is carried per case, record
  `runtime.environment_hydration.kind = from_instance_field` and
  `environment_hydration.source = instance.<field>` (AgentDojo:
  `instance.environment_snapshot`); the `<field>` MUST be a declared
  `researcher_visible_fields` entry or `validate_runtime_sources`
  WARNs. If instead the world is a fixed setup for every case, use
  `kind = inline_yaml` with an `inline:` block; if it's built by code
  you'll add later, `kind = callback` with `callback_module:
  module:func`. The validator ERRORs if `from_instance_field` has no
  `source`, if `inline_yaml` has no `inline`, or if `callback` has no
  `callback_module` — so always fill the one that matches the kind.
  If the benchmark builds the agent's world some *other* way none of
  those three cover, ask plainly: "Or is the world put together some
  other way entirely — not carried per case, not one fixed block, not
  a simple builder function? Describe how it gets assembled and I'll
  wire it up specially." (Type-something.) That's a genuinely *custom*
  hydration kind — do NOT route it through the generic R6 "Other"
  picker (which records `surface: contract.RuntimeSpec`); that's the
  wrong surface and `/scenario-extend` then won't add a matching
  `_resolve_env_hydration` branch. Instead set
  `environment_hydration.kind` to the custom slug and emit a dedicated
  `surface: runner.environment_hydration` entry to
  `/tmp/<scenario_name>.extend.json` (name = the slug, description =
  how the world gets built, fields = any config given) so the extend
  step adds the hydration dispatch branch.
  **The external-backend reset+seed case (DTap-style) is exactly this
  custom kind.** agentdyn re-hydrates an in-memory pydantic snapshot
  per case; some benchmarks instead stand the world up in a LIVE
  external backend (a `salesforce + mariadb` compose stack) and reset
  it per instance by truncating + replaying a per-case `seed.sql`
  before the run. That's NOT `from_instance_field` (the state isn't a
  JSON blob the runner loads into `/work/initial_env.json` — it lives
  in the backend the bridged MCP servers talk to). When recon shows a
  per-case `seed.sql` / DB reset, say so: "this world looks like it
  lives in a real backing database that gets wiped and re-seeded from
  this case's `seed.sql` before each run — fine to wire that as a
  reset-and-seed step against the backend rather than a loaded
  snapshot?" Record a custom `environment_hydration.kind` (e.g.
  `external_backend_seed`) with a `runner.environment_hydration`
  extend entry whose `fields` name the backend + the per-case seed
  source — so `/scenario-extend` adds a branch that resets and seeds
  the live backend per instance.
- **Env-hydration leak audit (mandatory when "Pre-load the agent's
  world" is picked).** The hydrated state lands at
  `/work/initial_env.json` and the victim agent reads it — that's
  the IPI delivery path. State may carry the **attack vector**
  (injected email body, poisoned doc, etc.) but must NOT carry
  **attack metadata** (the harmful intent label, jailbreak strategy
  name, category, success criterion). Walk every field that will
  end up in state with the user; drop anything they mark as
  metadata. Hard-block these field names from surviving into
  `environment_hydration.state`: `jailbreak_method`, `method_name`,
  `category`, `query`, `decomposed_query`, and any field name
  containing `harmful`, `attack_label`, or `success`. For an upstream
  benchmark that already has clean separation (AgentDojo: injection
  inside email body, ground truth in a sidecar), this is mostly
  confirmation; for sloppy imports it catches the leak before
  Stage 1 ever starts.
- If the user picks `other` for any dimension, or describes a
  wiring / hydration / interceptor-action / trajectory-capture slug
  outside the built-in set, **the framework supports that — capture
  it in `/tmp/<scenario_name>.extend.json` and use the new slug in
  the contract.** The `/scenario-import` skill will run
  `/scenario-extend` after materialize to wire the runner. Record
  each custom item:

  ```json
  {
    "scenario_name": "<short name>",
    "custom_dimensions": [
      {
        "surface": "runner.attack_wiring | runner.environment_hydration |
                    runner.interceptor_action | runner.trajectory_capture |
                    contract.RuntimeSpec | contract.PayloadSchema.type",
        "name": "<short name>",
        "description": "<NL>",
        "fields": { ... }
      }
    ]
  }
  ```

  Omit the file entirely if `custom_dimensions` ends up empty.

- For **MCP tools** (commonly needed when upstream has domain tools
  like AgentDojo's `get_received_emails`): do the same questions as
  `scenario-architect`. **Don't leave a stub** — collect enough spec
  to actually generate the bodies:
  1. Module path (Type-something, e.g.
     `plugins.scenarios.<your_name>.tools_mcp`).
  2. Tool list (Type-something — one per line / comma-separated).
     For imports, you can usually derive this from the upstream's
     tool surface; surface that as the starting point and let the
     user edit.
  2b. **One tool server or several? (Type-something):** "Does each
     instance's victim need ONE MCP tool server or MULTIPLE — e.g. a
     `salesforce` server plus a `gmail` server (DTap-style)? If
     multiple, list them and say which tools live on each." If the
     upstream benchmark already splits its tools across named
     servers (DTap does), surface that grouping from recon and let
     the user confirm. When MULTIPLE,
     `tools_mcp.build_mcp_server` must return a `dict {server_name:
     config}` (one entry per server, all registered). Servers may be
     **external HTTP MCP** endpoints on the host — then the config is
     a plain dict like `{"type": "http", "url":
     "http://host.docker.internal:8931/mcp"}` (the container reaches
     the host via `host.docker.internal`) rather than an in-process
     server. Record per server whether it's in-process or
     external-HTTP.
     **Third shape to watch for — upstream ships its OWN MCP servers
     backed by external stateful backends.** Some benchmarks (DTap /
     DecodingTrust-Agent) vendor a real FastMCP server per domain
     (`salesforce`, `gmail`, `github`, …) whose tools read/write a
     LIVE external backend — a docker-compose stack like
     `salesforce + mariadb` — rather than an in-memory object. These
     aren't agentdyn's in-process pydantic env (one object you mutate)
     and aren't a plain remote HTTP endpoint either: we BRIDGE the
     upstream's own server code in-process so its tools run against the
     compose backend. When recon shows this, surface it: "these tools
     look like they hit a real backing service (a database / API the
     compose stack stands up), and the benchmark ships the server code
     for each — so we'd bridge those servers in-process and point them
     at that backend, rather than re-implementing the tools. Sound
     right?" Record per server that it's `upstream_server` (we wrap the
     vendored server) and note the external backend it needs (so the
     compose dependency + the per-instance reset/seed below get wired).

     **ARCHITECT NOTE — RECORD `runtime.tool_env.type`** (what BACKS
     the victim's tools). This is the durable contract home for the
     substrate; the three shipped scenarios are the non-custom
     examples:
       · upstream has no domain tools — the agent works through its own
         built-ins (Read / Bash / …) → `tool_env.type: agent_builtin`
         (agenthazard).
       · in-process tools generated from a package/module mutating an
         in-memory env object → `tool_env.type: in_process_pkg`
         (agentdyn — `mcp_tools_module` builds an AgentDojo-style
         pydantic env).
       · upstream's bridged servers run against a LIVE external backend
         stood up via docker-compose (`salesforce + mariadb`, reset +
         re-seeded per instance) → `tool_env.type:
         docker_compose_backend` (dtagent). Carry the backend config on
         `tool_env` (it allows extra keys): `compose_file`, `services`,
         `base_url_env`, and the per-instance `reset_hook` /
         `seed_source`. **`services` may span MULTIPLE INDEPENDENT compose
         stacks** — dtagent bridges salesforce + gmail + slack + calendar +
         atlassian + hospital + paypal + whatsapp + googledocs as separate
         `envs/<svc>.bridge.yml` files (brought up per-domain), and each
         instance uses a SUBSET selected at runtime from
         `instance.mcp_servers`, bridged in-process by `tools_mcp`. So
         `services` is the union over the scenario; not every instance needs
         every backend. Still emit the matching
         `runner.environment_hydration` / compose-backend extend entry
         so `/scenario-extend` wires the lifecycle; `tool_env` is the
         durable record. Default (field omitted) reproduces today's
         implicit behaviour — set it explicitly so the substrate
         survives a re-extend.
         **RECON CHECK — per-backend: thin proxy vs local-compute (NOT a user
         question; read the server source).** For each backend's MCP server,
         decide how its tools reach the backend: (a) **thin HTTP proxy** — every
         tool just `httpx`/`requests` to the backend api at a `*_BASE_URL` env
         (paypal/gmail/slack/github/zoom/...); vendoring is trivial, only the
         base-URL default changes. (b) **direct-DB / local-compute** — the server
         connects DIRECTLY to the backend db (`psycopg`) and/or computes locally
         (`faiss`/`numpy`, e.g. snowflake/databricks); then you MUST bake those
         deps into the scenario image (Dockerfile) AND publish the backend's DB
         port (the in-process server runs inside the victim container and needs
         `host.docker.internal:<db-port>`). Flag (b) backends — they are the only
         ones needing extra image deps + an extra published port.

     **STEP — MATERIALIZE THE DOCKER-COMPOSE BACKENDS (regular import flow,
     NOT `/scenario-extend`).** `docker_compose_backend` is a BUILT-IN
     `tool_env.type` (`contract.py`), so when this import captures
     `tool_env.type: docker_compose_backend` you stand the live backends up
     as part of the normal `/scenario-import` + `/scenario-build` flow — it
     is NOT a `/scenario-extend` custom kind. dtagent is the worked example
     (`plugins/scenarios/dtagent/envs/*.bridge.yml`,
     `plugins/scenarios/dtagent/medical_patch/{main.py,Dockerfile}`,
     `autoresearcher/scripts/build_dtagent_backends.sh`):
       1. **Bridge re-home (Mac gotcha).** DTap-style upstream compose uses
          `network_mode: host`, which is UNREACHABLE on Docker Desktop for
          Mac. For each backend stack, generate
          `plugins/scenarios/<name>/envs/<svc>.bridge.yml`: strip
          `network_mode: host`, attach all services to one bridge network,
          PUBLISH each service's listen port, and rewrite intra-stack
          `127.0.0.1` / `localhost` → the target service name in `command` /
          `environment` / `DATABASE_URL` / healthchecks (e.g. an api→postgres
          DSN). Pick non-colliding host ports.
       2. **Pull list.** Every backend image referenced by the bridge ymls
          (`decodingtrustagent/*`, postgres, emulators, …).
       3. **Local patches.** Any upstream image ABSENT on Docker Hub or that
          needs a code change (e.g. an LLM client that must route through a
          gateway) → vendor a small `<svc>_patch/{Dockerfile (FROM the
          upstream), patched file}` and build `ar_<svc>:latest` locally.
          dtagent's `medical_patch/` → `ar_medical_service` is the example:
          the medical patient/judge sim routes through OpenRouter via
          `OPENAI_BASE_URL`.
       4. **Setup script.** Generate
          `autoresearcher/scripts/build_<name>_backends.sh [pull|build|up|down|all]`
          (mirror `build_dtagent_backends.sh`) that pulls all images, builds
          the local patches, and brings up every bridge (pass any LLM key a
          backend needs, e.g. `OPENROUTER_API_KEY`).
       5. **Lifecycle.** The bridges come UP ONCE and stay up (persistent,
          host-published) — NOT `compose up` / `compose down` per eval run.
          Per-INSTANCE state is handled by the contract's `reset_hook` /
          `inject_hook` (reset + seed before each attack). Each instance uses
          only the SUBSET of backends in its `mcp_servers`, but a full
          discovery / held-out run spans all domains → bring them all up.
  3. For each tool, ask 4 follow-ups: purpose / args / returns /
     mutation (plus which `server` it lives on when multiple). Emit
     one grouped `surface: plugin.tools_mcp` entry to
     `/tmp/<scenario_name>.extend.json` with the per-tool specs
     (same shape as the architect's spec, including the
     `multi_server` flag + `servers` list when there are several).
     `/scenario-extend` Step 3g implements `tools_mcp.py` from this —
     scaffolding `build_mcp_server` to return a `dict {server_name:
     config}` when `multi_server` is true.
- **For tool-response edits (interceptors), pin down the match +
  the splice.** This is about quietly tampering with what a tool
  hands back before the agent sees it, so the runner needs three
  things nailed down. Ask them in plain words, leaning on recon:
  1. "Which tool's reply gets tampered with, and which part of what
     it hands back carries the attacker's content? In this benchmark
     it looks like <plain description from recon — e.g. 'the
     get-received-emails tool, and the content goes into a matched
     email's body'>. Sound right?" (Type-something.)
  2. "Should the tampering be the *same fixed edit* every single
     time, or should the attacking AI invent a fresh set of edits
     each round as part of its attempt? From the benchmark it looks
     like <fresh-each-round / fixed — state which from recon; for
     AgentDojo the attacker writes a fresh interceptor list every
     round>." (Closed-set: fixed vs fresh-each-round.)
  3. "And how does the content get spliced in — does it replace a
     little anchor marker in the reply, get tacked on the front
     or back, overwrite one specific field, or overwrite the whole
     matched item? From recon it looks like <inferred from recon>."
     (Closed-set over the built-in action kinds; `custom` always
     available.)
  ARCHITECT NOTE: each interceptor records a `match` (how to find the
  right object inside the reply) plus an `action` (how to splice).
    · `match`: use `field` / `object_id` / `static_match` for a
      fixed target, or their dynamic twins `field_source` /
      `object_id_source` (dotted paths) when the target itself is
      read per case or per attempt — never set both the static and
      the `*_source` form of the same key (the model XOR-rejects).
      Any `*_source` you set is checked by `validate_runtime_sources`.
    · `action.kind` is one of `replace_anchor` / `append` / `prepend`
      / `replace_field` / `overwrite_object` (or a custom kind →
      capture in extend.json); for `replace_anchor` also set
      `action.anchor` (default `{INJECTION}`); and `action.source`
      is REQUIRED — the dotted path to the text to splice.
    · **Fresh-each-round** (the common import case, AgentDojo): the
      attacking AI writes the whole interceptor list into `attack.json`
      each round, so DON'T author a static `tool_response_interceptors`
      list — instead set `runtime.tool_response_interceptors_from:
      attack.<field>` (AgentDojo: `attack.interceptors`, the Round-1
      controllable field). The per-interceptor `action.source` then
      typically points at `attack.<field>` too. `validate_runtime_sources`
      requires this dotted path resolve.
    · **Fixed** edits: author each entry under static
      `runtime.tool_response_interceptors`, with `action.source`
      pointing at `instance.<field>` (or a constant) — the validator
      requires every static `action.source` be set.
  - **How does the poisoned data reach the agent — spliced into a
    tool's live reply, or already sitting in the backend before the
    run?** Ask this only when the benchmark hands the agent an innocent
    task and the attack rides in on something it *reads* (the
    two-channels case). Two delivery modes that wire up differently:
    "From recon, when the agent reads the bad content, where was it a
    moment before? Two pictures: (A) the agent calls a tool — say
    'get my emails' — and the benchmark tampers with that *reply on the
    way back*, slipping the attacker's text in just before the agent
    sees it; or (B) before the run even starts, the benchmark *plants*
    a forged item — a fake email, a fake chat message — straight into
    the real backend it talks to, and the agent then reads it through
    its normal tools with no tampering at all. From recon it looks like
    <inferred>." Picker — three options:
      · "Spliced into a tool's reply on the fly (we edit the response)"
      · "Planted in the backend before the run (forged email / message
         the agent then reads normally)"
      · "…or does the benchmark get the poisoned data in front of the
         agent some *other* way I should wire up specially? (not a reply
         we splice, not a backend item we pre-plant)"
    ARCHITECT NOTE — RECORD which delivery mode into the contract:
      · **(A) tool-response splice** (agentdyn / AgentDojo) — the
        interceptor path above: the controllable field the attacker
        writes is `interceptors`, so include `interceptors` in
        `attacker_surface.controllable_fields`, and set the runtime
        binding `runtime.tool_response_interceptors_from:
        attack.interceptors`. No host hook.
      · **(B) backend pre-plant** (dtagent / DTap) — there is NO
        interceptor; the injection is PLANTED into the live backend
        host-side before the victim runs. The controllable field the
        attacker writes is `injection_steps`, so include
        `injection_steps` in `attacker_surface.controllable_fields`,
        and set the runtime binding `runtime.tool_env.inject_hook`
        (the `module:func` host hook that plants it, e.g.
        `plugins.scenarios.dtagent.inject:apply_injection`). This mode
        only fits when `tool_env.type: docker_compose_backend` with a
        `reset_hook` is already set (the backend question above) — the
        hook runs AFTER that reset, BEFORE the victim.
      · **(C) something new** — the benchmark delivers the poison in a
        way that is neither a tool-reply splice nor a backend pre-plant
        (e.g. the poison arrives over a side channel, gets injected by a
        peer agent, or rides in through some transport we don't model
        yet). This is a genuinely *custom* delivery kind. Ask one
        Type-something: "Describe in your own words how the benchmark
        gets the poisoned data in front of the agent — where it comes
        from and what moves it there — and I'll wire it up specially."
        Then pick a short custom slug for it and emit a dedicated entry
        to `/tmp/<scenario_name>.extend.json` with `surface:
        runner.indirect_delivery` (name = the custom slug, description =
        the user's plain-words account, fields = any config they gave)
        so `/scenario-extend` adds the matching delivery branch. Do NOT
        route this through the generic Round-7 "Other" picker (which
        records `surface: contract.RuntimeSpec`) — that's the wrong
        surface and the extend step won't add a delivery branch. Set
        NEITHER `tool_response_interceptors_from` NOR `inject_hook` for
        this case; the custom slug is the only delivery binding.
    These three are mutually exclusive per indirect attack: pick exactly
    one of (A) splice / (B) pre-plant / (C) custom. Do not set both a
    `tool_response_interceptors_from` and an `inject_hook` for the same
    delivery, do not pair either with a (C) custom slug, and do not
    invent an `inject_hook` for a benchmark whose indirect content
    arrives via interceptors, or vice versa.

- **Anything else this scenario needs at runtime?** Walk guided
  questions one at a time, never dump all examples at once.
  Start with a single Y/N gate:

  > "We've covered the usual moving parts. Is there anything *else*
  > this benchmark needs to run that we haven't touched on? Totally
  > fine if not — most imports are fully covered by now." Y/N

  If **N**: skip; no entries.

  If **Y**: walk these one at a time as plain Y/N questions, each
  with a Type-something follow-up on Y:
    1. "Does anything need to carry over between attempts — does the
       attacker build on what happened last round, rather than each
       try starting fresh?"
    2. "Any timing tricks — attacks that fire on a delay, or only
       after the agent's been running a while?"
    3. "Want any extra logging or measurements beyond the normal
       transcript we already record?"
    4. "Any network or sandbox rules — does the agent need internet,
       or should it be locked down a certain way?"
    5. "Any special settings for the target agent itself — a
       particular temperature, token budget, system prompt tweak?"
    6. "Does the benchmark involve *more than one* agent — agents
       talking to each other, or one handing off to another?"
    7. "Anything else at all we haven't covered?"

  Emit one `surface: contract.RuntimeSpec` entry per described
  dimension. `/scenario-extend` Step 3f handles each.

**Round 7 — final review**:
- Show the draft `contract.yaml` and the `convert.py` skeleton.
  Include the runtime block (which may be near-empty if the user
  picked no optional dimensions — that's valid).
- Ask, in plain words: "Here's the whole thing drafted from the
  benchmark — the contract that describes the scenario, plus the
  converter that pulls the data in. Take a look: does it match the
  benchmark you had in mind? You can sign off, tweak the contract,
  tweak the converter, or have me redo a piece." Picker options:
  approve / patch contract / patch converter / regenerate. Loop
  until approved.

### Step 3 — Draft `convert.py`

Pick the recipe template matching `upstream_type`:
- `templates/scenario-import-recipes/convert_pip_package.py.j2`
- `templates/scenario-import-recipes/convert_git_clone.py.j2`
- `templates/scenario-import-recipes/convert_hf_dataset.py.j2`
- `templates/scenario-import-recipes/convert_local_files.py.j2`

Customize:
- Upstream import / enumeration block (recipe-specific)
- Per-record extraction → `{researcher_view: {...}, evaluator_only: {...}, category: "..."}`
- Stage-1/held-out split logic: if upstream has its own split, **honour it** (don't randomly resplit a published benchmark). If not, default to 90/10 stratified random with `--seed 0`.
- Write the four output files: `train.json`, `heldout.json`, `clean/<cat>/<id>.json`, `clean_heldout/<cat>/<id>.json`, `judge_data.json` keyed by str(id).

Write the draft to `/tmp/<scenario_name>.convert.py.draft`.

### Step 4 — Validate each round

After every round (especially Round 4 and 5), validate the draft:

```bash
~/.local/bin/uv run python -c "from autoresearch_redteam.contract import load_contract; load_contract('/tmp/<scenario_name>.contract.yaml.draft')"
~/.local/bin/uv run python -m py_compile /tmp/<scenario_name>.convert.py.draft
```

If either fails, the next round's questions must target the failing
fields. Do not finalize until both validate.

### Step 5 — Return

Return a one-line summary like:
`"scenario-importer done: <scenario_name>, upstream=<type>, contract validates, convert.py compiles, expected N≈<count> instances"`

## Hard rules

- DO NOT invent any record content. If the upstream has 200 records,
  produce a converter for 200 records; don't synthesize the missing
  ones to round up the count.
- DO NOT resplit a benchmark that ships its own official split.
  Preserve upstream's split as-is.
- DO NOT pick judge type ahead of asking. Some benchmarks expect
  LLM-prompt judges (AHZ, HarmBench); others expect pure-logic
  (AgentDojo function-call match, AdvBench string-match).
- DO NOT skip the field-visibility split. Every upstream field must
  end up on one side of the partition; ask explicitly when ambiguous.
- DO NOT materialize the plugin or run convert.py — that's the skill's
  Step 5/6 job. You only write the two `/tmp/*.draft` files.
- DO NOT touch `plugins/scenarios/<scenario_name>/` directly; even if
  the directory exists from a prior attempt, only the skill writes
  there.

## Failure modes you should surface clearly

- Upstream has no clear "record" granularity → ask the user to pick:
  per-(prompt, target) pair, per-task, per-conversation.
- Upstream's licence is unclear or restrictive → ask whether to proceed
  and add `licence: <upstream-licence>` to contract.
- Upstream judge code is not faithfully replicable in pure Python →
  flag as `judge.rule: <name>` with a `VICTIM_INTEGRATION_NOTES.md`
  note (mirror AgentDojo's pattern).
