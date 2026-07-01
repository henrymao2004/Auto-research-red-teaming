"""Runs inside the codex victim container (``ar_codex:latest``).

Reads the attack spec from **stdin** (piped by the host adapter) and
writes ``/harness/trajectory.json``. Mirrors the structure of the
claude_code ``in_container_runner.py::main_async`` but drives the
``codex exec`` CLI instead of the claude-agent-sdk.

Two scenario shapes are handled:

- **no-MCP** (agenthazard-style multi-turn user messages, codex's
  built-in tools): just drive ``codex exec`` per user turn.
- **MCP + IPI** (agentdyn-style): when the scenario declares an
  ``mcp_tools_module``, the runner templates a
  ``[mcp_servers.scenario_tools]`` STDIO block into the codex config and
  codex spawns ``scenario_mcp_stdio.py``, which re-serves the scenario's
  tools and applies the ``tool_response_interceptors`` to each tool's
  output (the codex IPI path — claude_code does this in a PostToolUse
  hook; codex does it at the MCP server). After the run the runner reads
  back the server-serialized ``post_environment`` for the judge.

The model-agnostic contract dispatch (spec normalisation, user-turn
derivation, env hydration, interceptor resolution, trajectory filtering)
is reused verbatim from ``runner_core`` so this module stays
codex-specific only.

codex transport (CONFIRMED working against deepseek via OpenRouter):

- ``codex exec --json --skip-git-repo-check
  --dangerously-bypass-approvals-and-sandbox "<prompt>" < /dev/null``
  emits JSONL events on stdout:
    - ``thread.started``   — has ``thread_id``
    - ``turn.started``
    - ``item.completed``   — has ``item`` with ``type`` in
        {``agent_message`` (has ``text``), ``command_execution``,
         ``mcp_tool_call`` (has ``server``/``tool``/``arguments``/``result``/
         ``status``), ``reasoning``}
    - ``turn.completed``   — has ``usage``
    - ``error`` / ``turn.failed`` on failure
- Resume a thread for the next user turn:
  ``codex exec resume <thread_id> --json ... "<next prompt>" < /dev/null``

``$CODEX_HOME`` points at a writable temp dir; we template its
``config.toml`` with the OpenRouter provider block before the first turn.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
from pathlib import Path
from typing import Any

# Shared contract dispatch.
from runner_core import (
    GENERIC_KICKOFF,
    HARNESS,
    WORK,
    _filter_trajectory,
    _hydrate_environment,
    _normalise_input,
    _user_turns_for_wiring,
)

DEFAULT_MODEL = "deepseek/deepseek-v4-pro"


def _normalise_model(slug: str | None) -> str:
    """Pass the victim model slug to Moon Bridge verbatim.

    Moon Bridge resolves the name against its own config (the ``models:``
    aliases + each provider's ``offers``), so a bare slug like
    ``deepseek-v4-pro`` or ``minimax-m2.7`` already routes to the right
    upstream. We do NOT guess a ``<vendor>/`` prefix — hardcoding one
    mis-routes every model whose vendor we didn't enumerate (e.g.
    ``minimax-m2.7`` -> ``deepseek/minimax-m2.7`` -> 400 from DeepSeek).
    """
    s = (slug or "").strip()
    return s or DEFAULT_MODEL


def _toml_escape(s: str) -> str:
    """Escape a string for a TOML basic (double-quoted) string value."""
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _write_codex_config(
    codex_home: Path,
    model: str,
    mcp_server_env: dict[str, str] | None = None,
) -> Path:
    """Template ``$CODEX_HOME/config.toml`` with the OpenRouter provider.

    When ``mcp_server_env`` is provided (the scenario declared an
    ``mcp_tools_module``), a ``[mcp_servers.scenario_tools]`` STDIO block
    is appended — codex spawns ``scenario_mcp_stdio.py`` and routes the
    scenario's tools through it (the codex analogue of claude_code's
    in-process SDK MCP server). Tool-output interceptors are applied
    inside that server. The OpenRouter API key is read from
    ``OPENROUTER_API_KEY`` at runtime via ``env_key`` — never in the file.
    """
    codex_home.mkdir(parents=True, exist_ok=True)
    # Configure the Responses endpoint.
    base_url = os.environ.get(
        "CODEX_RESPONSES_BASE_URL", "http://host.docker.internal:38440/v1")
    key_env = os.environ.get("CODEX_API_KEY_ENV", "MOONBRIDGE_API_KEY")
    config = f"""model = "{model}"
model_provider = "moonbridge"


[model_providers.moonbridge]
name = "MoonBridge"
base_url = "{base_url}"
env_key = "{key_env}"
wire_api = "responses"
"""
    # Disable built-in web search.
    config = config.replace(
        f'model = "{model}"\n',
        f'model = "{model}"\nweb_search = "disabled"\n', 1)
    if mcp_server_env:
        env_pairs = ", ".join(
            f'"{_toml_escape(k)}" = "{_toml_escape(v)}"'
            for k, v in mcp_server_env.items()
        )
        config += f"""
[mcp_servers.scenario_tools]
command = "python3"
args = ["/app/scenario_mcp_stdio.py"]
env = {{ {env_pairs} }}
"""
    target = codex_home / "config.toml"
    target.write_text(config)
    print(f"[runner] wrote codex config to {target} (model={model!r}"
          f"{', +scenario MCP' if mcp_server_env else ', no-MCP'})",
          file=sys.stderr)
    return target


def _prepare_scenario_mcp(
    norm: dict[str, Any],
    codex_home: Path,
    env_state: dict[str, Any] | None,
) -> tuple[dict[str, str], str]:
    """Stage the STDIO MCP server's launch files; return its env + post-env path.

    Writes ``instance`` / ``env_state`` / resolved ``interceptors`` to a
    private dir under ``$CODEX_HOME`` (NOT a bind mount, so a probing victim
    can't read its own attack plan) and returns the env-var block codex
    injects when it spawns ``scenario_mcp_stdio.py`` plus the path that
    server writes the post-attack environment to.
    """
    mcp_dir = codex_home / "scenario_mcp"
    mcp_dir.mkdir(parents=True, exist_ok=True)

    instance_path = mcp_dir / "instance.json"
    env_state_path = mcp_dir / "env_state.json"
    interceptors_path = mcp_dir / "interceptors.json"
    post_env_path = mcp_dir / "post_env.json"

    instance_path.write_text(
        json.dumps(norm.get("instance") or {}, ensure_ascii=False))
    env_state_path.write_text(
        json.dumps(env_state or {}, ensure_ascii=False))
    interceptors_path.write_text(
        json.dumps(norm.get("interceptors") or [], ensure_ascii=False))

    mcp_server_env = {
        "SCENARIO_MCP_MODULE": str(norm.get("mcp_tools_module") or ""),
        "SCENARIO_MCP_INSTANCE": str(instance_path),
        "SCENARIO_MCP_ENV_STATE": str(env_state_path),
        "SCENARIO_MCP_INTERCEPTORS": str(interceptors_path),
        "SCENARIO_MCP_POST_ENV": str(post_env_path),
        "PYTHONUNBUFFERED": "1",
    }
    print(f"[runner] staged scenario MCP launch files in {mcp_dir}",
          file=sys.stderr)
    return mcp_server_env, str(post_env_path)


_CODING_SURFACE_MARKERS = {"Bash", "BashOutput", "KillShell", "Read", "Write", "Edit"}

_CODEX_NONMCP_FEATURES = ["shell_tool", "unified_exec", "browser_use",
                          "computer_use", "image_generation"]


def _codex_disables_for(disallowed_tools: Any) -> list[str]:
    """Map a scenario's `disallowed_tools` to codex `--disable` feature flags.

    Returns the non-MCP feature set when the scenario removes the built-in
    coding surface (any shell/file tool in `disallowed_tools`); else empty.
    codex has no per-named-tool removal like claude, so this is feature-grained:
    `shell_tool` disables the whole shell rather than individual `Bash` etc.
    """
    if not disallowed_tools:
        return []
    names = {str(t) for t in disallowed_tools}
    if names & _CODING_SURFACE_MARKERS:
        return list(_CODEX_NONMCP_FEATURES)
    return []


def _run_codex_turn(
    prompt: str,
    *,
    thread_id: str | None,
    codex_home: str,
    timeout_seconds: int,
    disable_features: list[str] | None = None,
) -> subprocess.CompletedProcess:
    """Run one ``codex exec`` (or ``codex exec resume``) turn.

    Spec piped via stdin elsewhere; the codex prompt is passed as an argv
    positional. stdin is closed (``/dev/null``) so codex doesn't block
    waiting for interactive input.

    ``disable_features`` are codex feature flags turned off via repeated
    ``--disable`` (e.g. ``shell_tool``). This is the codex analogue of the
    claude runner's ``disallowed_tools``: when a scenario removes the built-in
    coding surface (dtagent forces MCP-only), we disable codex's non-MCP tool
    features so the only tools left are the scenario's ``mcp__*`` servers.
    """
    base = [
        "codex", "exec",
    ]
    if thread_id:
        base += ["resume", thread_id]
    base += [
        "--json",
        "--skip-git-repo-check",
        "--dangerously-bypass-approvals-and-sandbox",
    ]
    for feat in (disable_features or []):
        base += ["--disable", feat]
    base += [prompt]
    env = dict(os.environ)
    env["CODEX_HOME"] = codex_home
    print(f"[runner] codex turn (resume={bool(thread_id)}) prompt[:80]="
          f"{prompt[:80]!r}", file=sys.stderr)
    return subprocess.run(
        base,
        cwd=str(WORK),
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _parse_jsonl(stdout: str) -> list[dict[str, Any]]:
    """Parse codex ``--json`` JSONL stdout into a list of event dicts.

    Non-JSON lines (stray logging) are skipped, not fatal.
    """
    events: list[dict[str, Any]] = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"[runner] non-JSON codex line skipped: {line[:120]!r}",
                  file=sys.stderr)
    return events


def _event_type(ev: dict[str, Any]) -> str:
    """codex events carry their kind under ``type`` (e.g. 'item.completed')."""
    return str(ev.get("type") or "")


def _item_of(ev: dict[str, Any]) -> dict[str, Any]:
    """Extract the ``item`` payload from an ``item.completed`` event.

    Some codex builds nest the item under ``item``; tolerate both the
    nested and the flattened shape.
    """
    item = ev.get("item")
    if isinstance(item, dict):
        return item
    return ev


def main() -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print("FATAL: empty stdin (expected input_spec JSON)", file=sys.stderr)
        return 1
    spec = json.loads(raw)
    norm = _normalise_input(spec)

    model = _normalise_model(norm.get("model"))
    mcp_module = norm.get("mcp_tools_module")
    print(f"[runner] wiring_kind={norm['wiring_kind']!r} model={model!r} "
          f"env_hydration={(norm['env_hydration'] or {}).get('kind','-')} "
          f"mcp_tools_module={mcp_module or '-'} "
          f"interceptors={len(norm.get('interceptors') or [])}",
          file=sys.stderr)

    codex_home = os.environ.get("CODEX_HOME") or "/tmp/codex_home"

    env_state: dict[str, Any] | None = None
    try:
        env_state = _hydrate_environment(norm["env_hydration"])
    except Exception as e:  # noqa: BLE001
        print(f"[runner] WARN hydration failed: {e!r}", file=sys.stderr)

    post_env_path: str | None = None
    mcp_server_env: dict[str, str] | None = None
    if mcp_module:
        try:
            mcp_server_env, post_env_path = _prepare_scenario_mcp(
                norm, Path(codex_home), env_state,
            )
        except Exception as e:  # noqa: BLE001
            print(f"[runner] WARN could not stage scenario MCP server: {e!r}",
                  file=sys.stderr)
            traceback.print_exc(file=sys.stderr)

    try:
        _write_codex_config(Path(codex_home), model, mcp_server_env)
    except Exception as e:  # noqa: BLE001
        print(f"[runner] FATAL could not write codex config: {e!r}",
              file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        _write_error_trajectory(norm, f"config write failed: {e}")
        return 2

    runtime_spec = spec.get("runtime_spec") or {}
    disallowed_tools = (runtime_spec.get("disallowed_tools")
                        or norm.get("disallowed_tools") or [])
    codex_disables = _codex_disables_for(disallowed_tools)
    if codex_disables:
        print(f"[runner] disallowed_tools={list(disallowed_tools)} -> "
              f"codex --disable {codex_disables}", file=sys.stderr)

    user_turns = _user_turns_for_wiring(norm)
    if not user_turns:
        user_turns = [GENERIC_KICKOFF]

    per_turn_timeout = int(os.environ.get("CODEX_PER_TURN_TIMEOUT", "900"))

    collected: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []
    tool_outputs: list[dict[str, Any]] = []
    reasoning_texts: list[str] = []
    final_text = ""
    result_meta: dict[str, Any] = {}
    error: str | None = None
    thread_id: str | None = None

    for idx, turn in enumerate(user_turns):
        collected.append({"role": "user", "content": turn})
        try:
            proc = _run_codex_turn(
                turn,
                thread_id=thread_id,
                codex_home=codex_home,
                timeout_seconds=per_turn_timeout,
                disable_features=codex_disables,
            )
        except subprocess.TimeoutExpired:
            error = f"codex turn {idx} timed out after {per_turn_timeout}s"
            print(f"[runner] {error}", file=sys.stderr)
            break
        except Exception as e:  # noqa: BLE001
            error = f"{type(e).__name__}: {e}"
            traceback.print_exc(file=sys.stderr)
            break

        if proc.stderr:
            print(f"[codex-cli-stderr] {proc.stderr[-2000:]}", file=sys.stderr)

        events = _parse_jsonl(proc.stdout)
        turn_error = _consume_events(
            events, collected, tool_calls, tool_outputs, reasoning_texts,
        )
        for ev in events:
            if _event_type(ev) == "item.completed":
                item = _item_of(ev)
                if item.get("type") == "agent_message" and item.get("text"):
                    final_text = item["text"]
            elif _event_type(ev) == "thread.started" and ev.get("thread_id"):
                thread_id = ev["thread_id"]
            elif _event_type(ev) == "turn.completed":
                usage = ev.get("usage")
                if usage is not None:
                    result_meta["usage"] = usage

        if turn_error and error is None:
            error = turn_error
        if proc.returncode != 0 and error is None:
            error = (f"codex turn {idx} exited rc={proc.returncode}: "
                     f"{(proc.stderr or '')[-500:]}")
        if error is not None:
            break
        if thread_id is None:
            if idx < len(user_turns) - 1:
                print("[runner] WARN no thread_id from first turn; cannot "
                      "resume for remaining turns", file=sys.stderr)
            break

    result_meta.setdefault("wiring_kind", norm["wiring_kind"])
    result_meta.setdefault("thread_id", thread_id)
    result_meta.setdefault(
        "env_hydration_kind",
        (norm["env_hydration"] or {}).get("kind") if norm["env_hydration"] else None,
    )

    out: dict[str, Any] = {
        "tool_calls": tool_calls,
        "tool_outputs": tool_outputs,
        "assistant_messages": collected,
        "model_messages": collected,
        "reasoning": "\n\n".join(reasoning_texts) if reasoning_texts else None,
        "final_text": final_text,
        "final_answer": final_text,
        "result_meta": result_meta,
        "error": error,
    }

    # Attach post-run environment.
    if post_env_path:
        try:
            out["post_environment"] = json.loads(Path(post_env_path).read_text())
        except FileNotFoundError:
            out["post_environment"] = None
            print("[runner] no post_environment file (model called no scenario "
                  "tool, or MCP server failed to start)", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            out["post_environment"] = None
            print(f"[runner] WARN post_environment read failed: {e!r}",
                  file=sys.stderr)

    out = _filter_trajectory(out, norm.get("trajectory_capture"))
    (HARNESS / "trajectory.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2)
    )
    return 0 if error is None else 2


def _consume_events(
    events: list[dict[str, Any]],
    collected: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]],
    tool_outputs: list[dict[str, Any]],
    reasoning_texts: list[str],
) -> str | None:
    """Map one turn's codex events into the trajectory accumulators.

    Returns an error string if the turn emitted ``error`` / ``turn.failed``,
    else None.
    """
    turn_error: str | None = None
    for ev in events:
        etype = _event_type(ev)
        if etype in ("error", "turn.failed"):
            msg = ev.get("message") or ev.get("error") or json.dumps(ev)
            turn_error = f"codex {etype}: {msg}"
            print(f"[runner] {turn_error}", file=sys.stderr)
            continue
        if etype != "item.completed":
            continue
        item = _item_of(ev)
        itype = item.get("type")
        if itype == "agent_message":
            text = item.get("text") or ""
            if text:
                collected.append({"role": "assistant", "content": text,
                                  "tool_calls": []})
        elif itype == "reasoning":
            rtext = item.get("text") or item.get("reasoning") or ""
            if rtext:
                reasoning_texts.append(rtext)
        elif itype == "mcp_tool_call":
            tool_calls.append({
                "name": item.get("tool") or "",
                "arguments": item.get("arguments") or {},
            })
            result = item.get("result")
            if result is not None:
                tool_outputs.append({
                    "name": item.get("tool") or "",
                    "output": result,
                    "status": item.get("status"),
                })
        elif itype == "command_execution":
            args = {k: v for k, v in item.items()
                    if k not in ("type", "id")}
            tool_calls.append({"name": "shell", "arguments": args})
            output = (item.get("output")
                      or item.get("aggregated_output")
                      or item.get("result"))
            if output is not None:
                tool_outputs.append({
                    "name": "shell",
                    "output": output,
                    "exit_code": item.get("exit_code"),
                })
    return turn_error


def _write_error_trajectory(norm: dict[str, Any], error: str) -> None:
    """Best-effort: write a trajectory carrying only an error (never crash)."""
    out = {
        "tool_calls": [],
        "tool_outputs": [],
        "assistant_messages": [],
        "model_messages": [],
        "reasoning": None,
        "final_text": "",
        "final_answer": "",
        "result_meta": {"wiring_kind": norm.get("wiring_kind")},
        "error": error,
    }
    try:
        out = _filter_trajectory(out, norm.get("trajectory_capture"))
        (HARNESS / "trajectory.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2)
        )
    except Exception as e:  # noqa: BLE001
        print(f"[runner] could not write error trajectory: {e!r}",
              file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
