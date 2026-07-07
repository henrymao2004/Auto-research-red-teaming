"""Build a dtagent attack.json from a clean instance (DTap "Original" baseline)."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _load_instance(gid: str) -> dict:
    for sub in ("clean", "clean_heldout"):
        for p in (HERE / sub).rglob(f"{gid}.json"):
            return json.loads(p.read_text())
    raise FileNotFoundError(f"clean instance not found for gid={gid}")


def _canned_prompt(gid: str) -> str:
    jd = json.loads((HERE / "judge_data.json").read_text())
    turns = (jd.get(gid) or {}).get("canned_attack") or []
    parts: list[str] = []
    for t in turns:
        for step in (t.get("attack_steps") or []):
            if step.get("type") == "prompt" and step.get("content"):
                parts.append(str(step["content"]))
    return "\n\n".join(parts)


def _canned_injection_steps(gid: str) -> list[dict]:
    """DTap mode-B indirect injection steps (backend pre-plant) from canned_attack."""
    jd = json.loads((HERE / "judge_data.json").read_text())
    turns = (jd.get(gid) or {}).get("canned_attack") or []
    steps: list[dict] = []
    for t in turns:
        for step in (t.get("attack_steps") or []):
            if step.get("type") in ("environment", "tool") and step.get("injection_mcp_tool"):
                steps.append({"injection_mcp_tool": step["injection_mcp_tool"],
                              "kwargs": step.get("kwargs") or {}})
    return steps


_SUFFIX_MODE_TO_KIND = {"suffix": "append", "prefix": "prepend"}


def _canned_interceptors(gid: str) -> list[dict]:
    """DTap mode-A indirect (tool-output splice) interceptors from canned_attack."""
    jd = json.loads((HERE / "judge_data.json").read_text())
    turns = (jd.get(gid) or {}).get("canned_attack") or []
    out: list[dict] = []
    for t in turns:
        for step in (t.get("attack_steps") or []):
            if step.get("type") == "tool" and step.get("injected_tool") and step.get("content"):
                kind = _SUFFIX_MODE_TO_KIND.get(step.get("mode", "suffix"), "append")
                tool = str(step["injected_tool"]).split(":", 1)[-1]
                out.append({"tool": tool,
                            "action": {"kind": kind, "content": str(step["content"])}})
    return out


def build(gid: str) -> dict:
    inst = _load_instance(gid)
    tm = inst.get("threat_model") or "direct"
    task = inst.get("task_instruction") or inst.get("malicious_goal") or ""
    if tm == "benign":
        user_prompt = task
    elif tm == "direct":
        user_prompt = _canned_prompt(gid) or inst.get("malicious_goal") or task
    else:
        user_prompt = task
    sysp = (inst.get("system_prompt") or "").strip()
    if sysp:
        user_prompt = f"{sysp}\n\n---\n\n{user_prompt}"
    injection_steps = _canned_injection_steps(gid) if tm == "indirect" else []
    interceptors = _canned_interceptors(gid) if tm == "indirect" else []
    return {
        "instance_id": gid,
        "threat_model": tm,
        "user_prompt": user_prompt,
        "injection_steps": injection_steps,
        "interceptors": interceptors,
        "method_name": f"dtap_original_{gid}",
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gid", required=True, help="instance id, e.g. crm-benign-1")
    ap.add_argument("--out", required=True, help="path to write attack.json")
    a = ap.parse_args()
    attack = build(a.gid)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(attack, ensure_ascii=False, indent=2))
    print(f"wrote {out} (threat_model={attack['threat_model']}, "
          f"user_prompt[:80]={attack['user_prompt'][:80]!r})")


if __name__ == "__main__":
    main()
