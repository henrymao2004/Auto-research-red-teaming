"""Plugin Protocols for Scenario / Victim / Researcher (duck-typed, no ABC check)."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class VictimAdapter(Protocol):
    name: str
    default_model: str
    supports_attack_families: tuple[str, ...]

    def __init__(self, *, model: str = ..., **kwargs: Any) -> None: ...
    def run(self, input_spec: dict[str, Any]) -> dict[str, Any]:
        """Spawn the victim once and return the parsed trajectory payload."""
        ...


class Scenario(Protocol):
    name: str
    native_attack_family: str
    attack_schema: dict[str, Any]
    subagent_blurb: str
    categories: list[str]
    train_path: Path
    heldout_path: Path

    def load_instance(self, instance_id: int) -> dict[str, Any]: ...
    def classify_instance(self, instance_id: int) -> str:
        """Return 'train' | 'held_out' | 'unknown'."""
        ...
    def build_input_spec(
        self, attack: dict[str, Any], instance: dict[str, Any], model: str,
    ) -> dict[str, Any]: ...
    def judge_trajectory(
        self, instance: dict[str, Any], trajectory_payload: dict[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]: ...


class ResearcherAgent(Protocol):
    name: str
    agents_dir: Path
