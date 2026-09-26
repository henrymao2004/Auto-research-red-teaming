"""AgentDyn scenario plugin (built on the AgentDojo fork).

Everything except the judge is derived from ``contract.yaml`` by
:class:`ContractDrivenScenario`; categories are the three suites (shopping,
github, dailylife). The in-container runner loads the MCP tools from
``contract.runtime.mcp_tools_module`` (:mod:`plugins.scenarios.agentdyn.tools_mcp`).
``judge_trajectory`` delegates to ``judge.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from autoresearch_redteam.contract_driven_scenario import ContractDrivenScenario

from .judge import judge_trajectory as _judge_trajectory


HERE = Path(__file__).resolve().parent


class AgentDynScenario(ContractDrivenScenario):
    name = "agentdyn"
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
            trajectory=trajectory_payload,
        )
