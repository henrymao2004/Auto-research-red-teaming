# Minimal scenario template

Copy this directory to `autoresearcher/plugins/scenarios/<name>/` when
you want to hand-author a very small scenario. The guided paths
`/scenario-build` and `/scenario-import` are preferred for normal use.

Files:

- `scenario.yaml.template` — plugin manifest.
- `contract.yaml` — minimal contract skeleton.
- `scenario.py.template` — thin `ContractDrivenScenario` subclass.
- `judge.py.template` — rule-based judge stub.

After copying:

```bash
cd autoresearcher
PYTHONPATH=src python3 -m autoresearch_redteam.run_attack --list
```
