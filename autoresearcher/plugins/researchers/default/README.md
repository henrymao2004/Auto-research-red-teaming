# default researcher agent

The default 4-agent roster: Hypothesizer → Attack-Designer → Reflector
→ (every 10 iter) Critic. This is one **researcher agent** plugin (the
attack-discovery method). Used by the `autoresearch-redteam` skill.

The agents themselves are victim-agent-, victim-model-, and
scenario-agnostic: all scenario-specific context (attack family blurb,
attack JSON schema, instance file path, category list) is passed in by
the dispatch prompt that the skill builds from the registry-resolved
scenario plugin.

To ship a different research method (different sub-agent roster — e.g.
single-judge vs. dual-judge audit, or a research method without a
Critic), drop a sibling directory under `plugins/researchers/<name>/`
with an `agents/*.md` set; the skill's `--researcher <name>` flag
selects which one to copy into `.claude/agents/` at run launch time.
