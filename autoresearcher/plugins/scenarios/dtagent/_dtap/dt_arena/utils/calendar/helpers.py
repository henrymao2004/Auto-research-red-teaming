from __future__ import annotations
import json
import http.client
import urllib.parse as urlparse
from pathlib import Path
from typing import List, Dict, Any, Tuple
import yaml

from dt_arena.utils._resilient import resilient_send


def _get_registry() -> dict:
    root = Path(__file__).resolve().parents[3]
    registry_file = root / "dt_arena" / "envs" / "registry.yaml"
    if registry_file.exists():
        try:
            return yaml.safe_load(registry_file.read_text()) or {}
        except Exception:
            return {}
    return {}


def _get_calendar_host_port() -> Tuple[str, int]:
    import os
    # First check for environment variable (set by task_runner for dynamic ports)
    env_port = os.environ.get("CALENDAR_API_PORT")
    if env_port:
        return "127.0.0.1", int(env_port)
    
    # Use registry
    reg = _get_registry()
    base = ((reg.get("services") or {}).get("calendar") or {}).get(
        "api_base_url", "http://127.0.0.1:8032"
    )
    parsed = urlparse.urlparse(base)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if (parsed.scheme or "http") == "https" else 80)
    return host, port


def login(email: str, password: str) -> str:
    host, port = _get_calendar_host_port()
    body = json.dumps({"email": email, "password": password})
    headers = {"Content-Type": "application/json"}
    status, data = resilient_send(host, port, "POST", "/api/v1/auth/login", headers=headers, body=body, timeout=5)
    if status == 200:
        try:
            return json.loads(data.decode()).get("access_token") or ""
        except Exception:
            return ""
    return ""


def list_events(token: str, start: str | None = None, end: str | None = None, limit: int = 50) -> List[Dict[str, Any]]:
    host, port = _get_calendar_host_port()
    headers = {"Authorization": f"Bearer {token}"}
    # Try all calendars first
    status, cal_data = resilient_send(host, port, "GET", "/calendar/v3/users/me/calendarList", headers=headers, timeout=5)
    if status != 200:
        return []
    
    all_events = []
    try:
        calendars = json.loads(cal_data.decode())
        if isinstance(calendars, dict):
            calendars = calendars.get("items", [])
        for cal in calendars:
            cal_id = cal.get("id", "primary")
            status, events_data = resilient_send(host, port, "GET", f"/calendar/v3/calendars/{cal_id}/events", headers=headers, timeout=5)
            if status == 200:
                events = json.loads(events_data.decode())
                if isinstance(events, dict):
                    events = events.get("items", [])
                all_events.extend(events)
    except Exception:
        pass
    return all_events
