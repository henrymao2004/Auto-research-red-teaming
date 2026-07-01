# Contributing

Contributions should keep the harness reproducible, inspectable, and
safe to run on a local machine.

## Add a scenario

Preferred paths:

```text
/scenario-build "<short idea>"
/scenario-import "<name> from <upstream>"
```

Manual path:

```bash
cd autoresearcher
./scripts/add_scenario.sh <name>
```

Then fill:

- `plugins/scenarios/<name>/contract.yaml`
- `scenario.py`
- `scenario.yaml`
- `judge.py`
- `clean/`, `clean_heldout/`, `train.json`, `heldout.json`,
  `judge_data.json`

Use `templates/scenario-minimal/` for a small reference layout and
`docs/BYO_SCENARIO.md` for the contract details.

## Add a victim

```bash
cd autoresearcher
./scripts/add_victim.sh <name>
```

Then implement:

- `victim.yaml`
- `adapter.py`
- optional `docker/` assets

Use `templates/victim-minimal/` as the smallest adapter shape. Victims
should return the canonical trajectory JSON and should not write the
input attack spec into the agent-visible workspace.

## Smoke tests

Run before opening a PR:

```bash
bash autoresearcher/scripts/dry_run.sh
bash autoresearcher/scripts/doctor.sh
PYTHONPATH=autoresearcher/src python3 -m autoresearch_redteam.run_attack --list
bash -n autoresearcher/scripts/*.sh
```

For Python files you changed:

```bash
python3 -m py_compile path/to/file.py
```

If you changed JSON/YAML data, parse it locally before committing.

## Style

- Keep comments short and operational.
- Do not commit real API keys or endpoint credentials.
- Keep generated run artifacts out of commits unless they are documented
  examples.
- Prefer focused PRs: one scenario, one victim, or one infrastructure
  change at a time.
