"""Gate-first falsification self-test.

Substitute FULL := B1 (the v0.8.3 native baseline) and confirm the
harness MUST emit [KILL: G1]. A harness in which the feature cannot
lose is broken and its later 'pass' is inadmissible per the lock.

This script constructs n>=200 synthetic per-arm results where FULL is
byte-identical to B1 with realistic non-zero accuracies; computes the
gates; and exits 0 if and only if the verdict is REJECT and G1 fired.
"""

from __future__ import annotations

import random
import sys

from kaos.eval.harness import (
    ArmResults, QueryResult, compute_verdict,
)

from demo_action_realization_bench.gates import compute_gates


def _mk_arm(name: str, *, acc_action: float, acc_non_action: float,
            acc_sanity: float, seed: int, n_per: int = 220) -> ArmResults:
    rng = random.Random(hash((name, seed)) & 0xffffffff)
    a = ArmResults(arm=name)
    for label, p in (("action", acc_action),
                     ("non_action", acc_non_action),
                     ("sanity", acc_sanity)):
        for i in range(n_per):
            a.per_query.append(QueryResult(
                qid=f"{label}-{i}",
                qclass=label,
                correct=(rng.random() < p),
                split="in_dist",
            ))
    return a


def main() -> int:
    b1 = _mk_arm("B1", acc_action=0.25, acc_non_action=0.35,
                 acc_sanity=0.99, seed=1)
    full = ArmResults(arm="FULL", per_query=list(b1.per_query))  # := B1
    arms = {
        "B0": _mk_arm("B0", acc_action=0.05, acc_non_action=0.10,
                      acc_sanity=0.99, seed=2),
        "B1": b1,
        "FULL": full,
        "L1": _mk_arm("L1", acc_action=0.25, acc_non_action=0.35,
                      acc_sanity=0.99, seed=3),
        "L2": _mk_arm("L2", acc_action=0.26, acc_non_action=0.34,
                      acc_sanity=0.99, seed=4),
    }

    # Synthetic overhead numbers well within the budget so G4 doesn't
    # falsely fail and mask the G1 kill signal we're testing for.
    inline_us = {a: [10.0 + 0.001 * i for i in range(660)] for a in arms}

    outs = compute_gates(arms, inline_overhead_us_by_arm=inline_us)
    verdict = compute_verdict(outs, judge_kappa=1.0, kappa_min=0.85)

    print("=" * 70)
    print("GATE-FIRST FALSIFICATION SELF-TEST  (FULL := B1)")
    print("=" * 70)
    for g in outs:
        flag = "PASS" if g.passed else ("FAIL-KILL" if g.kill else "FAIL")
        print(f"  [{flag:9}] {g.gate}  {g.name}")
        print(f"             {g.detail}")
    print("-" * 70)
    print(f"  VERDICT: {verdict}")
    print("-" * 70)

    g1 = next(g for g in outs if g.gate == "G1")
    if verdict.startswith("REJECT") and not g1.passed and "G1" in verdict:
        print("\n  [OK] Harness is ADMISSIBLE: with FULL==B1 it emits "
              "[KILL: G1].\n       The feature can lose. Proceeding "
              "is permitted.")
        return 0
    print("\n  [BROKEN HARNESS] FULL==B1 did NOT trigger [KILL: G1]. "
          "Any later 'pass' is INADMISSIBLE per the lock.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
