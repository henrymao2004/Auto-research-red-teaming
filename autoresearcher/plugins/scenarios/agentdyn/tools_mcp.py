"""MCP server exposing AgentDojo suite tools to claude-agent-sdk.

Each :class:`agentdojo.functions_runtime.Function` in the suite becomes a
claude-agent-sdk ``@tool`` whose input schema is the function's pydantic
``parameters`` schema. All tools close over one hydrated
``TaskEnvironment`` per attack run, so stateful tools mutate a single
consistent world, and that environment is returned so the runner can
serialise it as ``post_environment`` for the judge. Tool return values are
coerced to MCP text blocks by :func:`_to_text`.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


DEFAULT_BENCHMARK_VERSION = "v1.2.2"


def build_mcp_server(
    instance: dict[str, Any],
    env_state: dict[str, Any],
    *,
    benchmark_version: str = DEFAULT_BENCHMARK_VERSION,
):
    """Build an MCP server exposing the upstream agentdojo tools for one instance.

    Args:
        instance: full per-instance dict; must contain ``"suite"`` (one
            of ``shopping`` / ``github`` / ``dailylife``).
        env_state: the ``environment_snapshot`` dict (researcher-visible
            keys; pydantic-instantiable into the suite's
            ``environment_type``).
        benchmark_version: agentdojo benchmark version tag the dataset
            was extracted with.

    Returns:
        ``(server, env)``: an ``McpSdkServerConfig`` for
        ``ClaudeAgentOptions.mcp_servers`` and the hydrated environment the
        tools mutate in place (the post-attack environment after the run).
    """
    from claude_agent_sdk import create_sdk_mcp_server

    sdk_tools, env = build_tools(
        instance, env_state, benchmark_version=benchmark_version,
    )
    server = create_sdk_mcp_server(
        name=f"agentdojo_{instance['suite']}",
        version="1.0.0",
        tools=sdk_tools,
    )
    return server, env


def build_tools(
    instance: dict[str, Any],
    env_state: dict[str, Any],
    *,
    benchmark_version: str = DEFAULT_BENCHMARK_VERSION,
):
    """Return ``(sdk_tools, env)``: the wrapped suite tools and the environment they mutate.

    :func:`build_mcp_server` serves these in-process for claude_code; the
    codex STDIO MCP server uses them directly.
    """
    from agentdojo.task_suite.load_suites import get_suite

    suite_name = instance["suite"]
    suite = get_suite(benchmark_version, suite_name)

    env = suite.environment_type(**env_state)

    allowed = set(instance.get("available_tools") or [])
    sdk_tools = []
    skipped: list[tuple[str, str]] = []
    for upstream_t in suite.tools:
        if allowed and upstream_t.name not in allowed:
            continue
        try:
            sdk_tools.append(_wrap_tool(upstream_t, env))
        except Exception as exc:  # noqa: BLE001
            skipped.append((upstream_t.name, repr(exc)))
            logger.warning("agentdojo tools_mcp: skipped %s (%s)", upstream_t.name, exc)

    if skipped:
        logger.warning("agentdojo tools_mcp: %d tools skipped: %s", len(skipped), skipped)

    return sdk_tools, env


def _wrap_tool(upstream_t, env):
    """Wrap one agentdojo ``Function`` as a claude-agent-sdk ``@tool`` async callable.

    Arguments are validated against the function's ``parameters`` model and
    dependencies (e.g. ``inbox=env.inbox``) are bound from the shared ``env``.
    Validation and runtime errors are returned as ``isError=True`` tool
    responses carrying the exception text, the same way agentdojo's
    ``FunctionsRuntime`` reports them.
    """
    from claude_agent_sdk import tool

    schema = upstream_t.parameters.model_json_schema()
    _strip_schema_titles(schema)

    name = upstream_t.name
    description = upstream_t.description
    parameters_cls = upstream_t.parameters
    dependencies = upstream_t.dependencies
    run = upstream_t.run

    @tool(name, description, schema)
    async def _impl(args: dict[str, Any]) -> dict[str, Any]:  # noqa: ANN401
        try:
            validated = parameters_cls.model_validate(args).model_dump()
        except Exception as exc:  # noqa: BLE001 - validation surfaces as a tool error
            return {
                "content": [{"type": "text", "text": f"ValidationError: {exc}"}],
                "isError": True,
            }

        env_kwargs = {
            arg_name: dep.extract_dep_from_env(env)
            for arg_name, dep in dependencies.items()
        }

        try:
            result = run(**validated, **env_kwargs)
        except Exception as exc:  # noqa: BLE001
            return {
                "content": [{"type": "text", "text": f"{type(exc).__name__}: {exc}"}],
                "isError": True,
            }

        return {"content": [{"type": "text", "text": _to_text(result)}]}

    return _impl


def _strip_schema_titles(schema: dict[str, Any]) -> None:
    """Recursively drop pydantic's auto-generated ``"title"`` keys, which add noise to the tool schema."""
    if isinstance(schema, dict):
        schema.pop("title", None)
        for v in schema.values():
            _strip_schema_titles(v)
    elif isinstance(schema, list):
        for v in schema:
            _strip_schema_titles(v)


def _to_text(value: Any) -> str:
    """Serialise a tool return value to text: pydantic models via ``model_dump_json``, else ``json.dumps``, else ``str``."""
    try:
        from pydantic import BaseModel
    except Exception:  # noqa: BLE001
        BaseModel = None  # type: ignore[assignment]

    if BaseModel is not None and isinstance(value, BaseModel):
        return value.model_dump_json(indent=2)

    def _default(o: Any) -> Any:
        if BaseModel is not None and isinstance(o, BaseModel):
            return json.loads(o.model_dump_json())
        return str(o)

    try:
        return json.dumps(value, indent=2, default=_default, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return str(value)


__all__ = ["build_mcp_server", "build_tools", "DEFAULT_BENCHMARK_VERSION"]
