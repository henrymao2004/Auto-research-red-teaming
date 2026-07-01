"""Tool-call normalization helpers for scenario judges."""
from __future__ import annotations

import json
from typing import Any


def normalize_observed_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    function_obj = call.get("function")
    name = call.get("name")
    if not name:
        if isinstance(function_obj, dict):
            name = function_obj.get("name")
        else:
            name = function_obj

    arguments = call.get("arguments")
    if arguments is None:
        arguments = call.get("args")
    if arguments is None and isinstance(function_obj, dict):
        arguments = function_obj.get("arguments")

    if isinstance(arguments, str):
        try:
            parsed = json.loads(arguments)
            arguments = parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            arguments = {}
    if not isinstance(arguments, dict):
        arguments = {}

    # Normalize MCP tool names.
    name = str(name or "")
    if name.startswith("mcp__"):
        name = name.split("__", 2)[-1]

    return {
        "name": name,
        "arguments": arguments,
        "id": call.get("id", ""),
    }


__all__ = ["normalize_observed_tool_call"]
