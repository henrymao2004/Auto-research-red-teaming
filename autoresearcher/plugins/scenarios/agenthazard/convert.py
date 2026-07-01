"""Convert AgentHazard dataset.json into our per-instance file layout.

Produces:
  - <output>/<category>/<id>.json   for each of the 2653 instances
    (strips fields the autoresearch agent must not see: `decomposed_query`
    [AgentHazard's own reference attack], `comment`, `jailbreak_method`)
  - <judge-data-out>                judge-only sidecar mapping id -> full
    instance (read by the host-side judge for prompt context; NEVER read
    by the autoresearch agent)

After this script, run `regen_split.py` to produce ahz_train.json and
ahz_heldout.json with the 9-per-category held-out split.

Categories (10): Data_Exfiltration, Privilege_Escalation, Destructive_Action,
                Compliance_Bypass, Resource_Exhaustion, Supply_Chain_Poisoning,
                System_RCE, Internal_Reconnaissance, Prompt_Intel_Theft,
                Persistence_Establishment.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Fields hidden from the researcher.
STRIP_FIELDS = ("decomposed_query", "comment", "jailbreak_method")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, required=True,
                   help="Path to AgentHazard dataset.json (2653 instances)")
    here = Path(__file__).resolve().parent
    p.add_argument("--output", type=Path, default=here / "clean",
                   help="Output directory for per-instance JSONs "
                        "(default: plugins/scenarios/agenthazard/clean/)")
    p.add_argument("--judge-data-out", type=Path,
                   default=here / "judge_data.json",
                   help="Judge-only sidecar id->instance index "
                        "(default: plugins/scenarios/agenthazard/judge_data.json)")
    args = p.parse_args()

    instances = json.loads(args.source.read_text())
    print(f"loaded {len(instances)} AgentHazard instances from {args.source}")

    by_cat: dict[str, list[dict]] = {}
    for inst in instances:
        cat = inst.get("category", "Uncategorized")
        by_cat.setdefault(cat, []).append(inst)
    print("categories:", {c: len(v) for c, v in sorted(by_cat.items())})

    args.output.mkdir(parents=True, exist_ok=True)
    written = 0
    for cat, items in sorted(by_cat.items()):
        cat_dir = args.output / cat
        cat_dir.mkdir(parents=True, exist_ok=True)
        for inst in items:
            cleaned = {k: v for k, v in inst.items() if k not in STRIP_FIELDS}
            (cat_dir / f"{inst['id']}.json").write_text(
                json.dumps(cleaned, indent=2, ensure_ascii=False)
            )
            written += 1
    print(f"wrote {written} per-instance files under {args.output}/")

    judge_data = {str(inst["id"]): inst for inst in instances}
    args.judge_data_out.write_text(
        json.dumps(judge_data, indent=2, ensure_ascii=False)
    )
    print(f"wrote judge-only index ({len(judge_data)} ids) to {args.judge_data_out}")
    print("\nnext step: uv run python scripts/regen_split.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
