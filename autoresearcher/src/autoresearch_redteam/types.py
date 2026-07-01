"""Minimal Pydantic types for the target/judge contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    id: str = ""


class CriterionResult(BaseModel):
    name: str
    judge: str
    score: float
    threshold: float
    passed: bool


class EvalResult(BaseModel):
    behavior_id: str
    model: str
    break_: bool = Field(alias="break")
    criteria: list[CriterionResult] = Field(default_factory=list)
    turns: int = 0
    tool_calls: list[str] = Field(default_factory=list)
    raw_trajectory: list[dict[str, Any]] = Field(default_factory=list)
    raw_payload: dict[str, Any] | None = None
    model_response: str | None = None
    reasoning: str | None = None
    usage: dict[str, int] = Field(default_factory=dict)
    duration_seconds: float = 0.0
    error: str | None = None

    model_config = {"populate_by_name": True}
