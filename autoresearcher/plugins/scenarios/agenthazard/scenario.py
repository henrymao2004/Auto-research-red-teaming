"""AgentHazard scenario plugin.

A thin :class:`ContractDrivenScenario` subclass: ``contract.yaml``
declares the attack family, payload schema, sub-agent blurb shape,
researcher-visible / evaluator-only field partition, and judge rule.
The base class derives ``attack_schema``, ``subagent_blurb``,
``categories``, the dataset paths, and the default
``build_input_spec`` from that contract.

Only the judge wiring is scenario-specific (the AHZ official LLM-judge
prompt lives in ``judge/agenthazard_official.md`` and is hashed in the
contract).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from autoresearch_redteam.contract_driven_scenario import ContractDrivenScenario

from .judge import judge_trajectory as _judge_trajectory


HERE = Path(__file__).resolve().parent


class AgentHazardScenario(ContractDrivenScenario):
    name = "agenthazard"
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
        return _judge_trajectory(
            instance=instance,
            trajectory=trajectory_payload.get("assistant_messages", []),
            judge_model=judge_model,
            api_key=api_key,
            base_url=base_url,
        )
