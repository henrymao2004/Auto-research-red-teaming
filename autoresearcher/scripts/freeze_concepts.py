"""Freeze COUNTED concepts from a finished autoresearch run.

Reads attacks/<run_code>/vcg.md and freezes the VC-NNNN blocks under the
``## Counted Concepts`` section. The section boundary is the source of truth;
this script does not re-apply promotion predicates from concept fields.

Writes held_out_eval/<run_code>/frozen_concepts.json — the list of concepts
that proceed to held-out eval. Once written, this file is the contract:
held-out evaluation may not introduce new concepts after this point.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
# Match annotated VC headings.
_CONCEPT_RE = re.compile(r"^###\s+(VC-\d+)\b.*$", re.M)
_FIELD_RE = re.compile(r"\s*-\s+\*\*(\w+)\*\*:\s*(.*)")


def _counted_section(text: str) -> str:
    headers = list(_SECTION_RE.finditer(text))
    for idx, header in enumerate(headers):
        if not header.group(1).strip().lower().startswith("counted concepts"):
            continue
        start = header.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        return text[start:end]
    return ""


def parse_vcg(vcg_path: Path) -> list[dict]:
    text = _counted_section(vcg_path.read_text())
    headers = list(_CONCEPT_RE.finditer(text))
    concepts = []
    for idx, header in enumerate(headers):
        vc_id = header.group(1)
        start = header.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(text)
        body = text[start:end]
        fields: dict = {"id": vc_id}
        for line in body.split("\n"):
            m = _FIELD_RE.match(line)
            if m:
                fields[m.group(1)] = m.group(2).strip()
        concepts.append(fields)
    return concepts


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: freeze_concepts.py <run_code>", file=sys.stderr)
        return 2
    run_code = argv[1]
    # Try both VCG locations.
    candidates = [
        Path(f"attacks/{run_code}/vcg.md"),
        Path(f"attacks/{run_code}/success/vcg.md"),
    ]
    vcg = next((p for p in candidates if p.exists()), None)
    if vcg is None:
        print(f"vcg not found under attacks/{run_code}/ — tried: "
              + ", ".join(str(p) for p in candidates), file=sys.stderr)
        return 1
    print(f"using vcg: {vcg}")
    out_dir = Path(f"held_out_eval/{run_code}")
    out_dir.mkdir(parents=True, exist_ok=True)

    counted = parse_vcg(vcg)

    out = out_dir / "frozen_concepts.json"
    out.write_text(json.dumps(counted, indent=2, ensure_ascii=False))
    print(
        f"{len(counted)} COUNTED concepts frozen from section -> {out}"
    )
    for c in counted:
        print(f"  {c['id']}  conf={c.get('confidence')} n_conf={c.get('n_confirmations')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
