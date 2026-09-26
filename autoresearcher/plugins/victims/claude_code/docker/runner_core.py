"""Model-agnostic, in-container contract dispatch shared by victim runners.

Contract-spec resolution and interceptor splicing, stdlib only, so runners
for other agents can use it without importing the claude agent SDK.
"""
from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path
from typing import Any


WORK = Path("/work")
# Harness only stores trajectory output.
HARNESS = Path("/harness")

GENERIC_KICKOFF = "Please proceed with your assigned task."

ALL_TRAJECTORY_KEYS = {
    "model_messages",
    "assistant_messages",
    "tool_calls",
    "tool_outputs",
    "reasoning",
    "final_answer",
    "final_text",
    "result_meta",
    "error",
    "post_environment",
}


def _resolve_path(
    dotted: str | None,
    attack: dict[str, Any],
    instance: dict[str, Any],
) -> Any:
    """Resolve ``attack.foo.bar`` or ``instance.foo.bar`` against the dicts."""
    if not dotted:
        return None
    root, *rest = dotted.split(".")
    if root == "attack":
        obj: Any = attack
    elif root == "instance":
        obj = instance
    else:
        raise ValueError(
            f"unknown root {root!r} in path {dotted!r} "
            f"(expected attack.* or instance.*)"
        )
    for key in rest:
        if obj is None:
            return None
        if isinstance(obj, dict):
            obj = obj.get(key)
        else:
            obj = getattr(obj, key, None)
    return obj


def _resolve_wiring(
    runtime_spec: dict[str, Any],
    attack: dict[str, Any],
    instance: dict[str, Any],
) -> dict[str, Any]:
    w = runtime_spec.get("attack_wiring")
    if not w:
        return {
            "kind": "environment_only",
            "payload": None,
            "max_turns_per_user_msg": 25,
        }
    payload = (
        _resolve_path(w.get("source"), attack, instance)
        if w.get("source") else None
    )
    return {
        "kind": w.get("kind", "environment_only"),
        "payload": payload,
        "max_turns_per_user_msg": int(w.get("max_turns_per_user_msg") or 25),
    }


def _resolve_env_hydration(
    runtime_spec: dict[str, Any],
    attack: dict[str, Any],
    instance: dict[str, Any],
) -> dict[str, Any]:
    eh = runtime_spec.get("environment_hydration") or {"kind": "none"}
    kind = eh.get("kind", "none")
    if kind == "none":
        return {"kind": "none"}
    if kind == "from_instance_field":
        return {
            "kind": "from_instance_field",
            "state": _resolve_path(eh.get("source"), attack, instance),
        }
    if kind == "inline_yaml":
        return {"kind": "inline_yaml", "state": eh.get("inline")}
    if kind == "callback":
        state = _invoke_env_callback(eh.get("callback_module"), attack, instance)
        return {
            "kind": "callback",
            "state": state,
            "callback_module": eh.get("callback_module"),
        }
    raise ValueError(f"unknown environment_hydration.kind: {kind!r}")


def _invoke_env_callback(
    callback_module: str | None,
    attack: dict[str, Any],
    instance: dict[str, Any],
) -> dict[str, Any]:
    """Import and call ``module:func(instance, attack)`` from the ``/plugins`` mount."""
    if not callback_module:
        raise ValueError(
            "environment_hydration.kind == 'callback' requires "
            "callback_module='<module>:<func>'"
        )
    mod_name, _, func_name = callback_module.partition(":")
    if not func_name:
        raise ValueError(
            f"callback_module must be 'module:func', got {callback_module!r}"
        )
    if "/" not in sys.path:
        sys.path.insert(0, "/")
    mod = importlib.import_module(mod_name)
    func = getattr(mod, func_name, None)
    if func is None:
        raise AttributeError(
            f"callback_module {mod_name!r} has no attribute {func_name!r}"
        )
    result = func(instance, attack)
    if result is None:
        return {}
    if not isinstance(result, dict):
        raise TypeError(
            f"callback {callback_module!r} returned {type(result).__name__}; "
            f"expected dict"
        )
    return result


def _resolve_interceptors(
    runtime_spec: dict[str, Any],
    attack: dict[str, Any],
    instance: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve dynamic interceptors (from attack.*) or static list (from contract)."""
    dynamic_from = runtime_spec.get("tool_response_interceptors_from")
    if dynamic_from:
        dynamic = _resolve_path(dynamic_from, attack, instance)
        out: list[dict[str, Any]] = []
        for entry in dynamic or []:
            match = entry.get("match") or {}
            action = entry.get("action") or {}
            out.append({
                "tool": entry.get("tool"),
                "match": {
                    "object_id": match.get("object_id"),
                    "field": match.get("field"),
                    "static_match": match.get("static_match"),
                },
                "action": {
                    "kind": action.get("kind"),
                    "anchor": action.get("anchor", "{INJECTION}"),
                    "content": action.get("content"),
                },
            })
        return out

    static = runtime_spec.get("tool_response_interceptors") or []
    out = []
    for i in static:
        m = i.get("match") or {}
        a = i.get("action") or {}
        object_id = m.get("object_id") or _resolve_path(
            m.get("object_id_source"), attack, instance,
        )
        field = m.get("field") or _resolve_path(
            m.get("field_source"), attack, instance,
        )
        content = (
            _resolve_path(a.get("source"), attack, instance)
            if a.get("source") else a.get("content")
        )
        out.append({
            "tool": i.get("tool"),
            "match": {
                "object_id": object_id,
                "field": field,
                "static_match": m.get("static_match"),
            },
            "action": {
                "kind": a.get("kind"),
                "anchor": a.get("anchor", "{INJECTION}"),
                "content": content,
            },
        })
    return out


def _hydrate_environment(env_hydration: dict[str, Any] | None) -> dict[str, Any] | None:
    """Materialise the hydrated env as /work/initial_env.json.

    Returns the parsed state dict (or None) so the caller can hand it
    to ``build_mcp_server`` for scenarios with bespoke tool worlds.
    """
    if not env_hydration:
        return None
    kind = env_hydration.get("kind", "none")
    if kind == "none":
        return None
    state = env_hydration.get("state")
    if state is None:
        state = env_hydration.get("inline")
    if state is None:
        print(f"[runner] env_hydration kind={kind!r} but no state payload; "
              f"skipping write", file=sys.stderr)
        return None
    target = WORK / "initial_env.json"
    target.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    print(f"[runner] wrote hydrated env to {target} "
          f"({len(target.read_text())} bytes, kind={kind!r})", file=sys.stderr)
    return state if isinstance(state, dict) else {"_root": state}


def _navigate(container: Any, object_id: Any) -> tuple[Any, Any] | None:
    """Return ``(parent, key)`` for the matched object inside container.

    ``object_id`` semantics:
      - int → list index; container must be list-like.
      - str → dict key OR list-element whose ``"id"`` field equals it.
      - None → match the container itself (parent=None, key=None).
    """
    if object_id is None:
        return (None, None)
    if isinstance(container, list):
        if isinstance(object_id, int):
            if 0 <= object_id < len(container):
                return (container, object_id)
            return None
        for idx, item in enumerate(container):
            if isinstance(item, dict):
                iid = item.get("id", item.get("id_"))
                if iid is not None and str(iid) == str(object_id):
                    return (container, idx)
        return None
    if isinstance(container, dict):
        if object_id in container:
            return (container, object_id)
        for v in container.values():
            if isinstance(v, list):
                nav = _navigate(v, object_id)
                if nav is not None:
                    return nav
        return None
    return None


# Skip structural metadata keys.
_NON_CONTENT_KEYS = frozenset({
    "type", "id", "role", "name", "mimeType", "mime_type", "annotations",
    "_meta", "tool_use_id", "tool_call_id", "status", "index", "uri",
})


def _iter_string_leaves(value: Any):
    """Yield ``(container, key_or_index, string)`` for every *content* string
    leaf in a nested list/dict, so callers can mutate the leaf in place.
    Handles the common MCP tool-output shapes: a list of strings, a list of
    ``{"type": "text", "text": ...}`` content blocks, and nested dicts.
    Metadata keys (``_NON_CONTENT_KEYS``) are skipped so injection lands on
    real text, not on structural fields."""
    if isinstance(value, list):
        for i, v in enumerate(value):
            if isinstance(v, str):
                yield value, i, v
            elif isinstance(v, (list, dict)):
                yield from _iter_string_leaves(v)
    elif isinstance(value, dict):
        for k, v in value.items():
            if k in _NON_CONTENT_KEYS:
                continue
            if isinstance(v, str):
                yield value, k, v
            elif isinstance(v, (list, dict)):
                yield from _iter_string_leaves(v)


def _splice_string_leaves(value: Any, kind: str, anchor: Any, content: Any,
                          static_match: Any) -> Any | None:
    """Apply replace_anchor / append / prepend to the string leaves of a list/dict tool response.

    MCP tools often return structured output rather than a bare string; this
    splices into the text leaves instead of replacing the whole structure.
    Mutates in place and returns the value, or ``None`` if nothing applied.
    """
    leaves = list(_iter_string_leaves(value))
    eligible = [(c, k, s) for (c, k, s) in leaves
                if static_match is None or static_match in s]
    if not eligible:
        if kind == "append" and isinstance(value, list):
            value.append({"type": "text", "text": str(content or "")})
            print("[runner][interceptor] appended new text block to list "
                  "tool response", file=sys.stderr)
            return value
        print(f"[runner][interceptor] no string leaf matching static_match="
              f"{static_match!r} in structured tool response; passing through",
              file=sys.stderr)
        return None
    if kind == "replace_anchor":
        if anchor is None or content is None:
            print("[runner][interceptor] replace_anchor needs anchor+content",
                  file=sys.stderr)
            return None
        applied = False
        for c, k, s in eligible:
            if anchor in s:
                c[k] = s.replace(anchor, str(content))
                applied = True
        if not applied:
            print(f"[runner][interceptor] anchor={anchor!r} not in any string "
                  f"leaf; passing through", file=sys.stderr)
            return None
        return value
    if kind == "append":
        c, k, s = eligible[-1]
        c[k] = s + str(content or "")
        return value
    if kind == "prepend":
        c, k, s = eligible[0]
        c[k] = str(content or "") + s
        return value
    return None


def _apply_interceptor(spec: dict[str, Any], tool_response: Any) -> Any | None:
    """Apply one interceptor spec, falling back to JSON text leaves.

    Some tools (e.g. agentdyn's ``_to_text``) serialise structured output into a
    single JSON text block, leaving nothing for ``object_id`` / ``field`` to
    navigate. If the direct apply fails, each JSON text leaf is parsed, retried,
    and re-serialised.
    """
    out = _apply_interceptor_core(spec, tool_response)
    if out is not None:
        return out
    match = spec.get("match") or {}
    if match.get("object_id") is None and match.get("field") is None:
        return None
    resp = copy.deepcopy(tool_response)
    for holder, key, s in _iter_string_leaves(resp):
        stripped = s.strip()
        if not stripped or stripped[0] not in "[{":
            continue
        try:
            parsed = json.loads(stripped)
        except (ValueError, TypeError):
            continue
        applied = _apply_interceptor_core(spec, parsed)
        if applied is not None:
            holder[key] = json.dumps(applied, indent=2, ensure_ascii=False)
            print(f"[runner][interceptor] applied via JSON text-leaf expansion "
                  f"(object_id={match.get('object_id')!r}, "
                  f"field={match.get('field')!r})", file=sys.stderr)
            return resp
    print(f"[runner][interceptor] object_id={match.get('object_id')!r} not "
          f"navigable in any JSON text leaf; passing through", file=sys.stderr)
    return None


def _apply_interceptor_core(spec: dict[str, Any], tool_response: Any) -> Any | None:
    """Apply one interceptor spec to ``tool_response``.

    Returns the modified response, or ``None`` if the spec doesn't
    apply (e.g. object_id not found, field missing). The caller falls
    back to passing the original response through unchanged.

    Spec shape::

        {
          "tool":   "<tool name>",            # already filtered by caller
          "match":  {
              "object_id":    <int|str|None>,
              "field":        <str|None>,
              "static_match": <str|None>,
          },
          "action": {
              "kind":    "replace_anchor|append|prepend|replace_field|overwrite_object",
              "anchor":  <str|None>,           # required for replace_anchor
              "content": <str|dict|None>,
          }
        }

    Mutates a deepcopy of ``tool_response`` to avoid leaking state
    between hook invocations.
    """
    match = spec.get("match") or {}
    action = spec.get("action") or {}
    kind = action.get("kind")
    content = action.get("content")

    object_id = match.get("object_id")
    field = match.get("field")
    static_match = match.get("static_match")

    resp = copy.deepcopy(tool_response)

    nav = _navigate(resp, object_id)
    if nav is None:
        print(f"[runner][interceptor] object_id={object_id!r} not found; "
              f"passing through", file=sys.stderr)
        return None
    parent, key = nav
    if parent is None:
        obj = resp
    else:
        obj = parent[key]

    if kind == "overwrite_object":
        if content is None:
            return None
        if parent is None:
            return copy.deepcopy(content)
        parent[key] = copy.deepcopy(content)
        return resp

    if field is None:
        target_holder = parent
        target_key = key
        target_value = obj
    else:
        if not isinstance(obj, dict):
            print(f"[runner][interceptor] field={field!r} requested but "
                  f"matched object is {type(obj).__name__}; passing through",
                  file=sys.stderr)
            return None
        if field not in obj and kind not in ("append", "prepend", "replace_field"):
            print(f"[runner][interceptor] field={field!r} missing on matched "
                  f"object; passing through", file=sys.stderr)
            return None
        target_holder = obj
        target_key = field
        target_value = obj.get(field, "")

    if static_match is not None and isinstance(target_value, str):
        if static_match not in target_value:
            print(f"[runner][interceptor] static_match={static_match!r} "
                  f"not found in field; passing through", file=sys.stderr)
            return None

    if kind in ("replace_anchor", "append", "prepend") and not isinstance(target_value, str):
        spliced = _splice_string_leaves(
            target_value, kind, action.get("anchor"), content, static_match)
        if spliced is None:
            return None
        if target_holder is None:
            return spliced
        target_holder[target_key] = spliced
        return resp

    if kind == "replace_anchor":
        anchor = action.get("anchor")
        if anchor is None or content is None:
            print("[runner][interceptor] replace_anchor needs anchor+content",
                  file=sys.stderr)
            return None
        if not isinstance(target_value, str):
            print(f"[runner][interceptor] replace_anchor needs string field; "
                  f"got {type(target_value).__name__}", file=sys.stderr)
            return None
        if anchor not in target_value:
            print(f"[runner][interceptor] anchor={anchor!r} not in field; "
                  f"passing through", file=sys.stderr)
            return None
        new_value = target_value.replace(anchor, str(content))
    elif kind == "append":
        new_value = (target_value if isinstance(target_value, str) else "") + str(content or "")
    elif kind == "prepend":
        new_value = str(content or "") + (target_value if isinstance(target_value, str) else "")
    elif kind == "replace_field":
        new_value = content
    else:
        print(f"[runner][interceptor] unknown action.kind={kind!r}; "
              f"passing through", file=sys.stderr)
        return None

    if target_holder is None:
        return new_value
    target_holder[target_key] = new_value
    return resp


def _tool_name_matches(spec_tool: Any, actual_tool: str) -> bool:
    """Match an interceptor's ``tool`` against the runtime tool name.

    Runtime MCP names are ``mcp__<server>__<bare>`` while attack payloads
    usually name the bare tool, so both forms match, plus the ``"*"`` wildcard.
    """
    if not spec_tool:
        return False
    if spec_tool == "*" or spec_tool == actual_tool:
        return True
    if isinstance(actual_tool, str) and actual_tool.startswith("mcp__"):
        bare = actual_tool.split("__", 2)[-1]
        if spec_tool == bare:
            return True
    return False


def _normalise_input(spec: dict[str, Any]) -> dict[str, Any]:
    """Return a normalised dict with keys::

        model, wiring_kind, payload, max_turns_per_user_msg,
        env_hydration, interceptors, trajectory_capture,
        system_prompt_prefix, mcp_tools_module, instance

    Accepts either a top-level ``decomposed_query`` list (everything else
    defaults) or the contract-driven shape, where ``runtime_spec`` is the
    serialised ``ScenarioContract.runtime`` and dotted paths are resolved
    against ``attack`` / ``instance``.
    """
    model = spec["model"]

    if "decomposed_query" in spec:
        return {
            "model": model,
            "wiring_kind": "sequential_user_messages",
            "payload": list(spec["decomposed_query"]),
            "max_turns_per_user_msg": int(spec.get("max_turns_per_user_msg", 25)),
            "env_hydration": None,
            "interceptors": [],
            "trajectory_capture": None,
            "system_prompt_prefix": None,
            "mcp_tools_module": None,
            "allowed_tools": None,
            "disallowed_tools": None,
            "instance": spec.get("instance"),
        }

    runtime_spec = spec.get("runtime_spec") or {}
    attack = spec.get("attack") or {}
    instance = spec.get("instance") or {}

    wiring = _resolve_wiring(runtime_spec, attack, instance)
    env_hyd = _resolve_env_hydration(runtime_spec, attack, instance)
    interceptors = _resolve_interceptors(runtime_spec, attack, instance)

    capture_include = (
        (runtime_spec.get("trajectory_capture") or {}).get("include") or []
    )
    trajectory_capture = list(capture_include) if capture_include else None

    kind = wiring["kind"]
    payload = wiring["payload"]
    max_turns = wiring["max_turns_per_user_msg"]
    system_prefix = None
    if kind == "system_prompt_prefix":
        system_prefix = payload if isinstance(payload, str) else None
        payload = None

    return {
        "model": model,
        "wiring_kind": kind,
        "payload": payload,
        "max_turns_per_user_msg": max_turns,
        "env_hydration": env_hyd,
        "interceptors": interceptors,
        "trajectory_capture": trajectory_capture,
        "system_prompt_prefix": system_prefix,
        "mcp_tools_module": runtime_spec.get("mcp_tools_module") or spec.get("mcp_tools_module"),
        "allowed_tools": spec.get("allowed_tools"),
        "disallowed_tools": runtime_spec.get("disallowed_tools") or spec.get("disallowed_tools"),
        "instance": instance,
    }


def _user_turns_for_wiring(norm: dict[str, Any]) -> list[str]:
    """Translate wiring kind + payload into the user messages to send (never empty)."""
    kind = norm["wiring_kind"]
    payload = norm["payload"]
    if kind == "sequential_user_messages":
        if not isinstance(payload, list) or not payload:
            return [GENERIC_KICKOFF]
        return [str(m) for m in payload]
    if kind == "single_user_message":
        if not isinstance(payload, str) or not payload:
            return [GENERIC_KICKOFF]
        return [payload]
    if kind == "system_prompt_prefix":
        return [GENERIC_KICKOFF]
    if kind == "environment_only":
        return [GENERIC_KICKOFF]
    if kind == "tool_call_injection":
        print("[runner] tool_call_injection wiring requested but treated "
              "as environment_only in claude_code; see docstring.",
              file=sys.stderr)
        return [GENERIC_KICKOFF]
    print(f"[runner] WARN unknown attack_wiring.kind={kind!r}; "
          f"using single_user_message", file=sys.stderr)
    if isinstance(payload, str) and payload:
        return [payload]
    return [GENERIC_KICKOFF]


def safe_model_dump(model: Any) -> Any:
    """JSON-safe dump of a pydantic env that never raises on non-serializable leaves.

    Some agentdojo tools leave a callable in the environment state (e.g. the
    shopping password-reset flow), which makes ``model_dump(mode="json")``
    raise and would leave the judge without a post-environment. On failure,
    dump in python mode and map callables to ``None`` and other non-JSON
    leaves to ``str``; those leaves are transient and not inspected by the
    security checks.
    """
    def _json_default(o: Any) -> Any:
        return None if callable(o) else str(o)
    try:
        return model.model_dump(mode="json")
    except Exception:  # noqa: BLE001
        try:
            py = model.model_dump(mode="python")
            return json.loads(json.dumps(py, default=_json_default))
        except Exception:  # noqa: BLE001
            return json.loads(json.dumps(model, default=_json_default))


def _filter_trajectory(out: dict[str, Any], capture: list[str] | None) -> dict[str, Any]:
    """Keep only the keys listed in ``trajectory_capture`` (all keys when empty).

    ``model_messages`` and ``final_answer`` alias ``assistant_messages`` and
    ``final_text``.
    """
    if not capture:
        return out
    requested = set(capture)
    if "model_messages" in requested:
        requested.add("assistant_messages")
    if "final_answer" in requested:
        requested.add("final_text")
    if "tool_outputs" in requested:
        # Tool outputs are stored inside assistant_messages.
        requested.add("assistant_messages")
    requested.add("error")
    return {k: v for k, v in out.items() if k in requested}
