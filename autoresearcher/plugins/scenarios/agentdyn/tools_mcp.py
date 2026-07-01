"""MCP-server façade exposing upstream AgentDojo tools to claude-agent-sdk.

The in-container runner drives the victim by handing it a list of
``McpSdkServerConfig`` objects via ``ClaudeAgentOptions.mcp_servers``.
This module turns each upstream :class:`agentdojo.functions_runtime.Function`
into a claude-agent-sdk ``@tool``-decorated callable, all sharing the
same hydrated :class:`agentdojo.functions_runtime.TaskEnvironment`
instance so stateful tools (``send_email`` → append to inbox,
``create_file`` → append to drive, …) mutate one consistent world for
the duration of a single attack run.

Public entry point:
    :func:`build_mcp_server(instance, env_state)`

which returns a ``(McpSdkServerConfig, env)`` tuple. The server is
plugged into ``ClaudeAgentOptions.mcp_servers``; the ``env`` is the
hydrated pydantic :class:`agentdojo.functions_runtime.TaskEnvironment`
that the wrapped tools mutate during the run — i.e. the *post-attack*
environment once the agent finishes. The runner serializes it
(``env.model_dump(mode='json')``) into the trajectory so the upstream
``injection_task.security`` / ``user_task.utility`` judge can run over
the pre/post environment pair.

Design notes
------------
* Upstream's :class:`Function` already carries:

  - ``name``          → MCP tool name (1:1, no prefix needed; the
    server name namespaces these on the SDK side).
  - ``description``   → MCP tool description.
  - ``parameters``    → Pydantic model class. We feed its
    ``model_json_schema()`` directly to ``@tool``'s ``input_schema``
    argument — claude-agent-sdk accepts a JSON-Schema dict.
  - ``dependencies``  → ``{arg_name: Depends(env_attr)}``. The wrapper
    binds the same ``env`` per call and injects these as kwargs the
    way upstream's :class:`FunctionsRuntime` does.

* Stateful tools mutate ``env`` by way of pydantic sub-models
  (Inbox / Calendar / CloudDrive / BankAccount / …). We instantiate
  ``env`` once per :func:`build_mcp_server` call and capture it in
  every wrapper closure → every tool call in a run sees & mutates the
  exact same world. The in-container runner calls
  :func:`build_mcp_server` once per attack run (per instance), so there
  is no cross-run state bleed.

* Return values from upstream tools can be:
  - a Pydantic ``BaseModel`` (e.g. ``Email``),
  - a list of such,
  - a dict / str / int / bool / None.

  MCP requires the response ``content`` to be a list of ``{"type":
  "text", "text": str}``-shaped blocks. We coerce every return value
  through :func:`_to_text` which uses ``model_dump_json`` for Pydantic
  objects and ``json.dumps(default=str)`` for everything else (date /
  datetime / Enum show up in AgentDojo payloads).
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
        benchmark_version: agentdojo benchmark version tag; pinned to
            the version the dataset was extracted from (see
            ``scenario.yaml`` for provenance).

    Returns:
        A ``(server, env)`` tuple where ``server`` is an
        ``McpSdkServerConfig`` ready to pass to
        ``ClaudeAgentOptions.mcp_servers`` and ``env`` is the hydrated
        pydantic ``suite.environment_type`` instance that the wrapped
        tools mutate in place. After the agent run, ``env`` is the
        post-attack environment; the runner serializes it for the
        upstream security/utility judge.
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
    """Build the wrapped scenario tools + the hydrated env, drive-layer-agnostic.

    Returns a ``(sdk_tools, env)`` tuple where ``sdk_tools`` is a list of
    claude-agent-sdk :class:`SdkMcpTool` instances (each carries
    ``name`` / ``description`` / ``input_schema`` / ``handler``) and
    ``env`` is the hydrated pydantic ``suite.environment_type`` that the
    tools mutate in place (the post-attack environment for the judge).

    :func:`build_mcp_server` wraps these into a claude-SDK in-process
    server for the claude_code victim. Other victims (e.g. the codex
    STDIO MCP server) consume the same ``(sdk_tools, env)`` directly:
    each tool's ``handler`` is the identical closure, so the tool world
    + post-environment behaviour is shared across victims — only the
    serving transport differs.
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
    """Wrap one upstream :class:`agentdojo.functions_runtime.Function`
    as a claude-agent-sdk ``@tool``-decorated async callable.

    The wrapper:

    1. Receives ``args: dict`` from the MCP runtime (already JSON-decoded).
    2. Validates ``args`` against the upstream tool's pydantic
       ``parameters`` model → dumps to a plain dict (drops aliases,
       fills defaults).
    3. Resolves dependencies (e.g. ``inbox=env.inbox``) from the closed-over
       ``env`` — mutations through these refs propagate across calls.
    4. Calls ``upstream_t.run(**args, **env_args)`` and returns its
       value, wrapped in the MCP content envelope.

    Errors are caught and returned as ``isError=True`` MCP responses
    rather than raising — matches upstream FunctionsRuntime's
    "return the exception text as a tool message" semantics, which is
    what real-world agentdojo trajectories see.
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
    """Recursively drop ``"title"`` keys from a JSON-Schema dict.

    Pydantic-generated schemas tag every field & nested object with a
    Pascal-Case title that's mostly noise to the LLM ("Bcc",
    "Recipients"). Removing them tightens the tool description without
    changing semantics.
    """
    if isinstance(schema, dict):
        schema.pop("title", None)
        for v in schema.values():
            _strip_schema_titles(v)
    elif isinstance(schema, list):
        for v in schema:
            _strip_schema_titles(v)


def _to_text(value: Any) -> str:
    """Serialise an upstream tool return value to a text payload.

    Order of preference:

    1. pydantic ``BaseModel`` → ``model_dump_json(indent=2)`` —
       preserves the schema-stable JSON form upstream uses internally.
    2. list / dict of pydantic-or-json-native → ``json.dumps`` with
       a ``default=`` that handles datetime / date / Enum / pydantic.
    3. native JSON types → ``json.dumps``.
    4. backup → ``str(value)``.
    """
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
