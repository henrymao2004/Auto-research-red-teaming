# 5-minute dry run

This is an offline smoke test for a fresh checkout. It does not start
DTap backends, does not call a model endpoint, and does not run a real
victim. It verifies that the Python package imports, the registry loads,
AgentHazard data is present, and a one-iteration run artifact can be
rendered.

```bash
git clone https://github.com/henrymao2004/Auto-research-red-teaming.git
cd Auto-research-red-teaming
uv venv && source .venv/bin/activate && uv pip install -e .

bash autoresearcher/scripts/dry_run.sh
```

Expected output ends with:

```text
[dry-run] OK
[dry-run] summary: .../autoresearcher/.dry_run/attacks/dry_run_5min/SUMMARY.md
```

The script writes:

- `autoresearcher/.dry_run/.env.dryrun` — fake endpoint values that are
  never used for network calls.
- `autoresearcher/.dry_run/attacks/dry_run_5min/v1/` — one synthetic
  AgentHazard-style iteration.
- `autoresearcher/.dry_run/attacks/dry_run_5min/SUMMARY.md` — rendered
  summary output.

After this passes, run:

```bash
bash autoresearcher/scripts/doctor.sh
```

`doctor.sh` checks Docker, model environment variables, scenario images,
DTap backend ports, and benchmark seed strings. Warnings are expected on
a laptop before you build images or start DTap.
