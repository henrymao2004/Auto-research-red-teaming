"""Generic STDIO MCP server that exposes a scenario's tools to **codex**.

The claude_code victim hands the scenario's tools to the agent via an
*in-process* claude-agent-sdk MCP server (``create_sdk_mcp_server``) and
applies IPI interceptors in a ``PostToolUse`` hook. codex has no such
hook and cannot host an in-process server — it spawns external MCP
servers over STDIO (declared as ``[mcp_servers.scenario_tools]`` in
``config.toml``). This module is that STDIO server.

It reuses the scenario unchanged: it imports the scenario's
``mcp_tools_module`` and calls ``build_tools(instance, env_state)`` —
the SAME closure-bound tool handlers + hydrated environment the
claude_code victim uses (see ``tools_mcp.build_tools``). The only
codex-specific delta is the transport (a real STDIO MCP server instead
of the in-process SDK server) and the **application point of the IPI
interceptors**: claude_code splices in its hook; here we splice each
tool's output inside ``call_tool`` — reusing ``runner_core``'s
``_apply_interceptor`` / ``_tool_name_matches`` verbatim, so the
``tool_response_interceptors`` contract is identical.

After every tool call we serialize the (mutated) environment to
``SCENARIO_MCP_POST_ENV`` so the host runner can attach it to the
trajectory as ``post_environment`` for the upstream-security judge —
the codex equivalent of claude_code's ``mcp_env.model_dump(...)``.

Launch contract (all via env vars, set by the runner in the
``[mcp_servers.scenario_tools].env`` block; never bind-mounted):

    SCENARIO_MCP_MODULE        dotted module, e.g. plugins.scenarios.agentdyn.tools_mcp
    SCENARIO_MCP_INSTANCE      path to instance JSON
    SCENARIO_MCP_ENV_STATE     path to env_state (environment_snapshot) JSON
    SCENARIO_MCP_INTERCEPTORS  path to resolved interceptors JSON (list)
    SCENARIO_MCP_POST_ENV      path to write the post-attack env JSON
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

# Shared interceptor logic.
from runner_core import _apply_interceptor, _tool_name_matches, safe_model_dump


def _log(msg: str) -> None:
    # Keep stdout for JSON-RPC.
    print(f"[scenario-mcp] {msg}", file=sys.stderr, flush=True)


def _load_json(env_var: str, default: Any) -> Any:
    path = os.environ.get(env_var)
    if not path:
        return default
    try:
        return json.loads(Path(path).read_text())
    except Exception as e:  # noqa: BLE001
        _log(f"WARN could not read {env_var}={path!r}: {e!r}")
        return default


def _resolve_build_tools(module_name: str):
    """Import the scenario module and return its ``build_tools`` callable.

    ``build_tools(instance, env_state) -> (sdk_tools, env)`` is the
    drive-layer-agnostic seam (see ``tools_mcp.build_tools``). The plugin
    dir is bind-mounted at ``/plugins``; ``/`` on ``sys.path`` makes
    ``plugins.scenarios.<name>.tools_mcp`` resolve.
    """
    if "/" not in sys.path:
        sys.path.insert(0, "/")
    mod = importlib.import_module(module_name)
    fn = getattr(mod, "build_tools", None)
    if not callable(fn):
        raise RuntimeError(
            f"{module_name!r} has no callable build_tools(instance, env_state); "
            f"the codex STDIO MCP server requires it (claude_code uses "
            f"build_mcp_server, but codex needs the raw tool list to re-serve "
            f"over STDIO)."
        )
    return fn


def _tool_input_schema(tool: Any) -> dict[str, Any]:
    """Coerce an SdkMcpTool.input_schema into an MCP JSON-Schema object.

    Scenario tools pass a full pydantic ``model_json_schema()`` dict
    (an object schema). A bare ``{name: pytype}`` mapping (the simple
    ``@tool`` form) is wrapped into a permissive object schema since we
    cannot faithfully translate python types here — the handler revalidates
    its own args anyway.
    """
    schema = getattr(tool, "input_schema", None)
    if isinstance(schema, dict) and ("properties" in schema or schema.get("type") == "object"):
        return schema
    return {"type": "object", "properties": {}, "additionalProperties": True}


def _content_to_blocks(content: Any):
    """Turn the handler's ``content`` list into MCP TextContent blocks.

    Handlers return ``{"content": [{"type": "text", "text": ...}, ...]}``.
    After an interceptor splice the structure can be an arbitrary
    list/dict, so non-text items are JSON-serialised into a text block
    rather than dropped (the model must see the spliced payload).
    """
    import mcp.types as types

    blocks = []
    items = content if isinstance(content, list) else [content]
    for item in items:
        if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
            blocks.append(types.TextContent(type="text", text=str(item["text"])))
        elif isinstance(item, str):
            blocks.append(types.TextContent(type="text", text=item))
        else:
            blocks.append(types.TextContent(
                type="text",
                text=json.dumps(item, ensure_ascii=False, default=str),
            ))
    if not blocks:
        blocks.append(types.TextContent(type="text", text=""))
    return blocks


def _build_server():
    from mcp.server.lowlevel import Server
    import mcp.types as types

    module_name = os.environ.get("SCENARIO_MCP_MODULE") or ""
    if not module_name:
        raise RuntimeError("SCENARIO_MCP_MODULE not set")

    instance = _load_json("SCENARIO_MCP_INSTANCE", {}) or {}
    env_state = _load_json("SCENARIO_MCP_ENV_STATE", {}) or {}
    interceptors = _load_json("SCENARIO_MCP_INTERCEPTORS", []) or []
    post_env_path = os.environ.get("SCENARIO_MCP_POST_ENV")

    build_tools = _resolve_build_tools(module_name)
    sdk_tools, env = build_tools(instance, env_state)
    handlers = {t.name: t.handler for t in sdk_tools}
    _log(f"loaded {len(sdk_tools)} tools from {module_name} "
         f"(suite={instance.get('suite')!r}); interceptors={len(interceptors)}")

    def _dump_post_env() -> None:
        if not post_env_path or env is None:
            return
        try:
            dumped = safe_model_dump(env)
            Path(post_env_path).write_text(json.dumps(dumped, ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            _log(f"WARN post_environment serialize failed: {e!r}")

    # Persist initial environment.
    _dump_post_env()

    server = Server("scenario_tools")

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:  # noqa: ANN202
        return [
            types.Tool(
                name=t.name,
                description=getattr(t, "description", "") or "",
                inputSchema=_tool_input_schema(t),
            )
            for t in sdk_tools
        ]

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]):  # noqa: ANN202
        handler = handlers.get(name)
        if handler is None:
            return _content_to_blocks([{"type": "text", "text": f"Unknown tool: {name}"}])
        result = await handler(arguments or {})
        content = result.get("content", []) if isinstance(result, dict) else result

        # Splice tool output.
        applied = False
        for spec in interceptors:
            if not _tool_name_matches(spec.get("tool"), name):
                continue
            modified = _apply_interceptor(spec, content)
            if modified is None:
                continue
            content = modified
            applied = True
            _log(f"spliced output for tool={name!r} via "
                 f"action={(spec.get('action') or {}).get('kind')!r}")

        # Persist post-tool environment.
        _dump_post_env()
        return _content_to_blocks(content)

    return server


async def _main() -> int:
    from mcp.server.stdio import stdio_server

    server = _build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(_main()))
    except Exception as e:  # noqa: BLE001
        _log(f"FATAL {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
        sys.exit(2)
