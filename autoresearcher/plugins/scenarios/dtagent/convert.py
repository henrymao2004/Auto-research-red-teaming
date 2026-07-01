"""DecodingTrust-Agent (DTap) -> contract-driven `dtagent` scenario converter."""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import sys
from pathlib import Path
from typing import Any

import yaml


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(s).lower()).strip("-")

PLUGIN_DIR = Path(__file__).resolve().parent
DEFAULT_DTAP = Path("/Users/henry_mao/vlm/DecodingTrust-Agent")
DOMAINS = [
    "browser", "code", "crm", "customer-service", "finance", "legal", "macos",
    "medical", "os-filesystem", "research", "telecom", "travel", "windows", "workflow",
]
TYPES = ["benign", "direct", "indirect"]
TARGET_TOTAL = 700


def _leaf_task_dirs(dtap: Path, domain: str, ttype: str) -> list[Path]:
    if ttype == "benign":
        base = dtap / "dataset" / domain / "benign"
        dirs = [p for p in base.glob("*") if p.is_dir()] if base.is_dir() else []
    else:
        base = dtap / "dataset" / domain / "malicious" / ttype
        dirs = [p for p in base.glob("*/*") if p.is_dir()] if base.is_dir() else []
    def _key(p: Path):
        nm = p.name
        return (p.parent.name, (0, int(nm)) if nm.isdigit() else (1, nm))
    return sorted(dirs, key=_key)


def _allocate(avail: dict[tuple[str, str], int]) -> dict[tuple[str, str], int]:
    total = sum(avail.values())
    raw = {k: TARGET_TOTAL * v / total for k, v in avail.items()}
    alloc = {k: min(avail[k], max(3 if avail[k] >= 3 else avail[k], round(r)))
             for k, r in raw.items()}
    order = sorted(avail, key=lambda k: -raw[k])
    guard = 0
    while sum(alloc.values()) != TARGET_TOTAL and guard < 100000:
        guard += 1
        diff = TARGET_TOTAL - sum(alloc.values())
        for k in order:
            if diff > 0 and alloc[k] < avail[k]:
                alloc[k] += 1
                break
            if diff < 0 and alloc[k] > (3 if avail[k] >= 3 else 1):
                alloc[k] -= 1
                break
        else:
            break
    return alloc


def _instance_id(domain: str, ttype: str, task_dir: Path) -> str:
    if ttype == "benign":
        return f"{domain}-benign-{task_dir.name}"
    return f"{domain}-{ttype[:3]}-{task_dir.parent.name}-{task_dir.name}"


def _extract(task_dir: Path, domain: str, ttype: str, gid: str) -> tuple[dict, dict] | None:
    cfg_path = task_dir / "config.yaml"
    if not cfg_path.exists():
        return None
    try:
        cfg = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception as e:  # noqa: BLE001
        print(f"[convert] WARN parse {cfg_path}: {e!r}", file=sys.stderr)
        return None

    task = cfg.get("Task") or {}
    agent = cfg.get("Agent") or {}
    attack = cfg.get("Attack") or {}
    mcp_servers = agent.get("mcp_servers") or []
    tool_hint = [s.get("name") for s in mcp_servers if isinstance(s, dict)]

    researcher = {
        "domain": domain,
        "threat_model": ttype,
        "task_category": task.get("task_category"),
        "task_instruction": task.get("task_instruction"),
        "system_prompt": agent.get("system_prompt"),
        "available_tools": tool_hint,
        "risk_category": attack.get("risk_category"),
        "malicious_goal": attack.get("malicious_goal") if ttype != "benign" else None,
        "additional_information": attack.get("additional_information") if ttype != "benign" else None,
    }
    evaluator = {
        "task_id": task.get("task_id"),
        "threat_model": ttype,
        "judge_ref": f"judges/{domain}/{gid}/judge.py",
        "seed_ref": f"seeds/{domain}/{gid}/seed.sql",
        "policies": attack.get("policies"),
        "malicious_goal": attack.get("malicious_goal"),
        "mcp_servers": mcp_servers,
        "canned_attack": attack.get("attack_turns"),
        "base_task": task.get("base_task"),
    }
    return researcher, evaluator


def _vendor(task_dir: Path, domain: str, gid: str) -> None:
    """Copy the task's per-task judge.py + seed.sql + setup.sh into the plugin."""
    jdst = PLUGIN_DIR / "judges" / domain / gid
    jdst.mkdir(parents=True, exist_ok=True)
    jsrc = task_dir / "judge.py"
    if jsrc.exists():
        shutil.copy2(jsrc, jdst / "judge.py")
    sdst = PLUGIN_DIR / "seeds" / domain / gid
    sdst.mkdir(parents=True, exist_ok=True)
    ssrc = task_dir / "metadata" / "seed.sql"
    if ssrc.exists():
        shutil.copy2(ssrc, sdst / "seed.sql")
    setup_dst = PLUGIN_DIR / "setups" / domain / gid
    setup_src = task_dir / "setup.sh"
    if setup_src.exists():
        setup_dst.mkdir(parents=True, exist_ok=True)
        shutil.copy2(setup_src, setup_dst / "setup.sh")
        meta = task_dir / "metadata"
        if meta.is_dir():
            shutil.copytree(meta, setup_dst / "metadata", dirs_exist_ok=True)


def convert(dtap: Path, domains: list[str], split_ratio: float, seed: int) -> dict:
    avail: dict[tuple[str, str], int] = {}
    leaves: dict[tuple[str, str], list[Path]] = {}
    for d in domains:
        for t in TYPES:
            ds = _leaf_task_dirs(dtap, d, t)
            leaves[(d, t)] = ds
            avail[(d, t)] = len(ds)
    alloc = _allocate(avail)

    clean = PLUGIN_DIR / "clean"
    clean_ho = PLUGIN_DIR / "clean_heldout"
    judge_data: dict[str, dict] = {}
    n_ok = n_skip = 0

    buckets: dict[str, list] = {}
    for (d, t), n in alloc.items():
        for task_dir in leaves[(d, t)][:n]:
            gid = _instance_id(d, t, task_dir)
            ex = _extract(task_dir, d, t, gid)
            if ex is None:
                n_skip += 1
                continue
            researcher, evaluator = ex
            cell = f"{t}-{_slug(researcher.get('risk_category') or 'unknown')}"
            buckets.setdefault(cell, []).append((gid, researcher, evaluator, task_dir, d))

    cats: dict[str, dict] = {}
    for cell in sorted(buckets):
        items = sorted(buckets[cell], key=lambda x: x[0])
        n = len(items)
        n_eval = max(1, round((1 - split_ratio) * n)) if n >= 2 else 0
        cats[cell] = {"train": [], "held_out": []}
        for idx, (gid, researcher, evaluator, task_dir, d) in enumerate(items):
            _vendor(task_dir, d, gid)
            is_eval = idx >= (n - n_eval)
            out_dir = (clean_ho if is_eval else clean) / cell
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{gid}.json").write_text(
                json.dumps(researcher, ensure_ascii=False, indent=2))
            judge_data[gid] = evaluator
            (cats[cell]["held_out"] if is_eval else cats[cell]["train"]).append(gid)
            n_ok += 1

    (PLUGIN_DIR / "judge_data.json").write_text(
        json.dumps(judge_data, ensure_ascii=False, indent=2))
    split = {"seed": seed,
             "split_method": f"stratified by threat_model x risk_category, {split_ratio} per cell"}
    (PLUGIN_DIR / "train.json").write_text(json.dumps(
        {**split, "categories": {c: {"train": cats[c]["train"]} for c in cats}},
        ensure_ascii=False, indent=2))
    (PLUGIN_DIR / "heldout.json").write_text(json.dumps(
        {**split, "categories": {c: {"held_out": cats[c]["held_out"]} for c in cats}},
        ensure_ascii=False, indent=2))

    n_train = sum(len(cats[c]["train"]) for c in cats)
    n_eval = sum(len(cats[c]["held_out"]) for c in cats)
    print(f"[convert] wrote {n_ok} instances ({n_train} train / {n_eval} held-out), "
          f"{n_skip} skipped, across {len(domains)} domains")
    for d in domains:
        print(f"  {d:16} train={len(cats[d]['train']):>3} held_out={len(cats[d]['held_out']):>3}")
    return {"n_ok": n_ok, "n_train": n_train, "n_eval": n_eval, "alloc": alloc}


def main(argv: list[str]) -> int:
    global TARGET_TOTAL
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dtap-repo", default=str(DEFAULT_DTAP))
    p.add_argument("--domains", default=",".join(DOMAINS),
                   help="comma list (default all 14)")
    p.add_argument("--split", type=float, default=0.8, help="Stage-1 fraction")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--total", type=int, default=TARGET_TOTAL,
                   help="sample cap across the selected domains (proportional)")
    a = p.parse_args(argv[1:])
    TARGET_TOTAL = a.total
    dtap = Path(a.dtap_repo)
    if not (dtap / "dataset").is_dir():
        print(f"[convert] DTap repo not found at {dtap}", file=sys.stderr)
        return 1
    doms = [d.strip() for d in a.domains.split(",") if d.strip()]
    convert(dtap, doms, a.split, a.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
