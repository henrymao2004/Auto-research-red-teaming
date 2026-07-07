"""AgentDyn scenario plugin (built on the AgentDojo fork).

A thin :class:`ContractDrivenScenario` subclass: ``contract.yaml``
declares the attack family (``indirect_prompt_injection``), the
single-string payload schema, researcher-visible / evaluator-only
field partition, and the upstream-security judge rule. The base
class derives ``attack_schema``, ``subagent_blurb``, ``categories``
(= the three AgentDyn suites: shopping, github, dailylife),
``build_input_spec``, and the dataset paths from the contract.
``judge_trajectory`` delegates to the upstream-security logic in
``judge.py`` (wraps ``injection_task.security`` + ``user_task.utility``).

The MCP server in :mod:`plugins.scenarios.agentdyn.tools_mcp` is
loaded by the in-container runner (the runner reads
``contract.runtime.mcp_tools_module``). This file no longer overrides
``build_input_spec`` — the contract-driven input spec built by
``run_attack._build_input_spec`` is sufficient. Only ``judge_trajectory``
remains, delegated to the local function-call-match logic in ``judge.py``.
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
