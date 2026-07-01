"""Planned raw VLM framework adapter.

When implemented, this adapter wraps a single vision-language-model
victim (OpenAI-compatible /v1/chat/completions that accepts image_url
content blocks) — no agent runtime, no tools. Use with multimodal
jailbreak scenarios (typographic injections, FigStep-style flowcharts,
HADES-style visual context priming).

Expected input_spec shape:

    {
        "model": "<slug>",
        "messages": [
            {"role": "user", "content": [
                {"type": "text", "text": "<question>"},
                {"type": "image_url",
                 "image_url": {"url": "data:image/png;base64,..."}},
            ]},
        ],
        "system": "<optional>",
        "temperature": <float>,
    }
"""
from __future__ import annotations


class RawVLMAdapter:
    name = "raw_vlm"
    default_model = "gpt-5-vision"
    supports_attack_families = ("single_turn", "multi_turn", "multimodal_injection")

    def __init__(self, *, model: str | None = None, timeout_seconds: int = 180, **_):
        raise NotImplementedError(
            "raw_vlm adapter is a planned extension. Implement against "
            "an OpenAI-compatible chat-completions endpoint that accepts "
            "image_url content blocks. Images can be passed as base64 "
            "data URLs or as remote URLs the endpoint can fetch."
        )

    def run(self, input_spec):
        raise NotImplementedError
