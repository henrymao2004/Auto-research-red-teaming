"""Codex victim adapter (Docker-sandboxed).

Mirrors :class:`ClaudeCodeAdapter`'s host-side shape but drives the
OpenAI ``codex`` CLI inside ``ar_codex:latest`` instead of the
claude-agent-sdk. Pure victim concerns:

  - spawn the container (``input_spec["docker_image"]`` or the adapter's
    default ``ar_codex:latest``);
  - per-attack tempdir split into ``/work`` (agent cwd) + ``/harness``
    (trajectory output only) — handled by ``victim_harness.run_in_docker``;
  - pipe the attack spec to the in-container runner via **stdin** so it
    never lands on a bind-mounted path;
  - read ``trajectory.json`` back from ``/harness``.

codex talks to the victim model via OpenRouter (``OPENROUTER_API_KEY``).
The container env carries the OpenRouter key + ``CODEX_HOME`` only (NO
``ANTHROPIC_*`` — codex does not use them). Scenario MCP tools + IPI
interceptors (when the contract declares an ``mcp_tools_module``) are
handled inside the container by the runner's STDIO MCP server; the host
adapter is unchanged by that — it only spawns the container and reads the
trajectory back.
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
    # Attack families handled by the runner.
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

        # Model endpoint key for the runner config.
        self.api_key = (
            openrouter_api_key
            or os.environ.get("MOONBRIDGE_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
            or os.environ.get("ROUTER_API_KEY")
            or "moonbridge"
        )

    def run(self, input_spec: dict[str, Any]) -> dict[str, Any]:
        """Spawn one container; return the parsed trajectory dict.

        The codex victim ALWAYS runs ``ar_codex`` (which bakes the codex
        runner). It must NOT use ``input_spec["docker_image"]`` — that is the
        scenario's *claude-flavored* image (FROM ar_claude_code_base, baking the
        claude in_container_runner), which would run the wrong agent. Scenario
        deps that codex needs (e.g. agentdojo's pip package) are baked into
        ``ar_codex`` (or a codex-flavored scenario image) rather than taken from
        the claude scenario image.
        """
        image = self.image
        spec_json = json.dumps(input_spec, ensure_ascii=False)
        # Codex container environment.
        container_env = {
            # Provider key aliases.
            "MOONBRIDGE_API_KEY": self.api_key,
            "OPENROUTER_API_KEY": self.api_key,
            "CODEX_HOME": "/tmp/codex_home",
        }
        # Forward codex endpoint overrides.
        for _k in ("CODEX_RESPONSES_BASE_URL", "CODEX_API_KEY_ENV"):
            _v = os.environ.get(_k)
            if _v:
                container_env[_k] = _v
        # Forward the selected provider key.
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
        """Locate the host's ``autoresearcher/plugins`` directory.

        This file lives at ``plugins/victims/codex/adapter.py`` so
        ``parents[2]`` is the plugins root.
        """
        here = Path(__file__).resolve()
        plugins = here.parents[2]  # plugins root
        return plugins if (plugins.name == "plugins" and plugins.is_dir()) else None
