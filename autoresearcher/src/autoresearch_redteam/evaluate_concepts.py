"""Cross-target evaluation of concepts from a source run against target combos."""

from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def _setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


_CONCEPT_HEADER_RE = re.compile(r"^###\s+VC-(\d+)\s*$", re.M)
_FIELD_RE = re.compile(r"^\s*-\s+\*\*(\w+)\*\*:\s*(.+)$", re.M)


def parse_concepts_from_vcg(vcg_path: Path) -> list[dict]:
    if not vcg_path.exists():
        return []
    text = vcg_path.read_text()
    concepts = []
    parts = _CONCEPT_HEADER_RE.split(text)
    for i in range(1, len(parts), 2):
        vc_id = f"VC-{int(parts[i]):04d}"
        body = parts[i + 1]
        fields = {}
        for m in _FIELD_RE.finditer(body):
            fields[m.group(1).lower()] = m.group(2).strip()
        if "mechanism" in fields and "attack_template" in fields:
            concepts.append({
                "id": vc_id,
                "mechanism": fields.get("mechanism", ""),
                "enabling_condition": fields.get("enabling_condition", ""),
                "attack_template": fields.get("attack_template", ""),
                "failure_outcome": fields.get("failure_outcome", ""),
                "transfer_prediction": fields.get("transfer_prediction", ""),
                "confidence": float(fields.get("confidence", 0.0) or 0.0),
                "is_counted": fields.get("is_counted", "false").lower() == "true",
            })
    return concepts


def _run_one_eval(
    concept: dict,
    target: dict,
    eval_dir: Path,
    timeout: int = 300,
) -> dict:
    safe_id = f"{concept['id']}_{target['framework']}_{target['llm'].replace('/', '-')}_{target['scenario_id']}"
    attempt_dir = eval_dir / safe_id
    attempt_dir.mkdir(parents=True, exist_ok=True)
    attack = {
        "scenario_id": target["scenario_id"],
        "attack_text": concept["attack_template"],
        "method_name": f"concept_{concept['id']}",
        "_concept_id": concept["id"],
        "_concept_mechanism": concept["mechanism"][:200],
    }
    (attempt_dir / "attack.json").write_text(json.dumps(attack, indent=2))

    cmd = [
        sys.executable, "-m", "autoresearch_redteam.run_attack",
        "--run-code", attempt_dir.name,
        "--version", "1",
        "--framework", target["framework"],
        "--model", target["llm"],
        "--timeout", str(timeout),
        "--attacks-root", str(attempt_dir.parent),
    ]
    logger.info("eval concept=%s target=%s/%s/%s",
                concept["id"], target["framework"], target["llm"], target["scenario_id"])
    v1_dir = attempt_dir / "v1"
    v1_dir.mkdir(exist_ok=True)
    (attempt_dir / "attack.json").rename(v1_dir / "attack.json")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 60)
        if proc.returncode != 0:
            logger.warning("run_attack failed: %s", proc.stderr[-400:])
    except subprocess.TimeoutExpired:
        logger.warning("eval timed out for %s", safe_id)

    result_path = v1_dir / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text())
    return {"is_break": False, "error": "no result.json produced"}


def evaluate_concepts(
    source_run: str,
    targets: list[dict],
    output_dir: Path,
    timeout: int = 300,
    attacks_root: str = "attacks",
    counted_only: bool = True,
) -> dict:
    vcg_path = Path(attacks_root) / source_run / "success" / "vcg.md"
    if not vcg_path.exists():
        vcg_path = Path(attacks_root) / source_run / "vcg.md"
    concepts = parse_concepts_from_vcg(vcg_path)
    if counted_only:
        concepts = [c for c in concepts if c["is_counted"]]
    logger.info("Loaded %d concepts from %s", len(concepts), vcg_path)
    if not concepts:
        raise RuntimeError(f"No concepts found in {vcg_path} (counted_only={counted_only})")

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = []
    for concept in concepts:
        for target in targets:
            result = _run_one_eval(concept, target, output_dir, timeout=timeout)
            matrix.append({
                "concept_id": concept["id"],
                "concept_mechanism": concept["mechanism"][:120],
                "target_framework": target["framework"],
                "target_llm": target["llm"],
                "target_scenario": target["scenario_id"],
                "is_break": bool(result.get("is_break", False)),
                "attack_score": result.get("attack_score"),
                "error": result.get("error"),
            })

    per_concept: dict[str, dict[str, int]] = defaultdict(lambda: {"attempts": 0, "breaks": 0})
    per_target: dict[str, dict[str, int]] = defaultdict(lambda: {"attempts": 0, "breaks": 0})
    for row in matrix:
        per_concept[row["concept_id"]]["attempts"] += 1
        if row["is_break"]:
            per_concept[row["concept_id"]]["breaks"] += 1
        tkey = f"{row['target_framework']}/{row['target_llm']}"
        per_target[tkey]["attempts"] += 1
        if row["is_break"]:
            per_target[tkey]["breaks"] += 1

    summary = {
        "source_run": source_run,
        "n_concepts": len(concepts),
        "n_targets": len(targets),
        "timestamp": datetime.utcnow().isoformat(),
        "overall_transfer_rate": sum(r["is_break"] for r in matrix) / max(len(matrix), 1),
        "per_concept_transfer": {
            k: {**v, "rate": v["breaks"] / max(v["attempts"], 1)}
            for k, v in per_concept.items()
        },
        "per_target_break_rate": {
            k: {**v, "rate": v["breaks"] / max(v["attempts"], 1)}
            for k, v in per_target.items()
        },
        "matrix": matrix,
    }
    (output_dir / "eval_matrix.json").write_text(json.dumps(summary, indent=2))
    return summary


def main():
    _setup_logging()
    p = argparse.ArgumentParser()
    p.add_argument("--source-run", required=True,
                   help="Run code whose vcg.md to load concepts from")
    p.add_argument("--targets-file", required=True,
                   help="JSON file: list of {framework, llm, scenario_id}")
    p.add_argument("--output-dir", required=True)
    p.add_argument("--timeout", default=300, type=int)
    p.add_argument("--attacks-root", default="attacks")
    p.add_argument("--all-concepts", action="store_true",
                   help="Include candidate (non-counted) concepts too")
    args = p.parse_args()

    targets = json.loads(Path(args.targets_file).read_text())
    summary = evaluate_concepts(
        source_run=args.source_run,
        targets=targets,
        output_dir=Path(args.output_dir),
        timeout=args.timeout,
        attacks_root=args.attacks_root,
        counted_only=not args.all_concepts,
    )
    print(f"\n=== Concept Cross-target Evaluation ===")
    print(f"Source run: {summary['source_run']}")
    print(f"Concepts: {summary['n_concepts']}  Targets: {summary['n_targets']}")
    print(f"Overall transfer rate: {summary['overall_transfer_rate']:.2%}")
    print(f"\nPer-concept transfer rate:")
    for cid, v in summary["per_concept_transfer"].items():
        print(f"  {cid}: {v['rate']:.2%} ({v['breaks']}/{v['attempts']})")
    print(f"\nPer-target break rate:")
    for tkey, v in summary["per_target_break_rate"].items():
        print(f"  {tkey}: {v['rate']:.2%} ({v['breaks']}/{v['attempts']})")


if __name__ == "__main__":
    main()
