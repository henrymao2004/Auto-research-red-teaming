"""dtagent held-out eval driver (host-side)."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AR = HERE.parents[2]
ATTACKS = AR / "attacks"

from plugins.scenarios.dtagent import make_attack, metrics, reset_seed  # noqa: E402


def _threat(gid: str) -> str:
    for marker, tm in (("-dir-", "direct"), ("-ind-", "indirect")):
        if marker in gid:
            return tm
    return "?"


def _heldout(domains: list[str] | None) -> list[str]:
    ho = json.loads((HERE / "heldout.json").read_text())
    out = []
    for dom, d in (ho.get("categories") or {}).items():
        if domains and dom not in domains:
            continue
        out.extend(d.get("held_out") or [])
    return out


def _run_attack(gid: str, model: str, run_code: str, timeout: int) -> dict:
    vdir = ATTACKS / run_code / f"v1"
    cmd = [
        "uv", "run", "-m", "autoresearch_redteam.run_attack",
        "--run-code", run_code, "--version", "1",
        "--victim", "claude_code", "--scenario", "dtagent", "--model", model,
        "--attacks-root", str(ATTACKS),
        "--max-input-tokens", "500000", "--max-output-tokens", "50000",
        "--timeout", str(timeout),
    ]
    subprocess.run(cmd, cwd=str(AR), capture_output=True, text=True, timeout=timeout + 120)
    rp = ATTACKS / run_code / "v1" / "result.json"
    return json.loads(rp.read_text()) if rp.exists() else {"error": "no result.json"}


def evaluate(model: str, domains: list[str] | None, threats: set[str],
             limit: int | None, timeout: int) -> dict:
    gids = [g for g in _heldout(domains) if _threat(g) in threats]
    if limit:
        gids = gids[:limit]
    eval_gids: list[str] = []
    eval_results: list[dict] = []
    for gid in gids:
        rs = reset_seed.reset_and_seed(gid)
        run_code = f"dtap_eval_{gid}"
        attack = make_attack.build(gid)
        vdir = ATTACKS / run_code / "v1"
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "attack.json").write_text(json.dumps(attack, ensure_ascii=False, indent=2))
        res = _run_attack(gid, model, run_code, timeout)
        res.setdefault("reset_rc", rs.get("rc"))
        eval_gids.append(gid)
        eval_results.append(res)
        m = (res.get("judge_verdict") or {}).get("metrics") or {}
        print(f"  {gid:42} reset_rc={rs.get('rc')} util={m.get('utility')} "
              f"asr={m.get('targeted_asr')}", file=sys.stderr)

    agg = metrics.aggregate(eval_results, eval_gids)
    summary = {"model": model, **agg}
    (HERE / "heldout_eval.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--domains", default="crm")
    ap.add_argument("--threat", default="direct,indirect")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=int, default=300)
    a = ap.parse_args()
    doms = [d.strip() for d in a.domains.split(",") if d.strip()]
    threats = {t.strip() for t in a.threat.split(",") if t.strip()}
    s = evaluate(a.model, doms, threats, a.limit, a.timeout)
    print(metrics.format_report(s))


if __name__ == "__main__":
    main()
