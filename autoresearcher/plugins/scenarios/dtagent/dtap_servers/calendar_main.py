#!/usr/bin/env python3
"""Calendar MCP Server for Google Calendar Sandbox."""
import os
import sys
import json
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import asyncio
import httpx
from fastmcp import FastMCP
from pathlib import Path
try:
    import yaml  # type: ignore
except Exception:
    yaml = None

CALENDAR_API_URL = os.getenv("CALENDAR_API_URL", "http://localhost:8032")
CALENDAR_API_BASE = f"{CALENDAR_API_URL}/calendar/v3"

USER_ACCESS_TOKEN = os.getenv("USER_ACCESS_TOKEN", "")

print(f"[Calendar MCP Server] ===== STARTING =====", file=sys.stderr)
print(f"[Calendar MCP Server] USER_ACCESS_TOKEN: {USER_ACCESS_TOKEN[:20] if USER_ACCESS_TOKEN else 'NONE'}...", file=sys.stderr)
print(f"[Calendar MCP Server] CALENDAR_API_URL: {CALENDAR_API_URL}", file=sys.stderr)
print(f"[Calendar MCP Server] ==================", file=sys.stderr)
sys.stderr.flush()

mcp = FastMCP("Calendar Client")

_http_client: Optional[httpx.AsyncClient] = None


def _get_auth_headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if USER_ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {USER_ACCESS_TOKEN}"
    return headers


async def get_http() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=30.0,
            headers=_get_auth_headers()
        )
    return _http_client


async def resolve_calendar_id(calendar_id: Optional[str]) -> str:
    """Resolve 'primary' or missing calendar_id to the user's primary calendar id."""
    target = (calendar_id or "primary").strip()
    if target and target != "primary":
        return target
    try:
        client = await get_http()
        resp = await client.get(f"{CALENDAR_API_BASE}/users/me/calendarList", headers=_get_auth_headers())
        if resp.status_code == 200:
            data = resp.json() or {}
            items = data.get("items", []) or []
            for cal in items:
                if cal.get("id") == "primary":
                    return "primary"
            for cal in items:
                if cal.get("primary"):
                    return cal.get("id")
            if items:
                return items[0].get("id") or "primary"
    except Exception:
        pass
    return "primary"


@mcp.tool()
async def list_calendars(
    min_access_role: Optional[str] = None,
    show_deleted: bool = False,
    show_hidden: bool = False,
) -> str:
    """List all calendars accessible to the user."""
    try:
        client = await get_http()
        params = {}
        if min_access_role:
            params["minAccessRole"] = min_access_role
        if show_deleted:
            params["showDeleted"] = "true"
        if show_hidden:
            params["showHidden"] = "true"
        
        resp = await client.get(
            f"{CALENDAR_API_BASE}/users/me/calendarList",
            params=params,
            headers=_get_auth_headers()
        )
        
        if resp.status_code != 200:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_events(
    calendar_id: str = "primary",
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 50,
    order_by: str = "startTime",
    single_events: bool = True,
    show_deleted: bool = False,
) -> str:
    """List events from a calendar."""
    try:
        client = await get_http()
        params = {
            "maxResults": min(max_results, 250),
            "orderBy": order_by,
            "singleEvents": str(single_events).lower(),
        }

        if time_min:
            params["timeMin"] = _parse_time_param(time_min)
        if time_max:
            params["timeMax"] = _parse_time_param(time_max)
        if show_deleted:
            params["showDeleted"] = "true"

        resolved_id = await resolve_calendar_id(calendar_id)

        resp: httpx.Response | None = None
        for attempt in range(3):
            resp = await client.get(
                f"{CALENDAR_API_BASE}/calendars/{resolved_id}/events",
                params=params,
                headers=_get_auth_headers(),
            )
            if 500 <= resp.status_code < 600:
                try:
                    print(
                        f"[Calendar MCP] list_events 5xx (attempt {attempt+1}) "
                        f"calendar_id={resolved_id!r} status={resp.status_code} body={resp.text[:300]}",
                        file=sys.stderr,
                    )
                except Exception:
                    pass
                if attempt < 2:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
            break

        if resp is None:
            return json.dumps({"error": "Failed to contact calendar service"}, ensure_ascii=False)

        if resp.status_code != 200:
            return json.dumps(
                {
                    "error": f"HTTP {resp.status_code}: {resp.text}",
                    "items": [],
                },
                ensure_ascii=False,
            )

        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_event(
    event_id: str,
    calendar_id: str = "primary",
) -> str:
    """Get details of a specific event."""
    if not event_id:
        return json.dumps({"error": "event_id is required"})
    
    try:
        client = await get_http()
        resolved_id = await resolve_calendar_id(calendar_id)
        resp = await client.get(
            f"{CALENDAR_API_BASE}/calendars/{resolved_id}/events/{event_id}",
            headers=_get_auth_headers()
        )
        
        if resp.status_code == 404:
            return json.dumps({"error": f"Event {event_id} not found"})
        if resp.status_code != 200:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _parse_list_param(val: Any) -> Optional[List[str]]:
    if val is None:
        return None
    if isinstance(val, list):
        return val
    if isinstance(val, str):
        val = val.strip()
        if val.startswith('['):
            try:
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        if '@' in val:
            return [val]
    return None


@mcp.tool()
async def create_event(
    summary: str,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    calendar_id: str = "primary",
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[Any] = None,
    timezone: str = "UTC",
    send_updates: Optional[str] = None,
) -> str:
    """Create a new calendar event."""
    if not summary:
        return json.dumps({"error": "summary is required"})

    attendees_list = _parse_list_param(attendees)

    try:
        event_data: Dict[str, Any] = {"summary": summary}

        if start_datetime and end_datetime:
            event_data["start"] = {
                "dateTime": start_datetime,
                "timeZone": timezone
            }
            event_data["end"] = {
                "dateTime": end_datetime,
                "timeZone": timezone
            }
        elif start_date and end_date:
            event_data["start"] = {"date": start_date}
            event_data["end"] = {"date": end_date}
        elif start_datetime:
            event_data["start"] = {
                "dateTime": start_datetime,
                "timeZone": timezone
            }
            end_dt = _add_hours(start_datetime, 1)
            event_data["end"] = {
                "dateTime": end_dt,
                "timeZone": timezone
            }
        else:
            return json.dumps({"error": "Either start_datetime/end_datetime or start_date/end_date is required"})
        
        if description:
            event_data["description"] = description
        if location:
            event_data["location"] = location
        if attendees_list:
            event_data["attendees"] = [{"email": email} for email in attendees_list]
        
        client = await get_http()
        params = {}
        if send_updates:
            params["sendUpdates"] = send_updates
        
        resolved_id = await resolve_calendar_id(calendar_id)
        resp = await client.post(
            f"{CALENDAR_API_BASE}/calendars/{resolved_id}/events",
            json=event_data,
            params=params,
            headers=_get_auth_headers()
        )
        
        if resp.status_code not in (200, 201):
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def update_event(
    event_id: str,
    calendar_id: str = "primary",
    summary: Optional[str] = None,
    start_datetime: Optional[str] = None,
    end_datetime: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    description: Optional[str] = None,
    location: Optional[str] = None,
    attendees: Optional[List[str]] = None,
    timezone: Optional[str] = None,
    status: Optional[str] = None,
    send_updates: Optional[str] = None,
) -> str:
    """Update an existing calendar event."""
    if not event_id:
        return json.dumps({"error": "event_id is required"})

    try:
        client = await get_http()
        resolved_id = await resolve_calendar_id(calendar_id)
        get_resp = await client.get(
            f"{CALENDAR_API_BASE}/calendars/{resolved_id}/events/{event_id}",
            headers=_get_auth_headers()
        )
        
        if get_resp.status_code == 404:
            return json.dumps({"error": f"Event {event_id} not found"})
        if get_resp.status_code != 200:
            return json.dumps({"error": f"HTTP {get_resp.status_code}: {get_resp.text}"})
        
        event_data = get_resp.json()

        if summary is not None:
            event_data["summary"] = summary
        if description is not None:
            event_data["description"] = description
        if location is not None:
            event_data["location"] = location
        if status is not None:
            event_data["status"] = status

        if start_datetime and end_datetime:
            tz = timezone or event_data.get("start", {}).get("timeZone", "UTC")
            event_data["start"] = {"dateTime": start_datetime, "timeZone": tz}
            event_data["end"] = {"dateTime": end_datetime, "timeZone": tz}
        elif start_date and end_date:
            event_data["start"] = {"date": start_date}
            event_data["end"] = {"date": end_date}
        
        if attendees is not None:
            event_data["attendees"] = [{"email": email} for email in attendees]
        
        params = {}
        if send_updates:
            params["sendUpdates"] = send_updates
        
        resp = await client.put(
            f"{CALENDAR_API_BASE}/calendars/{resolved_id}/events/{event_id}",
            json=event_data,
            params=params,
            headers=_get_auth_headers()
        )
        
        if resp.status_code != 200:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    send_updates: Optional[str] = None,
) -> str:
    """Delete a calendar event."""
    if not event_id:
        return json.dumps({"error": "event_id is required"})
    
    try:
        client = await get_http()
        params = {}
        if send_updates:
            params["sendUpdates"] = send_updates
        
        resolved_id = await resolve_calendar_id(calendar_id)
        resp = await client.delete(
            f"{CALENDAR_API_BASE}/calendars/{resolved_id}/events/{event_id}",
            params=params,
            headers=_get_auth_headers()
        )
        
        if resp.status_code in (200, 204, 404):
            return json.dumps({"ok": True, "event_id": event_id})
        
        return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def search_events(
    query: str,
    calendar_id: str = "primary",
    time_min: Optional[str] = None,
    time_max: Optional[str] = None,
    max_results: int = 50,
) -> str:
    """Search for events by text query."""
    if not query:
        return json.dumps({"error": "query is required"})
    
    try:
        client = await get_http()
        params = {
            "q": query,
            "maxResults": min(max_results, 250),
            "singleEvents": "true"
        }
        
        if time_min:
            params["timeMin"] = _parse_time_param(time_min)
        if time_max:
            params["timeMax"] = _parse_time_param(time_max)
        
        resolved_id = await resolve_calendar_id(calendar_id)
        resp = await client.get(
            f"{CALENDAR_API_BASE}/calendars/{resolved_id}/events",
            params=params,
            headers=_get_auth_headers()
        )
        
        if resp.status_code != 200:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def get_freebusy(
    time_min: str,
    time_max: str,
    calendar_ids: Optional[List[str]] = None,
    timezone: str = "UTC",
) -> str:
    """Query free/busy information for calendars."""
    if not time_min or not time_max:
        return json.dumps({"error": "time_min and time_max are required"})
    
    try:
        if calendar_ids is None:
            calendar_ids = ["primary"]
        
        request_body = {
            "timeMin": _parse_time_param(time_min),
            "timeMax": _parse_time_param(time_max),
            "timeZone": timezone,
            "items": [{"id": cal_id} for cal_id in calendar_ids]
        }
        
        client = await get_http()
        resp = await client.post(
            f"{CALENDAR_API_BASE}/calendar/v3/freeBusy",
            json=request_body,
            headers=_get_auth_headers()
        )
        
        if resp.status_code != 200:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def list_colors() -> str:
    """List available colors for calendars and events."""
    try:
        client = await get_http()
        resp = await client.get(
            f"{CALENDAR_API_BASE}/colors",
            headers=_get_auth_headers()
        )
        
        if resp.status_code != 200:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def accept_invitation(
    event_id: str,
    calendar_id: str = "primary",
) -> str:
    """Accept a calendar event invitation."""
    if not event_id:
        return json.dumps({"error": "event_id is required"})
    
    try:
        client = await get_http()
        resp = await client.post(
            f"{CALENDAR_API_BASE}/events/{event_id}/accept",
            headers=_get_auth_headers()
        )
        
        if resp.status_code != 200:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def decline_invitation(
    event_id: str,
    calendar_id: str = "primary",
) -> str:
    """Decline a calendar event invitation."""
    if not event_id:
        return json.dumps({"error": "event_id is required"})
    
    try:
        client = await get_http()
        resp = await client.post(
            f"{CALENDAR_API_BASE}/events/{event_id}/decline",
            headers=_get_auth_headers()
        )
        
        if resp.status_code != 200:
            return json.dumps({"error": f"HTTP {resp.status_code}: {resp.text}"})
        
        return json.dumps(resp.json(), ensure_ascii=False)
    except Exception as e:
        return json.dumps({"error": str(e)})


def _parse_time_param(time_str: str) -> str:
    import re

    raw = (time_str or "").strip()
    key = raw.lower()

    if key == "now":
        return datetime.utcnow().isoformat() + "Z"
    elif key == "today":
        return (
            datetime.utcnow()
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            + "Z"
        )
    elif key == "tomorrow":
        return (
            (datetime.utcnow() + timedelta(days=1))
            .replace(hour=0, minute=0, second=0, microsecond=0)
            .isoformat()
            + "Z"
        )
    elif key.startswith("+"):
        try:
            value = int(key[1:-1])
            unit = key[-1]
            if unit == "d":
                dt = datetime.utcnow() + timedelta(days=value)
            elif unit == "h":
                dt = datetime.utcnow() + timedelta(hours=value)
            elif unit == "m":
                dt = datetime.utcnow() + timedelta(minutes=value)
            else:
                return raw
            return dt.isoformat() + "Z"
        except Exception:
            return raw
    else:
        if raw.endswith(("Z", "z")):
            return raw[:-1] + "Z"

        # Preserve explicit UTC offsets such as -05:00, +0000, -07.
        if re.search(r"(?:[+-]\d{2}:\d{2}|[+-]\d{4}|[+-]\d{2})$", raw):
            return raw

        if raw.upper().endswith("UTC"):
            return raw[:-3] + "Z"

        return raw + "Z"


def _add_hours(datetime_str: str, hours: int) -> str:
    try:
        dt_str = datetime_str.rstrip("Z")
        dt = datetime.fromisoformat(dt_str)
        dt = dt + timedelta(hours=hours)
        return dt.isoformat()
    except Exception:
        return datetime_str


def main():
    print("Starting Calendar MCP Server (Google Calendar Sandbox)...", file=sys.stderr)
    sys.stderr.flush()
    host = os.getenv("CALENDAR_MCP_HOST", "localhost")
    env_port = os.getenv("PORT", "").strip()

    def _port_from_registry(default_port: int) -> int:
        try:
            if yaml is None:
                return default_port
            registry_path = Path(__file__).resolve().parent.parent / "registry.yaml"
            if not registry_path.exists():
                return default_port
            data = yaml.safe_load(registry_path.read_text()) or {}
            service_name = Path(__file__).resolve().parent.name
            for srv in (data.get("servers") or []):
                if isinstance(srv, dict) and srv.get("name") == service_name:
                    env = srv.get("env") or {}
                    port_str = str(env.get("PORT") or "").strip().strip('\"')
                    return int(port_str) if port_str else default_port
        except Exception:
            return default_port
        return default_port

    if env_port.isdigit():
        port = int(env_port)
    else:
        port = _port_from_registry(8841)

    mcp.run(transport="http", port=port)


if __name__ == "__main__":
    main()
