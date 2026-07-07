"""Per-instance reset + seed of the DTap backends (evaluator side, host-run).

Runs the instance's vendored DTap ``setup.sh`` verbatim host-side before the
victim, so utility/ASR reflect this instance. Captures and surfaces the rc.
Note: ``rc == 0`` is not proof the seed worked (setup.sh can swallow auth
failures), so a uniformly 0% domain warrants verifying the backend state.
"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SALESFORCE_BASE_URL = os.environ.get("SALESFORCE_BASE_URL", "http://localhost:8080")

# Backend host ports.
_BACKEND_PORTS = {
    "SALESFORCE_API_PORT": os.environ.get("SALESFORCE_API_PORT", "8080"),
    "GMAIL_AUTH_PORT": os.environ.get("GMAIL_AUTH_PORT", "8030"),
    "GMAIL_UI_PORT": os.environ.get("GMAIL_UI_PORT", "8025"),
    "GMAIL_PROXY_PORT": os.environ.get("GMAIL_PROXY_PORT", "8031"),
    "GMAIL_SMTP_PORT": os.environ.get("GMAIL_SMTP_PORT", "1025"),
    "GMAIL_FRONTEND_PORT": os.environ.get("GMAIL_FRONTEND_PORT", "8050"),
    "SLACK_API_PORT": os.environ.get("SLACK_API_PORT", "8034"),
    "SLACK_UI_PORT": os.environ.get("SLACK_UI_PORT", "8028"),
    "CALENDAR_API_PORT": os.environ.get("CALENDAR_API_PORT", "8032"),
    "CALENDAR_UI_PORT": os.environ.get("CALENDAR_UI_PORT", "8026"),
    "ATLASSIAN_API_PORT": os.environ.get("ATLASSIAN_API_PORT", "8040"),
    "ATLASSIAN_DB_PORT": os.environ.get("ATLASSIAN_DB_PORT", "5454"),
    "ATLASSIAN_UI_PORT": os.environ.get("ATLASSIAN_UI_PORT", "8041"),
    "HOSPITAL_HOST": "127.0.0.1",
    "HOSPITAL_PORT": os.environ.get("HOSPITAL_PORT", "12001"),
    "PAYPAL_API_PORT": os.environ.get("PAYPAL_API_PORT", "8035"),
    "WHATSAPP_API_PORT": os.environ.get("WHATSAPP_API_PORT", "8039"),
    "GOOGLEDOCS_API_PORT": os.environ.get("GOOGLEDOCS_API_PORT", "8041"),
    "ZOOM_API_PORT": os.environ.get("ZOOM_API_PORT", "8033"),
    "GOOGLE_FORM_API_PORT": os.environ.get("GOOGLE_FORM_API_PORT", "8054"),
    "SNOWFLAKE_ADMIN_PORT": os.environ.get("SNOWFLAKE_ADMIN_PORT", "8454"),
    "DATABRICKS_ADMIN_PORT": os.environ.get("DATABRICKS_ADMIN_PORT", "8453"),
    "DATABRICKS_PG_PORT": os.environ.get("DATABRICKS_PG_PORT", "5453"),
    "OS_FILESYSTEM_API_PORT": os.environ.get("OS_FILESYSTEM_API_PORT", "8036"),
    "GITHUB_API_PORT": os.environ.get("GITHUB_API_PORT", "8083"),
}


def _setup_path(gid: str, domain: str | None = None) -> Path | None:
    if domain:
        p = HERE / "setups" / domain / gid / "setup.sh"
        if p.exists():
            return p
    for p in (HERE / "setups").rglob(f"{gid}/setup.sh"):
        return p
    return None


def _post(url: str, body: dict | None = None, timeout: int = 30) -> int:
    data = json.dumps(body or {}).encode() if body is not None else b"{}"
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:  # noqa: BLE001
        return -1


def reset_and_seed(gid: str, *, domain: str | None = None,
                   base_url: str | None = None, timeout: int = 120) -> dict:
    """Run the instance's vendored DTap setup.sh host-side. Never raises."""
    out: dict = {"gid": gid, "method": None, "rc": None}
    sp = _setup_path(gid, domain)
    if sp is not None:
        _gates = {k: gid for k in (
            "OS_FILESYSTEM_PROJECT_NAME", "SLACK_PROJECT_NAME",
            "GMAIL_PROJECT_NAME", "PAYPAL_PROJECT_NAME")}
        env = dict(os.environ, **_BACKEND_PORTS, **_gates)
        try:
            p = subprocess.run(["bash", str(sp)], cwd=str(sp.parent), env=env,
                               capture_output=True, text=True, timeout=timeout)
            out.update(method="setup.sh", rc=p.returncode,
                       stdout_tail=p.stdout[-400:], stderr_tail=p.stderr[-400:])
        except subprocess.TimeoutExpired:
            out.update(method="setup.sh", rc=-1, stderr_tail=f"timeout>{timeout}s")
        return out
    base = (base_url or SALESFORCE_BASE_URL).rstrip("/")
    out.update(method="reset-database-only", rc=_post(f"{base}/Api/V8/admin/reset-database"))
    return out


if __name__ == "__main__":
    import sys
    g = sys.argv[1] if len(sys.argv) > 1 else "crm-benign-1"
    print(json.dumps(reset_and_seed(g), indent=2))
