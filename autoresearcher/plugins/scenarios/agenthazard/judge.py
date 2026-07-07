"""AgentHazard-style LLM judge.

Single LLM call per trajectory: feed the harmful goal + full agent trajectory,
get back {harmful: bool, score: 0-10, reason: str}.

Adapted from AgentHazard's run/llm_judge.py (https://github.com/Yunhao-Feng/AgentHazard).

## Endpoint

Talks to **OpenAI-compatible** chat-completions (OpenAI / OpenRouter /
DeepSeek / Together / Moonshot / local vLLM / sglang / ...) **or** the
**Anthropic Messages API**, selected by the base URL or
``JUDGE_PROTOCOL`` env override. Configured via env:

    JUDGE_BASE_URL  (default https://openrouter.ai/api/v1)
    JUDGE_API_KEY   (required at call time)
    JUDGE_MODEL     (default google/gemini-3-flash-preview)
    JUDGE_PROTOCOL  (optional: ``openai`` | ``anthropic``;
                     auto-detected from JUDGE_BASE_URL when unset)

Auto-detection: a base URL containing ``anthropic`` is treated as
Anthropic; everything else is treated as OpenAI-compatible. Set
``JUDGE_PROTOCOL`` explicitly to override (e.g. when using a proxy
that doesn't follow the naming pattern).
"""
from __future__ import annotations

import json
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


_HERE = Path(__file__).resolve().parent
_JUDGE_PROMPT_PATH = _HERE / "judge" / "agenthazard_official.md"


@lru_cache(maxsize=1)
def _judge_prompt() -> str:
    """Load the AgentHazard-official judge prompt from disk.

    Path: ``plugins/scenarios/agenthazard/judge/agenthazard_official.md``.
    Cached after first call (the template never changes within a process).
    The corresponding ``judge.prompt_hash`` is pinned in ``contract.yaml``
    so silent prompt edits surface at contract-load time.
    """
    return _JUDGE_PROMPT_PATH.read_text()


def _default_base_url() -> str:
    return os.environ.get("JUDGE_BASE_URL", "https://openrouter.ai/api/v1")


def _default_model() -> str:
    return os.environ.get("JUDGE_MODEL", "google/gemini-3-flash-preview")


def _resolve_protocol(base_url: str) -> str:
    """Pick 'openai' or 'anthropic' based on env override or base URL."""
    override = os.environ.get("JUDGE_PROTOCOL", "").strip().lower()
    if override in ("openai", "anthropic"):
        return override
    return "anthropic" if "anthropic" in (base_url or "").lower() else "openai"


def _call_openai(*, base_url: str, api_key: str, model: str, prompt: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=base_url)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        max_tokens=512,
    )
    return resp.choices[0].message.content or ""


def _call_anthropic(*, base_url: str, api_key: str, model: str, prompt: str) -> str:
    from anthropic import Anthropic
    client = Anthropic(api_key=api_key, base_url=base_url or None)
    msg = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    parts: list[str] = []
    for block in (msg.content or []):
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "".join(parts)


def judge_trajectory(
    instance: dict[str, Any],
    trajectory: list[dict[str, Any]],
    judge_model: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    max_retries: int = 3,
    detail_logs: dict | None = None,
) -> dict[str, Any]:
    """Score a single agent trajectory against an AgentHazard instance.

    Judge prompt is the official AgentHazard ``run/llm_judge.py`` prompt
    verbatim (with the ``comment`` field included).

    Args:
        instance: AgentHazard instance dict — ``query``, ``category``,
            ``jailbreak_method``, ``comment`` (all four expected by the prompt).
        trajectory: list of assistant/tool message dicts captured by the adapter.
        judge_model: model ID (overrides ``JUDGE_MODEL`` env).
        api_key: judge endpoint key (overrides ``JUDGE_API_KEY`` env).
        base_url: judge base URL (overrides ``JUDGE_BASE_URL`` env).
        max_retries: parse retries on bad JSON output.
        detail_logs: optional structured tool-call detail dict (gets rendered
            into the official-prompt ``Detail Logs`` section).

    Returns:
        ``{"harmful": bool, "score": int, "reason": str, "raw": str}``
    """
    key = api_key or os.environ.get("JUDGE_API_KEY")
    base = base_url or _default_base_url()
    model = judge_model or _default_model()
    protocol = _resolve_protocol(base)
    if not key:
        return {"harmful": False, "score": 0,
                "reason": "JUDGE_API_KEY not set; judge skipped", "raw": "",
                "model": model, "protocol": protocol}

    detail_logs_section = ""
    if detail_logs:
        detail_logs_section = (
            "\n\n【详细工具调用日志（Detail Logs）】\n"
            + json.dumps(detail_logs, ensure_ascii=False, indent=2)
        )
    prompt = _judge_prompt().format(
        target=instance.get("query", ""),
        comment=instance.get("comment", ""),
        jailbreak_method=instance.get("jailbreak_method", ""),
        category=instance.get("category", ""),
        trajectory=json.dumps(trajectory, ensure_ascii=False, indent=2)[:30000],
        detail_logs_section=detail_logs_section,
    )

    last_err = ""
    for attempt in range(max_retries):
        try:
            if protocol == "anthropic":
                text = _call_anthropic(
                    base_url=base, api_key=key, model=model, prompt=prompt,
                )
            else:
                text = _call_openai(
                    base_url=base, api_key=key, model=model, prompt=prompt,
                )
            t = text.strip()
            if t.startswith("```"):
                t = t.split("```", 2)[1]
                if t.startswith("json"):
                    t = t[4:].strip()
                t = t.split("```")[0].strip()
            try:
                parsed = json.loads(t)
            except json.JSONDecodeError:
                # Repair common JSON wrapper issues.
                import re as _re
                t2 = _re.sub(r",(\s*[}\]])", r"\1", t)
                try:
                    parsed = json.loads(t2)
                except json.JSONDecodeError:
                    _m = _re.search(r"\{.*\}", t2, _re.DOTALL)
                    if not _m:
                        raise
                    parsed = json.loads(_re.sub(r",(\s*[}\]])", r"\1", _m.group(0)))
            return {
                "harmful": bool(parsed.get("harmful", False)),
                "score": int(parsed.get("score", 0)),
                "reason": str(parsed.get("reason", "")),
                "raw": text,
                "model": model,
                "protocol": protocol,
            }
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            logger.warning("judge attempt %d failed (%s): %s",
                           attempt + 1, protocol, last_err)

    return {"harmful": False, "score": 0,
            "reason": f"judge failed after {max_retries} attempts: {last_err}",
            "raw": "", "model": model, "protocol": protocol}
