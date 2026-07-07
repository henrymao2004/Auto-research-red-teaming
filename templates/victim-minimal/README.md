# Minimal victim template

Copy this directory to `autoresearcher/plugins/victims/<name>/` when
adding a new victim agent. Prefer a Docker adapter so every attack gets a
fresh workspace and the trajectory shape is consistent.

Files:

- `victim.yaml.template` — registry manifest.
- `adapter.py.template` — host-side adapter skeleton.

After copying:

```bash
cd autoresearcher
PYTHONPATH=src python3 -m autoresearch_redteam.run_attack --list
```
