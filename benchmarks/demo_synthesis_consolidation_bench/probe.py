"""Cheap pre-committed probe for extractive consolidation.

Gates P1/P2/P3 are frozen in PROBE_PREREG.md (committed before any EXT
code existed). Any fail => DO NOT BUILD, reported faithfully, no
retune. All pass => earns the full ISA.lock.v3 pre-registration.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from kaos import Kaos
from kaos.dream.phases import synthesis as S
from workload import build_workload
from queries import build_queries
import arms as A

SEED = 20260516
HARD = {"compositional_multihop", "abstraction_only"}
CACHE = HERE / ".synth_cache" / "cache.json"


def _acc(arm: str, db: str, qs) -> float:
    rows = A.retrieve_all(arm, db, qs)
    hard = [(q, r) for q, r in zip(qs, rows)
            if q.qclass in HARD and q.split == "in_dist"]
    if not hard:
        return 0.0
    return sum(1 for q, r in hard if q.decisive(r.texts)) / len(hard)


def main() -> int:
    print("=" * 66)
    print("EXTRACTIVE-CONSOLIDATION CHEAP PROBE (gates frozen in "
          "PROBE_PREREG.md)")
    print("=" * 66)
    base = str(HERE / "_pbase.db")
    idx = build_workload(base, SEED, days=90, incidents_per_day=6)
    qs = build_queries(idx)
    print(f"workload: {len(idx.incidents)} incidents -> "
          f"{len(idx.mem_text)} memories; {len(qs)} queries")

    dbp = {a: str(HERE / f"_p_{a}.db")
           for a in ("B0", "B1", "EXT", "FULL")}
    for a, p in dbp.items():
        shutil.copyfile(base, p)

    # EXT arm: non-LLM extractive consolidation.
    ke = Kaos(db_path=dbp["EXT"])
    try:
        rep = S.extractive_consolidate(ke.conn, index_insights=True)
    finally:
        ke.close()
    print(f"EXT: {rep.insights_written} extractive insights "
          f"({rep.clusters_found} clusters)")

    # FULL_v2 arm: the REJECTED LLM synthesis, replayed verbatim from the
    # hash-locked cache (llm_call_fn=None => cannot make new calls; only
    # cached insights are written -> it cannot be re-weakened).
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    kf = Kaos(db_path=dbp["FULL"])
    try:
        repf = S.run(kf.conn, llm_call_fn=None, cache=cache,
                     index_insights=True)
    finally:
        kf.close()
    print(f"FULL_v2 replay: {repf.insights_written} cached insights "
          f"(cache size {len(cache)})")

    # ── P1: mechanical token-faithfulness (zero tolerance) ──────────
    import re
    tok_re = re.compile(r"[a-z0-9]+")
    kE = Kaos(db_path=dbp["EXT"])
    try:
        srcs = [c.lower() for (c,) in kE.conn.execute(
            "SELECT content FROM memory WHERE type != 'insight'")]
        ins = [c for (c,) in kE.conn.execute(
            "SELECT content FROM memory WHERE type = 'insight'")]
    finally:
        kE.close()
    src_blob = "\n".join(srcs)
    bad = 0
    total = 0
    for it in ins:
        for t in tok_re.findall(it.lower()):
            total += 1
            if t not in src_blob:
                bad += 1
    p1 = (total > 0 and bad == 0)
    print(f"\nP1 token-faithfulness: {total-bad}/{total} verbatim "
          f"(need 100%) -> {'PASS' if p1 else 'FAIL'}")

    # ── P2 / P3: hard-class accuracy ────────────────────────────────
    acc = {a: _acc(a, dbp[a], qs) for a in ("B0", "B1", "EXT", "FULL")}
    print(f"hard in-dist acc: B0={acc['B0']:.3f} B1={acc['B1']:.3f} "
          f"EXT={acc['EXT']:.3f} FULL_v2={acc['FULL']:.3f}")
    p2_margin = acc["EXT"] - max(acc["B0"], acc["B1"])
    p3_margin = acc["EXT"] - acc["FULL"]
    p2 = p2_margin >= 0.05
    p3 = p3_margin >= 0.05
    print(f"P2 EXT-max(B0,B1) = {p2_margin:+.3f} (need >=+0.05) -> "
          f"{'PASS' if p2 else 'FAIL'}")
    print(f"P3 EXT-FULL_v2    = {p3_margin:+.3f} (need >=+0.05) -> "
          f"{'PASS' if p3 else 'FAIL'}")

    print("-" * 66)
    if p1 and p2 and p3:
        verdict = ("ESCALATE: probe cleared -> earns full ISA.lock.v3 "
                   "pre-registration (necessary, not sufficient)")
        rc = 0
    else:
        fails = [n for n, ok in (("P1", p1), ("P2", p2), ("P3", p3))
                 if not ok]
        verdict = (f"DO NOT BUILD: {','.join(fails)} failed. Faithful, "
                   f"final, no retune-and-rerun.")
        rc = 1
    print(f"PROBE VERDICT: {verdict}")
    print("-" * 66)

    (HERE / "probe_results.json").write_text(json.dumps({
        "acc": acc, "P1": p1, "P2": p2, "P3": p3,
        "p2_margin": p2_margin, "p3_margin": p3_margin,
        "verdict": verdict,
    }, indent=2))
    return rc


if __name__ == "__main__":
    sys.exit(main())
