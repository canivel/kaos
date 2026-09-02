"""Read every benchmark result JSON in a directory and fail on bad verdicts.

    python benchmarks/check_gates.py results/ [--fail-on REJECT,VOID]

Each result file must carry a top-level "verdict" string: ACCEPT, or
"REJECT: ..." / "VOID: ...". Missing directories or files are warnings,
not failures — a benchmark that was not run cannot fail a gate.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("results_dir")
    ap.add_argument("--fail-on", default="REJECT,VOID")
    args = ap.parse_args(argv)
    fail_on = {s.strip().upper() for s in args.fail_on.split(",") if s.strip()}
    d = Path(args.results_dir)
    if not d.is_dir():
        print(f"warning: results dir {d} does not exist — nothing to check")
        return 0
    files = sorted(d.glob("*.json"))
    if not files:
        print(f"warning: no result files in {d}")
        return 0
    bad = 0
    for f in files:
        try:
            verdict = str(json.loads(f.read_text()).get("verdict", "MISSING"))
        except json.JSONDecodeError as exc:
            print(f"warning: {f.name}: not JSON ({exc})")
            continue
        head = verdict.split(":", 1)[0].strip().upper()
        mark = "FAIL" if head in fail_on else "ok"
        print(f"{mark:4s} {f.name}: {verdict}")
        if head in fail_on:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
