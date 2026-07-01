"""Planned raw LLM framework adapter.

When implemented, this adapter wraps a single text-only chat-completion
victim (OpenAI-compatible /v1/chat/completions) — no agent runtime, no
tools, no Docker sandbox needed (the victim does not execute side
effects). Use with chat-level jailbreak scenarios.

Expected input_spec shape (what the scenario's build_input_spec
produces and this adapter would consume):

    {
        "model": "<slug>",
        "messages": [
            {"role": "user", "content": "<turn 1>"},
            ...   # single_turn uses one message; multi_turn allowed
        ],
        "system": "<optional system prompt>",
        "temperature": <float>,
    }
"""
from __future__ import annotations


class RawLLMAdapter:
    name = "raw_llm"
    default_model = "gpt-5"
    supports_attack_families = ("single_turn", "multi_turn")

    def __init__(self, *, model: str | None = None, timeout_seconds: int = 120, **_):
        raise NotImplementedError(
            "raw_llm adapter is a planned extension. Implement against "
            "an OpenAI-compatible chat-completions endpoint. One POST per "
            "attack; return {'assistant_messages': [...], 'result_meta': "
            "{...}} matching the universal trajectory_payload shape."
        )

    def run(self, input_spec):
        raise NotImplementedError
