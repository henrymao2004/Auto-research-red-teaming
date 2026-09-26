"""Codex victim adapter (Docker-sandboxed).

Same host-side shape as :class:`ClaudeCodeAdapter`, but drives the OpenAI
``codex`` CLI inside ``ar_codex:latest``. The attack spec is piped over
stdin; scenario MCP tools and interceptors are handled in the container by
the runner's STDIO MCP server. The container gets the provider key and
``CODEX_HOME`` only, no ``ANTHROPIC_*`` variables.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from autoresearch_redteam import victim_harness

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "ar_codex:latest"
DEFAULT_MODEL = "deepseek-v4-pro"


class CodexAdapter:
    """Docker-sandboxed OpenAI codex CLI victim adapter."""

    name = "codex"
    default_model = DEFAULT_MODEL
    supports_attack_families = (
        "multi_turn",
        "multi_turn_user_prompt_ratchet",
        "indirect_prompt_injection",
    )

    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        openrouter_api_key: str | None = None,
        timeout_seconds: int = 600,
        image: str = DEFAULT_IMAGE,
        cpus: float = 2.0,
        memory: str = os.environ.get("CODEX_MEMORY", "8g"),
        **kwargs: Any,
    ):
        self.model_slug = model
        self.timeout_seconds = timeout_seconds
        self.image = image
        self.cpus = cpus
        self.memory = memory

        self.api_key = (
            openrouter_api_key
            or os.environ.get("MOONBRIDGE_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ROUTER_API_KEY")
            or "moonbridge"
        )

    def run(self, input_spec: dict[str, Any]) -> dict[str, Any]:
        """Spawn one container and return the parsed trajectory dict.

        Always uses ``self.image``: ``input_spec["docker_image"]`` is the
        scenario's claude-based image and would run the wrong agent.
        """
        image = self.image
        spec_json = json.dumps(input_spec, ensure_ascii=False)
        container_env = {
            "MOONBRIDGE_API_KEY": self.api_key,
            "OPENROUTER_API_KEY": self.api_key,
            "CODEX_HOME": "/tmp/codex_home",
        }
        # Forward codex endpoint overrides.
        for _k in ("CODEX_RESPONSES_BASE_URL", "CODEX_API_KEY_ENV"):
            _v = os.environ.get(_k)
            if _v:
                container_env[_k] = _v
        _key_env = os.environ.get("CODEX_API_KEY_ENV")
        if _key_env and os.environ.get(_key_env):
            container_env[_key_env] = os.environ[_key_env]
        return victim_harness.run_in_docker(
            image, spec_json, container_env,
            work_tmpfs_size="2g",
            cpus=self.cpus,
            memory=self.memory,
            timeout_seconds=self.timeout_seconds,
            plugins_dir=self._find_plugins_dir(),
        )

    @staticmethod
    def _find_plugins_dir() -> Path | None:
        """Locate the host's ``autoresearcher/plugins`` directory."""
        here = Path(__file__).resolve()
        plugins = here.parents[2]
        return plugins if (plugins.name == "plugins" and plugins.is_dir()) else None
