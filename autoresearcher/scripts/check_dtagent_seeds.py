#!/usr/bin/env python3
"""Audit every dtagent reset+seed setup.sh for SILENT failures.

Why this exists: setup.sh seeds the shared backends via authenticated HTTP calls,
but those helpers swallow errors (``curl -sf`` / ``[WARN] ...``) and ``rc`` stays 0
even when a backend's token rotated or a seed endpoint 404'd. The world then ends
up empty/partial, the attack has nothing to act on, and the whole domain reads a
FALSE 0% (or depressed) ASR. ``rc == 0`` is NOT proof the seed worked — this script
runs each setup.sh host-side (same env as ``reset_seed.reset_and_seed``) and scans
the FULL output (not just the tail ``reset_and_seed`` keeps) for failure signals.

Run it before trusting a dtagent eval (especially after rebuilding any backend):

    python3 scripts/check_dtagent_seeds.py            # all domains
    python3 scripts/check_dtagent_seeds.py os-filesystem workflow

Exit status: 0 if every instance is clean, 1 if any failure signal is found.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO))
os.chdir(REPO)

from plugins.scenarios.dtagent.reset_seed import _BACKEND_PORTS  # noqa: E402

SETUPS = REPO / "plugins" / "scenarios" / "dtagent" / "setups"

# Detect seed failures.
FAIL_RE = re.compile(
    r"exec_cmd failed|skipping seed|Invalid token"
    r'|"detail"\s*:\s*"Not Found"'
    r"|->\s*[45][0-9][0-9]:"
    r"|curl: \(",
    re.I,
)
# Ignore benign reset lines.
BENIGN_RE = re.compile(
    r"Email already registered|assuming already present|Zoom register"
    r"|Zoom meeting create failed",
    re.I,
)

# Enable all seed gates.
GATES = ("OS_FILESYSTEM_PROJECT_NAME", "SLACK_PROJECT_NAME",
         "GMAIL_PROJECT_NAME", "PAYPAL_PROJECT_NAME")


def run_one(setup: Path, gid: str) -> tuple[int, list[str]]:
    env = dict(os.environ, **_BACKEND_PORTS, **{k: gid for k in GATES})
    try:
        p = subprocess.run(["bash", str(setup)], cwd=str(setup.parent), env=env,
                           capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return -1, ["TIMEOUT"]
    out = (p.stdout or "") + (p.stderr or "")
    hits = []
    for ln in out.splitlines():
        if FAIL_RE.search(ln) and not BENIGN_RE.search(ln):
            hits.append(ln.strip()[:120])
    return p.returncode, hits


def main(argv: list[str]) -> int:
    domains = argv[1:] or ["crm", "medical", "os-filesystem", "workflow"]
    summary = defaultdict(lambda: {"n": 0, "rc_bad": 0, "fail": 0, "examples": []})
    total_fail = 0
    for dom in domains:
        insts = sorted((SETUPS / dom).glob("*/setup.sh"))
        print(f"[{dom}] auditing {len(insts)} instances ...", flush=True)
        for i, sp in enumerate(insts):
            gid = sp.parent.name
            rc, hits = run_one(sp, gid)
            s = summary[dom]
            s["n"] += 1
            if rc not in (0, None):
                s["rc_bad"] += 1
            if hits:
                s["fail"] += 1
                total_fail += 1
                if len(s["examples"]) < 5:
                    s["examples"].append(f"{gid}: {hits[0]}")
            if (i + 1) % 50 == 0:
                print(f"  {i + 1}/{len(insts)}", flush=True)

    print("\n===== dtagent seed audit =====")
    for dom in domains:
        s = summary[dom]
        flag = "OK" if s["fail"] == 0 and s["rc_bad"] == 0 else "FAIL"
        print(f"{dom:13}: n={s['n']:3}  fail={s['fail']:3}  rc!=0={s['rc_bad']:3}  [{flag}]")
        for e in s["examples"]:
            print(f"     - {e}")
    print(f"\n{'ALL CLEAN' if total_fail == 0 else f'{total_fail} INSTANCE(S) WITH SEED FAILURES'}")
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
