"""Aggregate metrics across attack versions of a run."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
from pathlib import Path
from collections import Counter, defaultdict


def _load_result(attempt_dir: Path) -> dict | None:
    rp = attempt_dir / "result.json"
    if not rp.exists():
        return None
    try:
        return json.loads(rp.read_text())
    except json.JSONDecodeError:
        return None


def _load_reflection(attempt_dir: Path) -> str:
    rp = attempt_dir / "reflection.md"
    return rp.read_text() if rp.exists() else ""


def _load_proposal(attempt_dir: Path) -> str:
    rp = attempt_dir / "proposal.md"
    return rp.read_text() if rp.exists() else ""


def _load_attack(attempt_dir: Path) -> str:
    rp = attempt_dir / "attack.json"
    if not rp.exists():
        return ""
    try:
        return json.loads(rp.read_text()).get("attack_text", "")
    except Exception:
        return ""


_RECOMBINE_KW = re.compile(
    r"\b(combin\w*|merg\w*|stack\w*|hybrid\w*|integrat\w*)\b", re.I,
)
_NEW_MECH_KW = re.compile(
    r"\b(novel|new mechanism|previously unseen|unique pattern|discover\w*\s+(?:new|novel))\b",
    re.I,
)
_HP_KW = re.compile(
    r"\b(parameter\w*|hyperparam\w*|tweak\w*|tun\w+|adjust\w*|threshold)\b", re.I,
)


def _categorize_reflection(text: str) -> str:
    is_new = bool(_NEW_MECH_KW.search(text))
    is_recomb = bool(_RECOMBINE_KW.search(text))
    is_hp = bool(_HP_KW.search(text))
    if is_new and not (is_recomb or is_hp):
        return "new_mechanism"
    if is_recomb:
        return "recombining"
    if is_hp:
        return "hp_tune"
    return "other"


_MODE_RE = re.compile(r"\*\*Mode\*\*:\s*(\w+)", re.I)
_STATUS_RE = re.compile(r"\*\*hypothesis[_ ]status\*\*:\s*(\w+)", re.I)
_SURPRISE_RE = re.compile(r"\*\*surprise[_ ]signal\*\*[^0-9]*([0-9]*\.?[0-9]+)", re.I)
_NOVEL_RE = re.compile(r"\*\*novel[_ ]pattern\*\*:\s*(true|false)", re.I)


def _parse_proposal(text: str) -> dict:
    out = {"mode": None, "hypothesis_block": ""}
    m = _MODE_RE.search(text)
    if m:
        out["mode"] = m.group(1).upper()
    out["hypothesis_block"] = text
    return out


def _parse_reflection(text: str) -> dict:
    out = {"status": None, "surprise_signal": None, "novel_pattern": None}
    m = _STATUS_RE.search(text)
    if m:
        s = m.group(1).lower()
        if s in ("confirmed", "falsified", "inconclusive"):
            out["status"] = s
    m = _SURPRISE_RE.search(text)
    if m:
        try:
            out["surprise_signal"] = float(m.group(1))
        except ValueError:
            pass
    m = _NOVEL_RE.search(text)
    if m:
        out["novel_pattern"] = m.group(1).lower() == "true"
    return out


_VCG_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
_VCG_CONCEPT_RE = re.compile(r"^###\s+VC-(\d+)", re.M)
_VCG_FIELD_RE = re.compile(r"^\s*-\s+\*\*(\w+)\*\*:\s*(.+?)\s*$", re.M)
_VCG_EDGE_ROW_RE = re.compile(
    r"^\|\s*(VC-\d+)\s*\|\s*(\w+)\s*\|\s*(VC-\d+)\s*\|\s*([0-9.]+)\s*\|", re.M,
)


def _iter_vcg_sections(text: str):
    headers = list(_VCG_SECTION_RE.finditer(text))
    for idx, header in enumerate(headers):
        title = header.group(1).strip().lower()
        if title.startswith("counted concepts"):
            section = "counted"
        elif title.startswith("candidate concepts"):
            section = "candidate"
        else:
            continue
        start = header.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        yield section, text[start:end]


def _parse_vcg(vcg_path: Path) -> dict:
    if not vcg_path.exists():
        return {
            "n_total": 0, "n_counted": 0, "n_candidate": 0,
            "edges_total": 0, "edge_types": {}, "edge_density": 0.0,
            "confidence_distribution": {},
        }
    text = vcg_path.read_text()
    concepts = []
    section_counts = Counter()
    for section, section_text in _iter_vcg_sections(text):
        parts = _VCG_CONCEPT_RE.split(section_text)
        for i in range(1, len(parts), 2):
            body = parts[i + 1]
            fields = {}
            for m in _VCG_FIELD_RE.finditer(body):
                fields[m.group(1).lower()] = m.group(2)
            concepts.append(fields)
            section_counts[section] += 1

    n_counted = section_counts["counted"]
    n_candidate = section_counts["candidate"]
    confidences = []
    for c in concepts:
        try:
            confidences.append(float(c.get("confidence", "0")))
        except ValueError:
            pass

    edges = _VCG_EDGE_ROW_RE.findall(text)
    edge_types = Counter(r[1] for r in edges)

    n_total = len(concepts)
    return {
        "n_total": n_total,
        "n_counted": n_counted,
        "n_candidate": n_candidate,
        "edges_total": len(edges),
        "edge_types": dict(edge_types),
        "edge_density": (len(edges) / n_total) if n_total else 0.0,
        "confidence_distribution": {
            "min": round(min(confidences), 3) if confidences else None,
            "max": round(max(confidences), 3) if confidences else None,
            "mean": round(statistics.mean(confidences), 3) if confidences else None,
            "median": round(statistics.median(confidences), 3) if confidences else None,
            "n_above_0.6": sum(1 for c in confidences if c >= 0.6),
            "n_above_0.8": sum(1 for c in confidences if c >= 0.8),
        },
    }


def _integrity_check(run_dir: Path) -> dict:
    versions = sorted(
        (d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("v")),
        key=lambda p: int(p.name[1:]) if p.name[1:].isdigit() else 0,
    )
    over_budget_versions = []
    attack_hash_seen: dict[str, list[str]] = defaultdict(list)
    hash_mismatches = []

    for v in versions:
        r = _load_result(v)
        if r is None:
            continue
        if (r.get("budget") or {}).get("over_budget"):
            over_budget_versions.append(v.name)
        attack_text = _load_attack(v)
        if attack_text:
            h = hashlib.sha256(attack_text.encode()).hexdigest()[:12]
            attack_hash_seen[h].append(v.name)

    duplicate_attacks = {h: vs for h, vs in attack_hash_seen.items() if len(vs) > 1}

    return {
        "over_budget_versions": over_budget_versions,
        "duplicate_attack_hash_count": len(duplicate_attacks),
        "duplicate_attack_groups": list(duplicate_attacks.values()),
        "hash_mismatch_proposals": hash_mismatches,
    }


def build_leaderboard(run_code: str, attacks_root: str = "attacks") -> dict:
    run_dir = Path(attacks_root) / run_code
    if not run_dir.exists():
        raise FileNotFoundError(f"Run dir not found: {run_dir}")

    versions = sorted(
        (d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("v")),
        key=lambda p: int(p.name[1:]) if p.name[1:].isdigit() else 0,
    )

    rows = []
    train_breaks, heldout_breaks = 0, 0
    train_attempts, heldout_attempts = 0, 0
    cum_break_train, cum_break_held, cum_total_tokens = [], [], []
    total_tokens = 0
    per_scenario_break = defaultdict(lambda: {"attempts": 0, "breaks": 0})
    per_criterion_score = defaultdict(list)
    category_count = Counter()

    status_count = Counter()
    mode_count = Counter()
    per_mode_status = defaultdict(lambda: Counter())
    surprise_signals = []
    novel_pattern_count = {"true": 0, "false": 0}

    for v_dir in versions:
        r = _load_result(v_dir)
        if r is None:
            continue
        sset = r.get("scenario_set", "unknown")
        is_break = bool(r.get("is_break", False))
        budget = r.get("budget") or {}
        in_t = int(budget.get("effective_input_tokens", 0) or 0)
        out_t = int(budget.get("output_tokens", 0) or 0)
        total_tokens += in_t + out_t

        if sset == "train":
            train_attempts += 1
            if is_break:
                train_breaks += 1
        elif sset == "held_out":
            heldout_attempts += 1
            if is_break:
                heldout_breaks += 1

        sid = r.get("scenario_id", "?")
        per_scenario_break[sid]["attempts"] += 1
        if is_break:
            per_scenario_break[sid]["breaks"] += 1

        for c in r.get("criteria", []) or []:
            per_criterion_score[c.get("name", "?")].append(float(c.get("score", 0.0)))

        reflection_text = _load_reflection(v_dir)
        category_count[_categorize_reflection(reflection_text)] += 1
        refl = _parse_reflection(reflection_text)
        if refl["status"]:
            status_count[refl["status"]] += 1
        if refl["surprise_signal"] is not None:
            surprise_signals.append(refl["surprise_signal"])
        if refl["novel_pattern"] is not None:
            novel_pattern_count["true" if refl["novel_pattern"] else "false"] += 1

        prop = _parse_proposal(_load_proposal(v_dir))
        if prop["mode"]:
            mode_count[prop["mode"]] += 1
            if refl["status"]:
                per_mode_status[prop["mode"]][refl["status"]] += 1

        rows.append({
            "version": v_dir.name,
            "scenario_id": sid,
            "scenario_set": sset,
            "is_break": is_break,
            "attack_score": r.get("attack_score"),
            "input_tokens": in_t,
            "output_tokens": out_t,
            "over_budget": bool(budget.get("over_budget")),
            "mode": prop["mode"],
            "status": refl["status"],
            "novel_pattern": refl["novel_pattern"],
        })

        cum_break_train.append(train_breaks / max(train_attempts, 1))
        cum_break_held.append(heldout_breaks / max(heldout_attempts, 1) if heldout_attempts else 0.0)
        cum_total_tokens.append(total_tokens)

    vcg_path = run_dir / "success" / "vcg.md"
    if not vcg_path.exists():
        vcg_path = run_dir / "vcg.md"
    vcg_stats = _parse_vcg(vcg_path)
    integrity = _integrity_check(run_dir)

    per_mode_rate = {}
    for mode, counts in per_mode_status.items():
        total = sum(counts.values())
        per_mode_rate[mode] = {
            "total": total,
            "confirmed": counts.get("confirmed", 0),
            "falsified": counts.get("falsified", 0),
            "inconclusive": counts.get("inconclusive", 0),
            "confirmation_rate": counts.get("confirmed", 0) / max(total, 1),
        }

    summary = {
        "run_code": run_code,
        "n_versions": len(rows),

        "train_break_rate": train_breaks / train_attempts if train_attempts else 0.0,
        "heldout_break_rate": heldout_breaks / heldout_attempts if heldout_attempts else 0.0,
        "generalization_gap": (
            (heldout_breaks / heldout_attempts) - (train_breaks / train_attempts)
            if (train_attempts and heldout_attempts) else None
        ),
        "train_attempts": train_attempts,
        "train_breaks": train_breaks,
        "heldout_attempts": heldout_attempts,
        "heldout_breaks": heldout_breaks,
        "total_tokens": total_tokens,
        "per_scenario": dict(per_scenario_break),
        "per_criterion_mean_score": {
            k: round(sum(vs) / len(vs), 3)
            for k, vs in per_criterion_score.items() if vs
        },
        "reflection_categories": dict(category_count),
        "pareto_curve": {
            "tokens": cum_total_tokens,
            "train_break_rate": cum_break_train,
            "heldout_break_rate": cum_break_held,
        },

        "vcg_stats": vcg_stats,
        "hypothesis_status_distribution": dict(status_count),
        "orchestrator_mode_distribution": dict(mode_count),
        "per_mode_metrics": per_mode_rate,
        "surprise_signal_stats": (
            {
                "n": len(surprise_signals),
                "mean": round(statistics.mean(surprise_signals), 3),
                "median": round(statistics.median(surprise_signals), 3),
                "max": round(max(surprise_signals), 3),
            }
            if surprise_signals else None
        ),
        "novel_pattern_counts": novel_pattern_count,
        "integrity_check": integrity,

        "versions": rows,
    }
    (run_dir / "leaderboard.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-code", required=True)
    ap.add_argument("--attacks-root", default="attacks")
    args = ap.parse_args()
    s = build_leaderboard(args.run_code, args.attacks_root)

    print(f"\n=== Run {s['run_code']} — {s['n_versions']} versions ===\n")

    print("[Claudini-aligned]")
    print(f"  Stage-1 break rate:  {s['train_break_rate']:.2%} ({s['train_breaks']}/{s['train_attempts']})")
    print(f"  Held-out break rate: {s['heldout_break_rate']:.2%} ({s['heldout_breaks']}/{s['heldout_attempts']})")
    if s["generalization_gap"] is not None:
        print(f"  Generalization gap:  {s['generalization_gap']:+.2%}")
    print(f"  Total tokens:        {s['total_tokens']:,}")
    print(f"  Reflection categories: {s['reflection_categories']}")

    print("\n[VCG worldview]")
    v = s["vcg_stats"]
    print(f"  Concepts: {v['n_total']} total = {v['n_counted']} counted + {v['n_candidate']} candidate")
    print(f"  Edges: {v['edges_total']} (density {v['edge_density']:.2f}); types: {v['edge_types']}")
    if v["confidence_distribution"]["mean"] is not None:
        print(f"  Confidence: mean={v['confidence_distribution']['mean']}, "
              f"median={v['confidence_distribution']['median']}, "
              f"n≥0.6={v['confidence_distribution']['n_above_0.6']}, "
              f"n≥0.8={v['confidence_distribution']['n_above_0.8']}")

    print("\n[Hypothesis quality]")
    print(f"  Status: {s['hypothesis_status_distribution']}")
    print(f"  Mode distribution: {s['orchestrator_mode_distribution']}")
    if s["per_mode_metrics"]:
        print(f"  Per-mode confirmation rate:")
        for mode, m in s["per_mode_metrics"].items():
            print(f"    {mode}: {m['confirmation_rate']:.2%} ({m['confirmed']}/{m['total']})")
    if s["surprise_signal_stats"]:
        ss = s["surprise_signal_stats"]
        print(f"  Surprise signal: mean={ss['mean']}, median={ss['median']}, max={ss['max']} (n={ss['n']})")
    print(f"  Novel pattern: {s['novel_pattern_counts']}")

    print("\n[Integrity / anti-reward-hacking]")
    ic = s["integrity_check"]
    print(f"  Over-budget versions: {ic['over_budget_versions'] or '(none)'}")
    print(f"  Duplicate attack groups: {len(ic['duplicate_attack_groups'])}")
    if ic["duplicate_attack_groups"]:
        for g in ic["duplicate_attack_groups"][:3]:
            print(f"    {g}")

    print("\n[Per-criterion mean score]")
    for k, v in s["per_criterion_mean_score"].items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
