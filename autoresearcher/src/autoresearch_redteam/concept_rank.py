"""Concept ranking — mean / median rank of each concept across target combos."""

from __future__ import annotations

import argparse
import json
import statistics
from collections import defaultdict
from pathlib import Path


def rank_concepts(matrix_path: Path) -> dict:
    summary = json.loads(matrix_path.read_text())
    rows = summary["matrix"]

    # Group by target.
    by_target: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        tkey = f"{r['target_framework']}/{r['target_llm']}/{r['target_scenario']}"
        by_target[tkey].append(r)

    concept_ranks: dict[str, list[int]] = defaultdict(list)
    concept_scores: dict[str, list[float]] = defaultdict(list)
    for tkey, target_rows in by_target.items():
        scored = [
            (r, (r.get("attack_score") if r.get("attack_score") is not None
                 else (1.0 if r.get("is_break") else 0.0)))
            for r in target_rows
        ]
        scored.sort(key=lambda x: -x[1])
        # Assign dense ranks.
        prev_score = None
        cur_rank = 0
        for i, (r, sc) in enumerate(scored):
            if sc != prev_score:
                cur_rank = i + 1
                prev_score = sc
            concept_ranks[r["concept_id"]].append(cur_rank)
            concept_scores[r["concept_id"]].append(sc)

    leaderboard = []
    for cid, ranks in concept_ranks.items():
        scores = concept_scores[cid]
        leaderboard.append({
            "concept_id": cid,
            "mean_rank": round(sum(ranks) / len(ranks), 2),
            "median_rank": statistics.median(ranks),
            "mean_score": round(sum(scores) / len(scores), 3),
            "best_rank": min(ranks),
            "worst_rank": max(ranks),
            "n_targets": len(ranks),
        })
    leaderboard.sort(key=lambda r: r["mean_rank"])

    return {
        "n_concepts": len(leaderboard),
        "n_targets": len(by_target),
        "leaderboard": leaderboard,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--eval-matrix", required=True,
                   help="Path to eval_matrix.json from evaluate_concepts")
    p.add_argument("--output", default=None,
                   help="Optional output JSON path (default: same dir as eval-matrix)")
    args = p.parse_args()

    matrix_path = Path(args.eval_matrix)
    result = rank_concepts(matrix_path)

    out_path = Path(args.output) if args.output else (matrix_path.parent / "concept_rank.json")
    out_path.write_text(json.dumps(result, indent=2))

    print(f"\n=== Concept Leaderboard ===")
    print(f"Concepts: {result['n_concepts']}  Targets: {result['n_targets']}")
    print(f"\n{'Concept':<10} {'MeanRank':>10} {'MedRank':>8} {'MeanScore':>11} {'Best':>5} {'Worst':>5}")
    print("-" * 60)
    for row in result["leaderboard"]:
        print(f"{row['concept_id']:<10} {row['mean_rank']:>10.2f} {row['median_rank']:>8} "
              f"{row['mean_score']:>11.3f} {row['best_rank']:>5} {row['worst_rank']:>5}")


if __name__ == "__main__":
    main()
