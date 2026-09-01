"""Gate-first falsification self-test (lock: L_gate_first).

"run B0..B3 with the FULL arm stubbed to equal B0; the harness MUST emit
[KILL: G1]. A harness in which the feature cannot lose is broken and its
later 'pass' is inadmissible."

This builds >=200/class synthetic results where FULL is byte-identical to
B0 and B0 has clearly non-zero hard accuracy (so we prove G1 fails because
FULL cannot beat its OWN baseline — not because everything is zero). If
compute_gates does NOT reject on G1 here, the harness is inadmissible and
this script exits non-zero.
"""

from __future__ import annotations

import random
import sys

from gates import ArmResults, QueryResult, compute_gates, load_lock

CLASSES = ("verbatim_recall", "compositional_multihop",
           "abstraction_only", "tail_fact_probe")


def _mk(arm: str, *, hard_acc: float, verb_acc: float, tail_acc: float,
        synth_helped_hit: float, seed: int, n_per: int = 220) -> ArmResults:
    rng = random.Random(hash((arm, seed)) & 0xffffffff)
    ar = ArmResults(arm=arm)
    for split in ("in_dist", "shift"):
        for cls in CLASSES:
            if cls == "verbatim_recall":
                p = verb_acc
            elif cls == "tail_fact_probe":
                p = tail_acc
            else:
                p = hard_acc
            for i in range(n_per):
                correct = rng.random() < p
                helped = cls in ("compositional_multihop", "abstraction_only")
                ar.per_query.append(QueryResult(
                    qid=f"{cls}-{split}-{i}",
                    qclass=cls,
                    correct=correct,
                    synth_in_topk=(rng.random() < synth_helped_hit) if helped else False,
                    synth_helped=helped,
                    split=split,
                ))
    return ar


def main() -> int:
    lock = load_lock()

    # B0 has real, non-trivial hard accuracy so the test is meaningful.
    b0 = _mk("B0", hard_acc=0.40, verb_acc=0.99, tail_acc=0.85,
             synth_helped_hit=0.0, seed=1)
    # FULL is stubbed to EQUAL B0 (the mandated falsification condition):
    # copy B0's per-query verbatim.
    full = ArmResults(arm="FULL", per_query=list(b0.per_query))

    arms = {
        "B0": b0,
        "B1": _mk("B1", hard_acc=0.42, verb_acc=0.99, tail_acc=0.85,
                  synth_helped_hit=0.0, seed=2),
        "B2": _mk("B2", hard_acc=0.38, verb_acc=0.99, tail_acc=0.80,
                  synth_helped_hit=0.0, seed=3),
        "B3": _mk("B3", hard_acc=0.44, verb_acc=0.99, tail_acc=0.85,
                  synth_helped_hit=0.0, seed=4),
        "L1": _mk("L1", hard_acc=0.40, verb_acc=0.99, tail_acc=0.85,
                  synth_helped_hit=0.0, seed=5),
        "L2": _mk("L2", hard_acc=0.40, verb_acc=0.99, tail_acc=0.85,
                  synth_helped_hit=0.0, seed=6),
        "L3": _mk("L3", hard_acc=0.40, verb_acc=0.99, tail_acc=0.85,
                  synth_helped_hit=0.0, seed=7),
        "FULL": full,
    }

    outcomes, verdict = compute_gates(lock, arms, judge_kappa=1.0)

    print("=" * 68)
    print("GATE-FIRST FALSIFICATION SELF-TEST  (FULL := B0)")
    print("=" * 68)
    for g in outcomes:
        flag = "PASS" if g.passed else ("FAIL-KILL" if g.kill else "FAIL")
        print(f"  [{flag:9}] {g.gate} {g.name}")
        print(f"             {g.detail}")
    print("-" * 68)
    print(f"  VERDICT: {verdict}")
    print("-" * 68)

    g1 = next(g for g in outcomes if g.gate == "G1")
    if verdict.startswith("REJECT") and not g1.passed and "G1" in verdict:
        print("\n  [OK] Harness is ADMISSIBLE: with FULL==B0 it emits "
              "[KILL: G1].\n       The feature can lose. Proceeding is "
              "permitted.")
        return 0
    print("\n  [BROKEN HARNESS] FULL==B0 did NOT trigger [KILL: G1]. "
          "Any later 'pass' from this harness is INADMISSIBLE per the "
          "lock. Fix the harness before writing any feature code.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
