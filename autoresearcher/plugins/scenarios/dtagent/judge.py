"""dtagent per-instance judge dispatcher.

Loads the instance's vendored ``judge_ref`` (a DTap ``BaseJudge`` subclass) and
runs ``eval_task`` (utility) + ``eval_attack`` (targeted ASR), returning the
agentdyn/agenthazard verdict shape. Degrades to ``harmful=False`` with a
``metrics.judge_unavailable`` flag instead of raising.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import os

# DTap import root.
DTAP_REPO = Path(os.environ.get("DTAP_REPO") or (Path(__file__).resolve().parent / "_dtap"))

# Retryable backend errors.
_CONN_ERR_MARKERS = (
    "remote end closed", "remotedisconnected", "remote disconnected",
    "connection reset", "connection refused", "connection aborted",
    "connection error", "connectionerror", "newconnectionerror",
    "httpconnectionpool", "broken pipe", "max retries",
    "timed out", "timeout", "bad gateway", "service unavailable",
    "503", "502",
)


def _looks_like_conn_error(obj: Any) -> bool:
    """True if a judge verdict-meta OR a raised exception looks like a
    transient backend-connection drop (vs a real refusal/no-break)."""
    text = obj.get("message", "") if isinstance(obj, dict) else obj
    low = str(text).lower()
    return any(k in low for k in _CONN_ERR_MARKERS)


def _eval_with_retry(fn: Any, responses: Any, *, attempts: int = 6,
                     delay: float = 2.0) -> Any:
    """Call a judge eval method (eval_attack / eval_task) with retry on a
    transient backend-connection error — whether the error is RETURNED in the
    verdict metadata or RAISED as an exception. A real refusal/no-break (no
    connection marker) returns immediately; a non-connection exception
    re-raises for the caller to degrade."""
    import time as _t
    name = getattr(fn, "__name__", "eval")
    last = (False, {})
    for i in range(attempts):
        try:
            ok, meta = fn(responses)
        except Exception as exc:  # noqa: BLE001
            if not _looks_like_conn_error(exc):
                raise
            last = (False, {"message": f"{name} raised: {type(exc).__name__}: {exc}"})
        else:
            if ok or not _looks_like_conn_error(meta):
                return ok, meta
            last = (ok, meta)
        if i < attempts - 1:
            _t.sleep(min(delay * (i + 1), 8.0))
    return last


def _eval_attack_retry(judge: Any, responses: Any) -> Any:
    """eval_attack with retry on a transient backend-connection error."""
    return _eval_with_retry(judge.eval_attack, responses)


def _ensure_backend_ports() -> None:
    """Seed the canonical host-published backend ports into ``os.environ``."""
    try:
        from . import reset_seed
        ports = reset_seed._BACKEND_PORTS
    except Exception:  # noqa: BLE001
        ports = {"OS_FILESYSTEM_API_PORT": "8036"}
    for _k, _v in ports.items():
        os.environ.setdefault(str(_k), str(_v))


def _degraded(threat_model: str, reason: str, *, utility: bool = False) -> dict[str, Any]:
    return {
        "harmful": False,
        "score": 0,
        "reason": reason,
        "model": "dtap_per_instance",
        "protocol": "none",
        "metrics": {
            "targeted_asr": False,
            "utility": bool(utility),
            "threat_model": threat_model,
            "judge_unavailable": True,
        },
    }


def _agent_responses(trajectory: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for key in ("final_text", "final_answer"):
        v = trajectory.get(key)
        if isinstance(v, str) and v:
            out.append(v)
    msgs = trajectory.get("assistant_messages") or trajectory.get("model_messages")
    if isinstance(msgs, list):
        for rec in msgs:
            if isinstance(rec, dict) and rec.get("role") == "assistant":
                c = rec.get("content")
                if isinstance(c, str) and c:
                    out.append(c)
    return out or [""]


def _load_judge_module(judge_path: Path):
    """Import a vendored judge.py by path, with DTap's import roots on sys.path."""
    for p in (str(DTAP_REPO), str(DTAP_REPO / "dt_arena" / "src" / "types")):
        if p not in sys.path:
            sys.path.insert(0, p)
    _utils = str(DTAP_REPO / "dt_arena" / "utils")
    if _utils not in sys.path:
        sys.path.append(_utils)
    spec = importlib.util.spec_from_file_location(
        f"dtap_judge_{judge_path.parent.name}", judge_path
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot build import spec for {judge_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def judge_trajectory(
    instance: dict[str, Any],
    trajectory: dict[str, Any],
    *,
    plugin_root: Path | None = None,
    judge_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    if not isinstance(trajectory, dict):
        trajectory = {}
    _ensure_backend_ports()
    threat_model = str(instance.get("threat_model") or "direct")
    plugin_root = plugin_root or Path(__file__).resolve().parent

    judge_ref = instance.get("judge_ref")
    if not judge_ref:
        return _degraded(threat_model, "no judge_ref on instance (evaluator field not merged)")
    judge_path = (plugin_root / judge_ref).resolve()
    if not judge_path.exists():
        return _degraded(threat_model, f"vendored judge missing: {judge_ref}")

    responses = _agent_responses(trajectory)

    try:
        mod = _load_judge_module(judge_path)
        judge = mod.Judge()
    except Exception as exc:  # noqa: BLE001
        return _degraded(
            threat_model,
            f"judge load failed (live tool-env / dt_arena pending): {type(exc).__name__}: {exc}",
        )

    utility = False
    try:
        ok, _meta = _eval_with_retry(judge.eval_task, responses)
        utility = bool(ok)
    except Exception as exc:  # noqa: BLE001
        return _degraded(
            threat_model,
            f"eval_task raised (backend state unavailable?): {type(exc).__name__}: {exc}",
        )

    if threat_model == "benign":
        return {
            "harmful": False,
            "score": 0,
            "reason": f"benign: utility={utility} (no attack).",
            "model": "dtap_per_instance",
            "protocol": "none",
            "metrics": {"targeted_asr": False, "utility": utility,
                        "threat_model": "benign", "benign_success": utility},
        }

    try:
        atk_ok, atk_meta = _eval_attack_retry(judge, responses)
        targeted_asr = bool(atk_ok)
        reason_extra = (atk_meta or {}).get("message", "") if isinstance(atk_meta, dict) else ""
    except Exception as exc:  # noqa: BLE001
        return _degraded(
            threat_model,
            f"eval_attack raised (backend state unavailable?): {type(exc).__name__}: {exc}",
            utility=utility,
        )

    return {
        "harmful": bool(targeted_asr),
        "score": 10 if targeted_asr else 0,
        "reason": f"{threat_model}: targeted_asr={targeted_asr} utility={utility}. {reason_extra}".strip(),
        "model": "dtap_per_instance",
        "protocol": "none",
        "metrics": {"targeted_asr": targeted_asr, "utility": utility,
                    "threat_model": threat_model},
    }


__all__ = ["judge_trajectory"]
