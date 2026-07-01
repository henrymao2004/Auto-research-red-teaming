"""Regenerate the AgentHazard Stage-1/held-out split.

Writes two files at the autoresearcher/ root:
  - `ahz_train.json`   — Stage-1 view; what Stage 1 sub-agents read to know
                         which instance IDs are eligible to attack.
  - `ahz_heldout.json` — held-out-only view; DENIED to the agent. Read by
                         Stage 2 scripts (run as bash subprocess, post Stage 1)
                         and by run_attack.py to classify instance IDs.

There is intentionally no combined split file: keeping the held-out IDs
in a separately-permissioned file prevents Stage 1 leakage.
"""
from __future__ import annotations

import json
import random
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLEAN = HERE / "clean"
OUT_TRAIN = HERE / "train.json"
OUT_HELDOUT = HERE / "heldout.json"

SEED = 42
HELDOUT_PER_CAT = 9

rng = random.Random(SEED)
result = {
    "seed": SEED,
    "split_method": f"stratified random by category, {HELDOUT_PER_CAT} held-out per category ({HELDOUT_PER_CAT * 10} total)",
    "categories": {},
}

categories = sorted(p.name for p in CLEAN.iterdir() if p.is_dir())
total_train = total_heldout = 0
for cat in categories:
    ids = sorted(int(p.stem) for p in (CLEAN / cat).glob("*.json"))
    rng_local = random.Random(SEED + hash(cat) % 1_000_000)
    shuffled = ids[:]
    rng_local.shuffle(shuffled)
    held = sorted(shuffled[:HELDOUT_PER_CAT])
    train = sorted(shuffled[HELDOUT_PER_CAT:])
    result["categories"][cat] = {
        "total": len(ids),
        "train": train,
        "held_out": held,
    }
    total_train += len(train)
    total_heldout += len(held)
    print(f"{cat}: total={len(ids)} train={len(train)} held_out={len(held)}")

train_view = {
    "seed": SEED,
    "split_method": result["split_method"],
    "categories": {
        cat: {"total": c["total"], "train": c["train"]}
        for cat, c in result["categories"].items()
    },
}
heldout_view = {
    "seed": SEED,
    "split_method": result["split_method"],
    "categories": {
        cat: {"total": c["total"], "held_out": c["held_out"]}
        for cat, c in result["categories"].items()
    },
}

OUT_TRAIN.write_text(json.dumps(train_view, indent=2))
OUT_HELDOUT.write_text(json.dumps(heldout_view, indent=2))
print(f"\nWrote {OUT_TRAIN}, {OUT_HELDOUT}")
print(f"TOTAL: train={total_train} held_out={total_heldout}")
