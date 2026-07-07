"""{SCENARIO_NAME_CAMEL} scenario plugin.

Thin :class:`ContractDrivenScenario` subclass. Everything declarative
lives in ``contract.yaml``; this file only wires the scenario-specific
``judge_trajectory`` over to ``judge.py`` (generated alongside this
file by ``/scenario-build`` or ``/scenario-import``).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from autoresearch_redteam.contract_driven_scenario import ContractDrivenScenario

from .judge import judge_trajectory as _judge_trajectory


HERE = Path(__file__).resolve().parent


class {SCENARIO_NAME_CAMEL}Scenario(ContractDrivenScenario):
    name = "{scenario_name}"
    contract_path = HERE / "contract.yaml"
    _plugin_root = HERE

    def judge_trajectory(
        self,
        instance: dict[str, Any],
        trajectory_payload: dict[str, Any],
        *,
        judge_model: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        # Dispatch to the generated judge.
        return _judge_trajectory(
            instance=instance,
            trajectory_payload=trajectory_payload,
            judge_model=judge_model,
            api_key=api_key,
            base_url=base_url,
        )
