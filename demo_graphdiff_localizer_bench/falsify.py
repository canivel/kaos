"""Falsification self-test (gate-first, per the lock):

  1. FULL := B1  — substitute the feature arm's results with the native
     localizer's. The harness MUST emit [KILL: G1] (the +10pp delta
     clause cannot hold when FULL == B1).
  2. FULL := L1  — substitute with the wrong-pair lesion. MUST kill on
     G1 or G2.

A harness that cannot kill the feature is INADMISSIBLE; run.py must not
produce a binding verdict until this exits 0.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from kaos.eval.harness import ArmResults, compute_verdict

from demo_graphdiff_localizer_bench import arms as A
from demo_graphdiff_localizer_bench.gates import compute_gates
from demo_graphdiff_localizer_bench.run import DB_PATH, run_arms
from demo_graphdiff_localizer_bench.workload import build


def _clone(ar: ArmResults, as_name: str) -> ArmResults:
    out = ArmResults(arm=as_name)
    out.per_query = list(ar.per_query)
    return out


def main() -> int:
    if DB_PATH.exists():
        DB_PATH.unlink()
    episodes = build(str(DB_PATH))
    failed = [e for e in episodes if e.qclass != "success"]
    successes = [e for e in episodes if e.qclass == "success"]
    conn = sqlite3.connect(DB_PATH)
    arms = run_arms(conn, failed, successes)
    pair_rate = A.pairing_same_family_rate(conn, failed, successes)
    conn.close()

    ok = True
    for sub in ("B1", "L1"):
        substituted = dict(arms)
        substituted["FULL"] = _clone(arms[sub], "FULL")
        outcomes = compute_gates(
            substituted,
            organic_median_reuse=99.0,   # G3 forced-pass: self-test targets G1/G2
            organic_n_agents=999,
            pairing_same_family_rate=pair_rate,
        )
        verdict = compute_verdict(outcomes, judge_kappa=1.0, kappa_min=0.85)
        killed = [g.gate for g in outcomes if g.kill and not g.passed]
        want = {"B1": {"G1"}, "L1": {"G1", "G2"}}[sub]
        hit = bool(set(killed) & want)
        print(f"FULL := {sub}: verdict={verdict} killed={killed} "
              f"(need one of {sorted(want)}) -> "
              f"{'ADMISSIBLE' if hit and verdict.startswith('REJECT') else 'INADMISSIBLE'}")
        ok = ok and hit and verdict.startswith("REJECT")

    print("falsification self-test:", "PASS — harness CAN kill the feature" if ok
          else "FAIL — harness cannot kill the feature; probe INADMISSIBLE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
