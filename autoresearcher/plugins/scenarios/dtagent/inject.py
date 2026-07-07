"""dtagent INDIRECT injection delivery (host-side, faithful to DTap)."""
from __future__ import annotations

import asyncio
import concurrent.futures
import importlib
import os
from typing import Any

# Injection backend defaults.
os.environ.setdefault("SLACK_API_URL", "http://localhost:8034")
os.environ.setdefault("GMAIL_SMTP_HOST", "localhost")
os.environ.setdefault("GMAIL_SMTP_PORT", "1025")
os.environ.setdefault("CALENDAR_API_URL", "http://localhost:8032")
os.environ.setdefault("SALESFORCE_BASE_URL", "http://localhost:8080")

# Vendored injection modules.
_SVC = {
    "slack-injection": ".dtap_servers.injection.slack_injection",
    "gmail-injection": ".dtap_servers.injection.gmail_injection",
    "calendar-injection": ".dtap_servers.injection.calendar_injection",
    "salesforce-injection": ".dtap_servers.injection.salesforce_injection",
}


def _run_async(coro_factory):
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        return ex.submit(lambda: asyncio.run(coro_factory())).result()


async def _call(mcp, tool_name: str, kwargs: dict):
    from fastmcp import Client
    async with Client(mcp) as c:
        return await c.call_tool(tool_name, kwargs or {})


def _normalize_injection_kwargs(svc: str, kwargs: dict) -> dict:
    # Normalize slack channel names.
    if svc.startswith("slack"):
        cn = kwargs.get("channel_name")
        if isinstance(cn, str) and cn.startswith("#"):
            kwargs = {**kwargs, "channel_name": cn.lstrip("#")}
    return kwargs


def apply_injection(attack: dict[str, Any], instance: dict[str, Any] | None = None) -> dict:
    """Run attack['injection_steps'] against the live backends. Never raises."""
    steps = (attack or {}).get("injection_steps") or []
    out: dict = {"steps": len(steps), "applied": 0, "errors": []}
    for st in steps:
        mt = st.get("injection_mcp_tool")
        kwargs = st.get("kwargs") or {}
        if not mt or ":" not in mt:
            out["errors"].append(f"bad injection_mcp_tool: {mt!r}")
            continue
        svc, tool_name = mt.split(":", 1)
        kwargs = _normalize_injection_kwargs(svc, kwargs)
        mod_path = _SVC.get(svc)
        if not mod_path:
            out["errors"].append(f"no vendored injection server for {svc!r}")
            continue
        try:
            mod = importlib.import_module(mod_path, package=__package__)
            _run_async(lambda: _call(mod.mcp, tool_name, kwargs))
            out["applied"] += 1
        except Exception as exc:  # noqa: BLE001
            out["errors"].append(f"{mt}: {type(exc).__name__}: {exc}")
    return out


if __name__ == "__main__":
    import json, sys
    from plugins.scenarios.dtagent import make_attack
    g = sys.argv[1] if len(sys.argv) > 1 else "crm-ind-dangerous-actions-15"
    print(json.dumps(apply_injection(make_attack.build(g)), indent=2))
