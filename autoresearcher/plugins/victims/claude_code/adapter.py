"""Claude Code victim adapter (Docker-sandboxed)."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from autoresearch_redteam import victim_harness

logger = logging.getLogger(__name__)


DEFAULT_IMAGE = "ar_claude_code_base:latest"
DEFAULT_MODEL = "claude-haiku-4-5"


class ClaudeCodeAdapter:
    """Docker-sandboxed Claude Code victim adapter."""

    name = "claude_code"
    default_model = DEFAULT_MODEL
    supports_attack_families = ("multi_turn",)

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        victim_anthropic_base_url: str | None = None,
        victim_anthropic_auth_token: str | None = None,
        timeout_seconds: int = 600,
        image: str = DEFAULT_IMAGE,
        cpus: float = 2.0,
        memory: str = "4g",
    ):
        self.model_slug = model
        self.timeout_seconds = timeout_seconds
        self.image = image
        self.cpus = cpus
        self.memory = memory

        self.victim_base_url = (
            victim_anthropic_base_url
            or os.environ.get("VICTIM_BASE_URL")
            or os.environ.get("ANTHROPIC_BASE_URL")
        )
        if not self.victim_base_url:
            raise RuntimeError(
                "claude_code adapter needs a victim endpoint — set "
                "VICTIM_BASE_URL (or ANTHROPIC_BASE_URL) to the direct "
                "provider endpoint in .env, or run /setup."
            )
        self.victim_auth_token = (
            victim_anthropic_auth_token
            or os.environ.get("VICTIM_API_KEY")
            or os.environ.get("VICTIM_AUTH_TOKEN")
            or os.environ.get("ANTHROPIC_AUTH_TOKEN")
        )
        if not self.victim_auth_token:
            raise RuntimeError(
                "claude_code adapter needs a victim key — set VICTIM_API_KEY "
                "(+ VICTIM_BASE_URL) in .env, or run /setup."
            )

    def run(self, input_spec: dict[str, Any]) -> dict[str, Any]:
        """Spawn one container; return parsed trajectory dict.

        The returned dict has whatever shape the in-container runner wrote
        to /harness/trajectory.json plus a `_container` envelope with rc,
        stderr_tail, container error info.

        The scenario image is selected via ``input_spec["docker_image"]``
        (``run_attack._build_input_spec`` populates this from
        ``contract.runtime.docker_image``). If unset / empty, the adapter
        uses its constructor default (``self.image``, normally
        ``ar_claude_code_base:latest``).
        """
        image = input_spec.get("docker_image") or self.image
        spec_json = json.dumps(input_spec, ensure_ascii=False)
        # Claude Code container environment.
        container_env = {
            "ANTHROPIC_BASE_URL": self.victim_base_url,
            "ANTHROPIC_AUTH_TOKEN": self.victim_auth_token,
            "ANTHROPIC_API_KEY": "",
            "CLAUDE_CODE_STREAM_CLOSE_TIMEOUT": "180000",
            "CLAUDE_AGENT_SDK_SKIP_VERSION_CHECK": "1",
            # Mark root-capable containers as sandboxed.
            "IS_SANDBOX": "1",
        }
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

        This file lives at ``autoresearcher/plugins/victims/claude_code/adapter.py``
        so ``parents[2]`` is the plugins root. We resolve via __file__ rather
        than cwd so the mount path is stable regardless of where run_attack
        is launched from.
        """
        here = Path(__file__).resolve()
        plugins = here.parents[2]  # plugins root
        return plugins if (plugins.name == "plugins" and plugins.is_dir()) else None
