"""Render attacks/<run_code>/SUMMARY.md from a Stage 1 run.

Single-file digest of what the run produced. Sections:

  1. Header — cell metadata + iteration count + Stage 1 ASR
  2. Top COUNTED concepts — table of mechanism / template / counters
  3. Candidate concepts (top-K, briefly)
  4. VCG graph — embedded mermaid diagram from VCG edges
  5. Latest Critic check excerpt (if any)
  6. Per-mode iteration breakdown
  7. Falsified-hypothesis examples (informative dead ends)

Run after Stage 1 stops (monitor STOP or hit OUTER_CAP):

    uv run python scripts/render_summary.py <run_code>

Writes attacks/<run_code>/SUMMARY.md. Idempotent — overwrite-on-rerun.

Stage 2 still consumes vcg.md (COUNTED concepts) directly; SUMMARY.md
is for humans / sharing, not for the router pipeline.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CONCEPT_HEADER = re.compile(r"^### (VC-\d{4})\s*$")
_FIELD = re.compile(r"^- \*\*([^*]+)\*\*:\s*(.*)$")


def parse_vcg(vcg_path: Path) -> dict[str, Any]:
    """Return {'counted': [...], 'candidate': [...], 'edges': [...]}.

    Each concept dict has keys: id, plus whatever fields the VCG has
    (mechanism, attack_template, enabling_condition, failure_outcome,
    transfer_prediction, provenance, confidence, n_observations,
    n_confirmations, n_falsifications, targets_validated).
    """
    if not vcg_path.exists():
        return {"counted": [], "candidate": [], "edges": []}

    text = vcg_path.read_text()
    sections = re.split(r"^## ", text, flags=re.M)
    counted: list[dict] = []
    candidate: list[dict] = []
    edges: list[dict] = []

    for section in sections:
        sec_head = section.split("\n", 1)[0].strip()
        body = section[len(sec_head):]
        if sec_head.startswith("Counted Concepts"):
            counted = _parse_concept_blocks(body)
        elif sec_head.startswith("Candidate Concepts"):
            candidate = _parse_concept_blocks(body)
        elif sec_head.startswith("Edges"):
            edges = _parse_edges(body)

    return {"counted": counted, "candidate": candidate, "edges": edges}


def _parse_concept_blocks(body: str) -> list[dict]:
    out: list[dict] = []
    current: dict | None = None
    for raw in body.splitlines():
        m = _CONCEPT_HEADER.match(raw)
        if m:
            if current:
                out.append(current)
            current = {"id": m.group(1)}
            continue
        f = _FIELD.match(raw)
        if f and current is not None:
            current[f.group(1).strip().lower().replace(" ", "_")] = f.group(2).strip()
    if current:
        out.append(current)
    return out


def _parse_edges(body: str) -> list[dict]:
    out: list[dict] = []
    for raw in body.splitlines():
        if not raw.startswith("|"):
            continue
        cells = [c.strip() for c in raw.strip("|").split("|")]
        if len(cells) < 4 or cells[0] in ("from", "---"):
            continue
        if not cells[0].startswith("VC-") or not cells[2].startswith("VC-"):
            continue
        out.append({
            "from": cells[0], "relation": cells[1], "to": cells[2],
            "confidence": cells[3] if len(cells) > 3 else "",
            "evidence": cells[4] if len(cells) > 4 else "",
        })
    return out


_ITER_ROW = re.compile(
    r"^v(\d+)\s*\|\s*(\d+)\s*\|\s*(\w+)\s*\|\s*(\w+)\s*\|\s*(true|false)\s*\|\s*(\w+)\s*\|"
)


def parse_agent_log(log_path: Path) -> dict[str, Any]:
    """Return {'iter_rows': [...], 'latest_critic': str | None, 'goal': str | None}."""
    if not log_path.exists():
        return {"iter_rows": [], "latest_critic": None, "goal": None}
    text = log_path.read_text()
    iter_rows: list[dict] = []
    for raw in text.splitlines():
        m = _ITER_ROW.match(raw.strip())
        if m:
            iter_rows.append({
                "n": int(m.group(1)),
                "instance_id": int(m.group(2)),
                "category": m.group(3),
                "mode": m.group(4),
                "is_break": m.group(5) == "true",
                "hypothesis_status": m.group(6),
            })

    critic_blocks = re.findall(
        r"(## Critic check @ v\d+.*?)(?=\n## |\Z)", text, flags=re.S
    )
    latest_critic = critic_blocks[-1].strip() if critic_blocks else None

    goal_m = re.search(r"^\*\*Goal\*\*:\s*(.+)$", text, flags=re.M)
    goal = goal_m.group(1).strip() if goal_m else None

    return {"iter_rows": iter_rows, "latest_critic": latest_critic, "goal": goal}


def parse_run_hint(hint_path: Path) -> dict[str, str]:
    """Return {'victim', 'scenario', 'researcher', 'model', 'goal_brief'}."""
    cells = {"victim": "", "scenario": "", "researcher": "", "model": "",
             "goal_brief": ""}
    if not hint_path.exists():
        return cells
    for raw in hint_path.read_text().splitlines():
        m = re.match(r"^#\s*(Victim|Scenario|Researcher|Model|Goal brief):\s*(.+)$", raw)
        if m:
            key = m.group(1).lower().replace(" ", "_")
            cells[key] = m.group(2).strip()
    return cells


def render_mermaid(vcg: dict[str, Any]) -> str:
    """Emit a mermaid `graph LR` of the VCG nodes + edges."""
    counted = vcg.get("counted", [])
    candidate = vcg.get("candidate", [])
    edges = vcg.get("edges", [])
    if not counted and not candidate and not edges:
        return "```\n(VCG empty — no concepts to graph yet.)\n```"

    lines = ["```mermaid", "graph LR"]
    seen: set[str] = set()
    for c in counted:
        vid = c.get("id")
        if not vid:
            continue
        seen.add(vid)
        label = (c.get("mechanism") or "")[:50].replace('"', "'")
        lines.append(f'  {_node_id(vid)}["{vid}<br/>{label}"]:::counted')
    for c in candidate:
        vid = c.get("id")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        label = (c.get("mechanism") or "")[:50].replace('"', "'")
        lines.append(f'  {_node_id(vid)}["{vid}<br/>{label}"]:::candidate')
    # Add missing graph nodes.
    for e in edges:
        for vid in (e["from"], e["to"]):
            if vid not in seen:
                seen.add(vid)
                lines.append(f'  {_node_id(vid)}["{vid}"]')
    for e in edges:
        rel = e["relation"].replace('"', "'")
        lines.append(
            f'  {_node_id(e["from"])} -->|{rel}| {_node_id(e["to"])}'
        )

    lines.append("  classDef counted fill:#cfe8c5,stroke:#2e7d32;")
    lines.append("  classDef candidate fill:#fff3c4,stroke:#f9a825;")
    lines.append("```")
    return "\n".join(lines)


def _node_id(vc_id: str) -> str:
    return vc_id.replace("-", "_")


def render_summary(run_code: str, attacks_root: str = "attacks") -> Path:
    run_dir = Path(attacks_root) / run_code
    if not run_dir.exists():
        raise FileNotFoundError(f"no run directory at {run_dir}")

    vcg = parse_vcg(run_dir / "vcg.md")
    log = parse_agent_log(run_dir / "AGENT_LOG.md")
    hint = parse_run_hint(Path("RUN_HINT.md"))

    n_iter = len(log["iter_rows"])
    n_break = sum(1 for r in log["iter_rows"] if r["is_break"])
    train_asr = (n_break / n_iter) if n_iter else 0.0

    from collections import Counter
    by_mode = Counter(r["mode"] for r in log["iter_rows"])
    by_status = Counter(r["hypothesis_status"] for r in log["iter_rows"])
    by_category = Counter(r["category"] for r in log["iter_rows"])

    falsified = [r for r in log["iter_rows"] if r["hypothesis_status"] == "falsified"]
    falsified_examples = sorted(falsified, key=lambda r: r["n"], reverse=True)[:3]

    out: list[str] = []
    out.append(f"# SUMMARY — {run_code}\n")
    out.append(f"_Generated {datetime.now(timezone.utc).isoformat(timespec='seconds')}._\n")

    out.append("## Cell\n")
    out.append("| Axis | Value |\n|---|---|")
    out.append(f"| Victim     | `{hint.get('victim') or '(unknown)'}` |")
    out.append(f"| Scenario   | `{hint.get('scenario') or '(unknown)'}` |")
    out.append(f"| Researcher | `{hint.get('researcher') or '(unknown)'}` |")
    out.append(f"| Model      | `{hint.get('model') or '(unknown)'}` |")
    if hint.get("goal_brief") and hint["goal_brief"] != "none":
        out.append(f"| GOAL_BRIEF | `{hint['goal_brief']}` |")
    out.append("")
    if log["goal"]:
        out.append(f"**Outer goal**: {log['goal']}\n")

    out.append("## Headline\n")
    out.append(f"- **Iterations**: {n_iter}")
    out.append(f"- **Stage 1 ASR**: {n_break}/{n_iter} = {train_asr:.1%}")
    out.append(f"- **VCG COUNTED**: {len(vcg['counted'])} concept"
               f"{'s' if len(vcg['counted']) != 1 else ''}")
    out.append(f"- **VCG candidates**: {len(vcg['candidate'])}")
    out.append(f"- **VCG edges**: {len(vcg['edges'])}\n")

    out.append("## COUNTED concepts\n")
    if not vcg["counted"]:
        out.append("_(none promoted yet — see "
                   "[docs/shared-references/vcg-promotion.md](../../docs/shared-references/vcg-promotion.md) "
                   "for the gate.)_\n")
    else:
        out.append("| VC | Mechanism | n_conf | n_fals | conf |")
        out.append("|---|---|---:|---:|---:|")
        for c in vcg["counted"]:
            out.append(
                f"| `{c.get('id', '?')}` | {_short(c.get('mechanism', ''), 80)} | "
                f"{c.get('n_confirmations', '?')} | "
                f"{c.get('n_falsifications', '?')} | "
                f"{c.get('confidence', '?')} |"
            )
        out.append("")
        out.append("**Attack templates** (verbatim from VCG):\n")
        for c in vcg["counted"]:
            out.append(f"- **{c.get('id', '?')}** — {_short(c.get('attack_template', ''), 200)}")
        out.append("")

    if vcg["candidate"]:
        out.append("## Candidate concepts (top 5)\n")
        ranked = sorted(
            vcg["candidate"],
            key=lambda c: int(re.search(r"\d+", c.get("n_confirmations", "0") or "0").group()),
            reverse=True,
        )[:5]
        out.append("| VC | Mechanism | n_conf | provenance |")
        out.append("|---|---|---:|---|")
        for c in ranked:
            out.append(
                f"| `{c.get('id', '?')}` | {_short(c.get('mechanism', ''), 80)} | "
                f"{c.get('n_confirmations', '?')} | "
                f"{c.get('provenance', '?')} |"
            )
        out.append("")

    out.append("## VCG graph\n")
    out.append("Concepts coloured by status (green = COUNTED, yellow = candidate). "
               "Edges from the VCG `Edges` section.\n")
    out.append(render_mermaid(vcg))
    out.append("")

    out.append("## Iteration breakdown\n")
    out.append("### By mode")
    if by_mode:
        out.append("| Mode | Count | Breaks |")
        out.append("|---|---:|---:|")
        for mode, cnt in by_mode.most_common():
            breaks = sum(1 for r in log["iter_rows"] if r["mode"] == mode and r["is_break"])
            out.append(f"| {mode} | {cnt} | {breaks} |")
    else:
        out.append("_(no iterations yet)_")
    out.append("")

    out.append("### By hypothesis status")
    if by_status:
        out.append("| Status | Count |")
        out.append("|---|---:|")
        for status, cnt in by_status.most_common():
            out.append(f"| {status} | {cnt} |")
    else:
        out.append("_(no reflections yet)_")
    out.append("")

    if by_category:
        out.append("### By scenario category")
        out.append("| Category | Count | Breaks |")
        out.append("|---|---:|---:|")
        for cat, cnt in by_category.most_common():
            breaks = sum(1 for r in log["iter_rows"] if r["category"] == cat and r["is_break"])
            out.append(f"| `{cat}` | {cnt} | {breaks} |")
        out.append("")

    if log["latest_critic"]:
        out.append("## Latest Critic audit\n")
        out.append(log["latest_critic"])
        out.append("")

    if falsified_examples:
        out.append("## Falsified-hypothesis examples\n")
        out.append("Dead ends from this run — useful prior context for future runs.\n")
        for r in falsified_examples:
            out.append(f"- **v{r['n']}** ({r['category']}, mode={r['mode']}, "
                       f"instance={r['instance_id']}): hypothesis_status=falsified.")
        out.append("")

    out.append("---")
    out.append("")
    out.append(
        "_VCG promotion gate: `n_confirmations ≥ 3 ∧ confidence ≥ 0.6 ∧ ≥ 1 is_break`. "
        "Partial-only never promotes. "
        "See [`docs/shared-references/vcg-promotion.md`](../../docs/shared-references/vcg-promotion.md)._"
    )

    summary_path = run_dir / "SUMMARY.md"
    summary_path.write_text("\n".join(out) + "\n")
    return summary_path


def _short(s: str, n: int) -> str:
    s = (s or "").replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def main(argv: list[str]) -> int:
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_code")
    p.add_argument("--attacks-root", default="attacks")
    args = p.parse_args(argv[1:])
    path = render_summary(args.run_code, args.attacks_root)
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
