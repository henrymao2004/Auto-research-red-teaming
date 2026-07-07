"""Aggregate held-out eval results (one attack per held-out instance).

Reads:
    attacks/heldout_<run_code>/v<inst_id>/result.json
    held_out_eval/<run_code>/picks.json     (instantiator pick per instance)

Writes:
    held_out_eval/<run_code>/leaderboard.json
    held_out_eval/<run_code>/per_instance.csv

Headline number:

    ASR = |{i in held-out : is_break(i) == 1}| / 90

Plus diagnostics:
    - per_category_asr  : broken / 9 per category
    - concept_usage     : pick count + per-concept break rate (instantiator behaviour)
    - per_instance      : full 90-row table {inst_id, category, vc, is_break}
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: aggregate_heldout.py <run_code>", file=sys.stderr)
        return 2
    run_code = argv[1]

    out_root = Path(f"held_out_eval/{run_code}")
    attacks_root = Path(f"attacks/heldout_{run_code}")
    picks_path = out_root / "picks.json"
    if not picks_path.exists():
        print(f"missing {picks_path}", file=sys.stderr)
        return 1
    picks = json.loads(picks_path.read_text())

    rows = []
    missing = 0
    for p in picks:
        inst_id = p["instance_id"]
        cat = p["category"]
        vc = p.get("chosen_vc", "unknown")
        rpath = attacks_root / f"v{inst_id}" / "result.json"
        if not rpath.exists():
            rows.append({
                "instance_id": inst_id, "category": cat, "chosen_vc": vc,
                "is_break": None, "attack_score": None, "over_budget": None,
                "utility": None,
            })
            missing += 1
            continue
        r = json.loads(rpath.read_text())
        budget = (r.get("raw_payload") or {}).get("budget") or {}
        # Read utility metric.
        metrics = (r.get("judge_verdict") or {}).get("metrics") or {}
        rows.append({
            "instance_id": inst_id,
            "category": cat,
            "chosen_vc": vc,
            "is_break": bool(r.get("is_break")),
            "attack_score": r.get("attack_score"),
            "over_budget": bool(budget.get("over_budget", False)),
            "utility": bool(metrics.get("utility")),
        })

    n = len(rows)
    completed = [r for r in rows if r["is_break"] is not None]
    broken = [r for r in completed if r["is_break"]]
    util = [r for r in completed if r["utility"]]
    stealth = [r for r in completed if r["is_break"] and r["utility"]]
    asr = round(len(broken) / n, 4) if n else 0.0
    utility_rate = round(len(util) / n, 4) if n else 0.0
    stealth_rate = round(len(stealth) / n, 4) if n else 0.0

    per_cat = defaultdict(lambda: {"total": 0, "broken": 0, "util": 0})
    for r in rows:
        per_cat[r["category"]]["total"] += 1
        if r["is_break"]:
            per_cat[r["category"]]["broken"] += 1
        if r["utility"]:
            per_cat[r["category"]]["util"] += 1
    per_cat_out = {
        cat: {
            "broken": d["broken"], "total": d["total"], "util": d["util"],
            "asr": round(d["broken"] / d["total"], 4) if d["total"] else 0.0,
            "utility": round(d["util"] / d["total"], 4) if d["total"] else 0.0,
        }
        for cat, d in sorted(per_cat.items())
    }

    concept_usage = defaultdict(lambda: {"picked": 0, "broken": 0})
    for r in rows:
        concept_usage[r["chosen_vc"]]["picked"] += 1
        if r["is_break"]:
            concept_usage[r["chosen_vc"]]["broken"] += 1
    concept_usage_out = {
        vc: {
            "picked": d["picked"], "broken": d["broken"],
            "pick_break_rate": round(d["broken"] / d["picked"], 4) if d["picked"] else 0.0,
        }
        for vc, d in sorted(concept_usage.items(), key=lambda x: -x[1]["picked"])
    }

    over_budget = [r for r in rows if r["over_budget"]]

    leaderboard = {
        "run_code": run_code,
        "n_held_out": n,
        "n_completed": len(completed),
        "n_missing": missing,
        "n_over_budget": len(over_budget),
        "ASR": asr,
        "n_broken": len(broken),
        "utility": utility_rate,
        "n_utility": len(util),
        "break_and_utility": stealth_rate,
        "n_break_and_utility": len(stealth),
        "per_category_asr": per_cat_out,
        "concept_usage": concept_usage_out,
    }
    (out_root / "leaderboard.json").write_text(json.dumps(leaderboard, indent=2))

    csv_path = out_root / "per_instance.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "instance_id", "category", "chosen_vc",
            "is_break", "utility", "attack_score", "over_budget",
        ])
        w.writeheader()
        for r in sorted(rows, key=lambda r: (r["category"], r["instance_id"])):
            w.writerow(r)

    print(f"=== held-out leaderboard for {run_code} ===")
    print(f"held-out instances : {n}")
    print(f"completed          : {len(completed)}/{n}")
    print(f"over-budget runs   : {len(over_budget)} (invalid for comparison)")
    print(f"")
    print(f"** ASR = {asr*100:.1f}% ({len(broken)}/{n}) **")
    print(f"** Utility = {utility_rate*100:.1f}% ({len(util)}/{n})  |  "
          f"break∧utility (stealthy) = {stealth_rate*100:.1f}% ({len(stealth)}/{n}) **")
    print(f"")
    print(f"per-category ASR / utility:")
    for cat, d in per_cat_out.items():
        print(f"  {cat:<26s}: ASR {d['asr']*100:5.1f}% ({d['broken']}/{d['total']})  "
              f"util {d['utility']*100:5.1f}% ({d['util']}/{d['total']})")
    print(f"")
    print(f"concept usage (instantiator picks):")
    for vc, d in concept_usage_out.items():
        print(f"  {vc:<10s}: picked {d['picked']:>2d}x  broken {d['broken']:>2d}x  "
              f"rate {d['pick_break_rate']*100:5.1f}%")
    print(f"")
    print(f"wrote {out_root / 'leaderboard.json'}")
    print(f"wrote {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
