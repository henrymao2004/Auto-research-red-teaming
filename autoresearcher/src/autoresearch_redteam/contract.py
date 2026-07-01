"""Scenario Contract — the single declarative description of a scenario."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttackerSurface(_Base):
    model_config = ConfigDict(extra="allow")

    type: str
    controllable_fields: list[str] = Field(min_length=1)


class PayloadSchema(BaseModel):
    """Shape of the attack.json researchers produce; ``type`` is a tag, extra keys are family-specific."""

    model_config = ConfigDict(extra="allow")
    type: str


class VictimEnvironment(_Base):
    model_config = ConfigDict(extra="allow")

    agent_type: str
    tools: list[str] = Field(default_factory=list)
    seed_data: str | None = None  # Deprecated field.
    setup: str | None = None


class SuccessCriterion(_Base):
    model_config = ConfigDict(extra="allow")

    type: str
    description: str
    metrics: list[str] = Field(default_factory=list)


class TrajectoryObservation(_Base):
    model_config = ConfigDict(extra="allow")

    collect: list[str] = Field(min_length=1)


class Judge(_Base):
    """How a finished trajectory is scored."""

    model_config = ConfigDict(extra="allow")

    mode: Literal["scenario", "per_instance"] = "scenario"
    type: str
    rule: str
    prompt_template: str | None = None
    prompt_hash: str | None = None


class AttackWiring(_Base):
    """How the attack payload reaches the agent at runtime; ``kind`` is open, custom kinds dispatch to runtime_hooks."""

    model_config = ConfigDict(extra="allow")

    kind: str
    source: str = ""
    max_turns_per_user_msg: int = 25


class EnvironmentHydration(_Base):
    """Pre-populate the agent's tool world before the run; built-in kinds none/from_instance_field/inline_yaml/callback."""

    model_config = ConfigDict(extra="allow")

    kind: str
    source: str | None = None
    inline: dict[str, Any] | None = None
    callback_module: str | None = None


class InterceptorMatch(_Base):
    """How to find the right object inside a tool's response; static XOR *_source resolution."""

    object_id_source: str | None = None
    object_id: str | None = None
    field_source: str | None = None
    field: str | None = None
    static_match: str | None = None

    @model_validator(mode="after")
    def _xor_check(self) -> "InterceptorMatch":
        if self.object_id_source and self.object_id:
            raise ValueError("specify object_id OR object_id_source, not both")
        if self.field_source and self.field:
            raise ValueError("specify field OR field_source, not both")
        return self


class InterceptorAction(_Base):
    """Built-in kinds replace_anchor/append/prepend/replace_field/overwrite_object; custom kinds dispatch to runtime_hooks."""

    model_config = ConfigDict(extra="allow")

    kind: str
    anchor: str = "{INJECTION}"
    source: str


class ToolResponseInterceptor(_Base):
    """Splice attack content into a specific tool's response data at runtime."""

    tool: str
    match: InterceptorMatch
    action: InterceptorAction


class TrajectoryCapture(_Base):
    """What to record in trajectory.json; unknown keys dispatch to runtime_hooks.transform_trajectory."""

    model_config = ConfigDict(extra="allow")

    include: list[str] = Field(default_factory=lambda: [
        "model_messages", "tool_calls", "tool_outputs", "final_answer"
    ])


class ToolEnv(BaseModel):
    """What BACKS the victim's tools at runtime (agent_builtin / in_process_pkg / docker_compose_backend)."""

    model_config = ConfigDict(extra="allow")

    type: Literal["agent_builtin", "in_process_pkg", "docker_compose_backend"]
    reset_hook: str | None = None
    inject_hook: str | None = None


class RuntimeSpec(BaseModel):
    """Declarative runtime spec — the only mode; extra="allow" so scenarios add custom dimensions via /scenario-extend."""

    model_config = ConfigDict(extra="allow")

    docker_image: str | None = None
    tool_env: ToolEnv | None = None
    disallowed_tools: list[str] = Field(default_factory=list)
    mcp_tools_module: str | None = None
    attack_wiring: AttackWiring | None = None
    environment_hydration: EnvironmentHydration = Field(
        default_factory=lambda: EnvironmentHydration(kind="none")
    )
    tool_response_interceptors: list[ToolResponseInterceptor] = Field(default_factory=list)
    tool_response_interceptors_from: str | None = None
    trajectory_capture: TrajectoryCapture = Field(default_factory=TrajectoryCapture)


class ScenarioContract(_Base):
    """The full contract; one per scenario plugin."""

    scenario_name: str
    version: str
    attack_family: str

    victim_scope: list[str] = Field(default_factory=lambda: ["claude_code"])

    attacker_surface: AttackerSurface
    payload_schema: PayloadSchema
    victim_environment: VictimEnvironment

    researcher_visible_fields: list[str] = Field(min_length=1)
    evaluator_only_fields: list[str] = Field(default_factory=list)

    synth_requirements: dict[str, Any] | None = None
    instance_schema: dict[str, Any] | None = None  # Instance JSON Schema.

    success_criterion: SuccessCriterion
    trajectory_observation: TrajectoryObservation
    judge: Judge
    runtime: RuntimeSpec

    @model_validator(mode="after")
    def _visibility_partition(self) -> "ScenarioContract":
        overlap = set(self.researcher_visible_fields) & set(self.evaluator_only_fields)
        if overlap:
            raise ValueError(
                "researcher_visible_fields and evaluator_only_fields must be "
                f"disjoint; overlap = {sorted(overlap)}"
            )
        return self


def compute_prompt_hash(path: Path) -> str:
    """SHA-256 hex of a prompt file's bytes, for `judge.prompt_hash`."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_contract(path: Path | str) -> ScenarioContract:
    """Parse `contract.yaml`, validate, and check judge prompt hash."""
    import yaml

    p = Path(path)
    raw = yaml.safe_load(p.read_text())
    contract = ScenarioContract.model_validate(raw)

    if contract.judge.prompt_template:
        prompt_path = p.parent / contract.judge.prompt_template
        if not prompt_path.exists():
            raise FileNotFoundError(
                f"judge.prompt_template points at {prompt_path} which does not exist"
            )
        actual = compute_prompt_hash(prompt_path)
        if contract.judge.prompt_hash and contract.judge.prompt_hash != actual:
            raise ValueError(
                f"judge.prompt_hash mismatch for {prompt_path}: "
                f"contract says {contract.judge.prompt_hash[:16]}…, "
                f"file is {actual[:16]}…. "
                f"Re-stamp the contract or revert the prompt."
            )
    return contract


def validate_runtime_sources(contract: ScenarioContract) -> list[str]:
    """Static lint for the runtime source bindings; returns ERROR:/WARN: issue strings (empty = clean)."""
    issues: list[str] = []
    rt = contract.runtime

    instance_fields = set(contract.researcher_visible_fields) | set(
        contract.evaluator_only_fields
    )
    universal_metadata = {"instance_id", "category", "method_name"}
    payload_fields = (
        set(contract.attacker_surface.controllable_fields)
        | universal_metadata
        | set((contract.payload_schema.model_dump(exclude_none=True).get("json_schema") or {})
              .get("properties", {}).keys())
        | instance_fields
    )

    def _check(dotted: str | None, where: str, *, required: bool) -> None:
        if not dotted:
            if required:
                issues.append(
                    f"ERROR: {where} has no source — the runner will resolve an "
                    f"empty payload and the attack will silently do nothing. "
                    f"Set a dotted path like 'attack.<field>' or 'instance.<field>'."
                )
            return
        parts = dotted.split(".")
        root, seg = parts[0], (parts[1] if len(parts) > 1 else None)
        if root not in ("attack", "instance") or seg is None:
            issues.append(
                f"ERROR: {where} source '{dotted}' must start with 'attack.' or "
                f"'instance.' followed by a field name."
            )
            return
        pool = payload_fields if root == "attack" else instance_fields
        if seg not in pool:
            issues.append(
                f"WARN: {where} source '{dotted}' references {root} field "
                f"'{seg}', which is not in the declared "
                f"{'controllable/payload fields' if root == 'attack' else 'researcher_visible ∪ evaluator_only fields'}. "
                f"Typo, or did you forget to declare it?"
            )

    if rt.attack_wiring.kind != "environment_only":
        _check(rt.attack_wiring.source, "attack_wiring", required=True)

    eh = rt.environment_hydration
    if eh.kind == "from_instance_field":
        _check(eh.source, "environment_hydration (from_instance_field)", required=True)
    elif eh.kind == "inline_yaml" and not eh.inline:
        issues.append("ERROR: environment_hydration kind=inline_yaml but no 'inline' block was provided.")
    elif eh.kind == "callback" and not eh.callback_module:
        issues.append("ERROR: environment_hydration kind=callback but no 'callback_module' (module:func) was provided.")

    for i, ic in enumerate(rt.tool_response_interceptors):
        _check(ic.action.source, f"tool_response_interceptors[{i}].action", required=True)
        m = ic.match
        _check(getattr(m, "object_id_source", None), f"tool_response_interceptors[{i}].match.object_id_source", required=False)
        _check(getattr(m, "field_source", None), f"tool_response_interceptors[{i}].match.field_source", required=False)

    if rt.tool_response_interceptors_from:
        _check(rt.tool_response_interceptors_from, "tool_response_interceptors_from", required=True)

    return issues


__all__ = [
    "validate_runtime_sources",
    "AttackWiring",
    "AttackerSurface",
    "EnvironmentHydration",
    "InterceptorAction",
    "InterceptorMatch",
    "Judge",
    "PayloadSchema",
    "RuntimeSpec",
    "ScenarioContract",
    "SuccessCriterion",
    "ToolEnv",
    "ToolResponseInterceptor",
    "TrajectoryCapture",
    "TrajectoryObservation",
    "VictimEnvironment",
    "compute_prompt_hash",
    "load_contract",
]
