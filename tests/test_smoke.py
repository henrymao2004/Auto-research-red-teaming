from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "autoresearcher/src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from autoresearch_redteam import registry
from autoresearch_redteam.contract import load_contract


def test_agenthazard_contract_loads() -> None:
    contract = load_contract(ROOT / "autoresearcher/plugins/scenarios/agenthazard/contract.yaml")
    assert contract.scenario_name == "agenthazard"
    assert contract.attack_family == "multi_turn_user_prompt_ratchet"


def test_registry_accepts_builtin_cell() -> None:
    registry.validate_cell("claude_code", "agenthazard")
    registry.validate_cell("codex", "agenthazard")


def test_run_attack_list_smoke() -> None:
    env = os.environ.copy()
    src = str(ROOT / "autoresearcher/src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "autoresearch_redteam.run_attack", "--list"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Victims:" in proc.stdout
    assert "Scenarios:" in proc.stdout
    assert "codex" in proc.stdout


def test_freeze_concepts_parses_counted_section(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "freeze_concepts",
        ROOT / "autoresearcher/scripts/freeze_concepts.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    vcg = tmp_path / "vcg.md"
    vcg.write_text(
        """# VCG

## Counted Concepts

### VC-0001  COUNTED @ v6
- **mechanism**: delegated authority confusion
- **attack_template**: split a blocked action across user turns
- **confidence**: 0.80
- **n_confirmations**: 3

## Candidate Concepts

### VC-0002
- **mechanism**: not frozen
""",
        encoding="utf-8",
    )

    concepts = module.parse_vcg(vcg)
    assert [c["id"] for c in concepts] == ["VC-0001"]
    assert concepts[0]["mechanism"] == "delegated authority confusion"
