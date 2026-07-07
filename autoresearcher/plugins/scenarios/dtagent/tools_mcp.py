"""dtagent victim tool surface — in-process SDK MCP, multi-server.

Bridges each DTap tool server (dtap_servers/<svc>_main.py) the instance lists
into a claude-agent-sdk in-process server and returns ``{server_name: server}``.
Per-task secrets in ``instance.mcp_servers[<name>].env_vars`` are set into the
environment before importing each server's module (servers read env at import).
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import os
import sys
from typing import Any

# DTap server modules.
_SERVERS = {
    "salesforce": ".dtap_servers.salesforce_main",
    "gmail": ".dtap_servers.gmail_main",
    "slack": ".dtap_servers.slack_main",
    "calendar": ".dtap_servers.calendar_main",
    "HospitalClient": ".dtap_servers.hospital_main",
    "atlassian": ".dtap_servers.atlassian_main",
    "paypal": ".dtap_servers.paypal_main",
    "whatsapp": ".dtap_servers.whatsapp_main",
    "googledocs": ".dtap_servers.googledocs_main",
    "github": ".dtap_servers.github_main",
    "zoom": ".dtap_servers.zoom_main",
    "google-form": ".dtap_servers.google_form_main",
    "OS-filesystem": ".dtap_servers.os_filesystem_main",
    "snowflake": ".dtap_servers.snowflake_main",
    "databricks": ".dtap_servers.databricks_main",
    "bigquery": ".dtap_servers.bigquery_main",
}

# Host-published backend defaults.
for _k, _v in {
    "SALESFORCE_BASE_URL": "http://host.docker.internal:8080",
    "AUTH_API_URL": "http://host.docker.internal:8030",
    "API_PROXY_URL": "http://host.docker.internal:8031",
    "MAILPIT_BASE_URL": "http://host.docker.internal:8025",
    "MAILPIT_SMTP_HOST": "host.docker.internal",
    "SLACK_API_URL": "http://host.docker.internal:8034",
    "CALENDAR_API_URL": "http://host.docker.internal:8032",
    "HOSPITAL_HOST": "192.168.65.254",
    "HOSPITAL_PORT": "12001",
    "ATLASSIAN_API_URL": "http://192.168.65.254:8040",
    "PAYPAL_API_URL": "http://host.docker.internal:8035",
    "SNOWFLAKE_ADMIN_URL": "http://host.docker.internal:8454",
    "SNOWFLAKE_PG_HOST": "192.168.65.254",
    "SNOWFLAKE_PG_PORT": "5454",
    "WHATSAPP_BASE_URL": "http://host.docker.internal:8039",
    "GOOGLEDOCS_API_URL": "http://host.docker.internal:8041",
    "GITHUB_API_URL": "http://host.docker.internal:8083",
    "ZOOM_API_URL": "http://host.docker.internal:8033",
    "GOOGLE_FORM_API_URL": "http://host.docker.internal:8054",
    "FILESYSTEM_API_URL": "http://host.docker.internal:8036",
    "PERMISSION_AUTO_APPROVE": "true",
    "DATABRICKS_BASE_URL": "http://host.docker.internal:8453",
    "DATABRICKS_PG_PORT": "5453",
    "BIGQUERY_API_URL": "http://host.docker.internal:9050",
}.items():
    os.environ.setdefault(_k, _v)

_TOKEN_READY: set[str] = set()


def _run_async(coro_factory):
    """Run async from sync code even inside a running loop (dedicated thread + loop)."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro_factory())).result()


def _load_server(name: str, env_vars: dict | None = None):
    """Set this server's per-task env, import its vendored module, return `mcp`."""
    mod_path = _SERVERS.get(name)
    if not mod_path:
        return None
    for k, v in (env_vars or {}).items():
        sv = str(v)
        if sv in ("127.0.0.1", "localhost"):
            sv = "host.docker.internal"
        elif "127.0.0.1" in sv or "localhost" in sv:
            sv = sv.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal")
        os.environ[str(k)] = sv
    mod = importlib.import_module(mod_path, package=__package__)
    if name not in _TOKEN_READY:
        startup = getattr(mod, "_ensure_token_on_startup", None)
        if callable(startup):
            try:
                _run_async(startup)
            except Exception:  # noqa: BLE001
                pass
        _TOKEN_READY.add(name)
    return getattr(mod, "mcp", None)


async def _list_tools(mcp):
    from fastmcp import Client
    async with Client(mcp) as c:
        return await c.list_tools()


def _to_text(result: Any) -> str:
    import json
    data = getattr(result, "data", None)
    if data is not None:
        try:
            return data if isinstance(data, str) else json.dumps(data, ensure_ascii=False, default=str)
        except Exception:  # noqa: BLE001
            return str(data)
    content = getattr(result, "content", None)
    if isinstance(content, list):
        return "\n".join((getattr(b, "text", None) or "") for b in content)
    return str(result)


def _sanitize_schema(s):
    """Strip keys (title/additionalProperties/$schema) the CLI MCP registration chokes on."""
    if isinstance(s, dict):
        return {k: _sanitize_schema(v) for k, v in s.items()
                if k not in ("title", "additionalProperties", "$schema")}
    if isinstance(s, list):
        return [_sanitize_schema(x) for x in s]
    return s


def _wrap(mcp, tool_info, tool_deco, exposed_name: str | None = None):
    name = tool_info.name
    exposed = exposed_name or name
    description = getattr(tool_info, "description", None) or name
    schema = _sanitize_schema(getattr(tool_info, "inputSchema", None) or {"type": "object"})

    @tool_deco(exposed, description, schema)
    async def _handler(args: dict) -> dict:
        from fastmcp import Client
        try:
            async with Client(mcp) as c:
                result = await c.call_tool(name, args or {})
            return {"content": [{"type": "text", "text": _to_text(result)}]}
        except Exception as exc:  # noqa: BLE001
            return {"content": [{"type": "text", "text": f"[tool error] {type(exc).__name__}: {exc}"}],
                    "isError": True}

    return _handler


def _bridge_one(name: str, env_vars: dict | None, create_sdk_mcp_server, tool):
    """Bridge one DTap tool server -> a single create_sdk_mcp_server, or None."""
    mcp = _load_server(name, env_vars)
    if mcp is None:
        return None
    tool_infos = _run_async(lambda: _list_tools(mcp))
    sdk_tools = [_wrap(mcp, ti, tool) for ti in tool_infos]
    print(f"[dtagent][bridge] bridged {len(sdk_tools)} tools from {name!r}", file=sys.stderr)
    return create_sdk_mcp_server(name=name, version="1.0.0", tools=sdk_tools)


def build_mcp_server(instance: dict[str, Any] | None = None,
                     env_state: dict[str, Any] | None = None):
    """Return ``{server_name: sdk_server}`` for every tool server the instance lists."""
    from claude_agent_sdk import create_sdk_mcp_server, tool

    inst = instance or {}
    cfgs = inst.get("mcp_servers")
    if not cfgs:
        cfgs = [{"name": n} for n in (inst.get("available_tools") or [])]

    servers: dict[str, Any] = {}
    for s in cfgs:
        name = s.get("name") if isinstance(s, dict) else str(s)
        env_vars = s.get("env_vars") if isinstance(s, dict) else None
        if name in servers or name not in _SERVERS:
            continue
        try:
            srv = _bridge_one(name, env_vars, create_sdk_mcp_server, tool)
        except Exception as exc:  # noqa: BLE001 — one bad server shouldn't kill the rest
            print(f"[dtagent][bridge] {name!r} FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
            srv = None
        if srv is not None:
            servers[name] = srv
    return servers or None


def build_tools(instance: dict[str, Any] | None = None,
                env_state: dict[str, Any] | None = None):
    """Return ``(sdk_tools, None)``: a flat ``mcp__<server>__<bare>`` tool list
    across all of the instance's backend servers, for the codex STDIO MCP bridge.
    ``env`` is ``None`` (DTap's vendored judge reads live backend state)."""
    from claude_agent_sdk import tool

    inst = instance or {}
    cfgs = inst.get("mcp_servers")
    if not cfgs:
        cfgs = [{"name": n} for n in (inst.get("available_tools") or [])]

    sdk_tools: list[Any] = []
    seen: set[str] = set()
    for s in cfgs:
        name = s.get("name") if isinstance(s, dict) else str(s)
        env_vars = s.get("env_vars") if isinstance(s, dict) else None
        if not name or name in seen or name not in _SERVERS:
            continue
        seen.add(name)
        try:
            mcp = _load_server(name, env_vars)
            if mcp is None:
                continue
            tool_infos = _run_async(lambda m=mcp: _list_tools(m))
            for ti in tool_infos:
                exposed_server = name.replace("-", "_")
                sdk_tools.append(
                    _wrap(mcp, ti, tool, exposed_name=f"mcp__{exposed_server}__{ti.name}"))
        except Exception as exc:  # noqa: BLE001 — one bad backend shouldn't kill the rest
            print(f"[dtagent][build_tools] {name!r} FAILED: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
    print(f"[dtagent][build_tools] flattened {len(sdk_tools)} tools "
          f"across {len(seen)} server(s)", file=sys.stderr)
    return (sdk_tools, None)


__all__ = ["build_mcp_server", "build_tools"]
