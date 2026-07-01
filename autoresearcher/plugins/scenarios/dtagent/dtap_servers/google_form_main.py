#!/usr/bin/env python3
"""Google Form MCP server (sandboxed) — thin HTTP proxy to the Google-Form ENV API."""
import os
import sys
import json
from typing import Any, Dict, Optional

import httpx
from fastmcp import FastMCP

FORM_API_BASE = (
    os.getenv("GOOGLE_FORM_API_URL")
    or os.getenv("FORM_API_BASE")
    or "http://host.docker.internal:8054"
).rstrip("/")

mcp = FastMCP("Local Google Form")

_client: Optional[httpx.AsyncClient] = None


async def get_http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=20.0)
    return _client


@mcp.tool()
async def get_form() -> str:
    """Get current form schema from the API."""
    try:
        client = await get_http()
        r = await client.get(f"{FORM_API_BASE}/form")
        if r.status_code != 200:
            return json.dumps({"error": f"HTTP {r.status_code}: {r.text}"})
        return json.dumps(r.json(), ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def set_form(schema_json: str) -> str:
    """Replace the form schema with the provided JSON string (via the API)."""
    try:
        data = json.loads(schema_json)
        if not isinstance(data, dict):
            return json.dumps({"error": "schema must be a JSON object"})
        client = await get_http()
        r = await client.post(f"{FORM_API_BASE}/form", json=data)
        if r.status_code != 200:
            return json.dumps({"error": f"HTTP {r.status_code}: {r.text}"})
        return json.dumps({"ok": True, "result": r.json()}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_submissions(limit: int = 100) -> str:
    """List recent submissions from API. Returns up to 'limit' rows."""
    try:
        client = await get_http()
        r = await client.get(f"{FORM_API_BASE}/submissions")
        if r.status_code != 200:
            return json.dumps({"error": f"HTTP {r.status_code}: {r.text}"})
        rows = r.json() or []
        return json.dumps(rows[: max(1, min(2000, limit))], ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def submit(payload_json: str) -> str:
    """Submit a response to the form. payload_json should be a JSON object of field->value."""
    try:
        payload = json.loads(payload_json or "{}")
        if not isinstance(payload, dict):
            return json.dumps({"error": "payload must be a JSON object"})
        client = await get_http()
        r = await client.post(f"{FORM_API_BASE}/submit", json=payload)
        if r.status_code != 200:
            return json.dumps({"error": f"HTTP {r.status_code}: {r.text}"})
        return json.dumps(r.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def clear_submissions() -> str:
    """Clear all submissions via the API."""
    try:
        client = await get_http()
        r = await client.delete(f"{FORM_API_BASE}/submissions")
        if r.status_code not in (200, 204):
            return json.dumps({"error": f"HTTP {r.status_code}: {r.text}"})
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"error": str(e)})


def main() -> None:
    print("Starting Local Google Form MCP server (proxying to ENV API)...", file=sys.stderr)
    print(f"[Google Form MCP] ENV API: {FORM_API_BASE}", file=sys.stderr)
    sys.stderr.flush()

    host = os.getenv("GF_MCP_HOST", "0.0.0.0")

    env_port = os.getenv("PORT", "").strip()
    raw_mcp_port = os.getenv("GOOGLE_FORM_MCP_PORT", "").strip()
    if env_port.isdigit():
        port = int(env_port)
    elif raw_mcp_port.isdigit():
        port = int(raw_mcp_port)
    else:
        port = 8855

    mcp.run(transport="http", host=host, port=port)


if __name__ == "__main__":
    main()
