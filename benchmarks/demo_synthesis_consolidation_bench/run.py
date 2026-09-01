"""Binding evaluation run for synthesis-as-consolidation.

Order is fixed by the lock. The exit code / printed verdict is BINDING:
ACCEPT, REJECT, or VOID — reported faithfully whatever it is. No
retune-and-rerun.
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

from gates import ArmResults, compute_gates, load_lock, lock_sha256
from judge import JudgedQuery, judge_arm
from queries import build_queries
from workload import build_workload
import arms as arms_mod

SEED = 20260516
ARMS = ["B0", "B1", "B2", "B3", "L1", "L2", "L3", "FULL"]
CACHE_DIR = HERE / ".synth_cache"


def main() -> int:
    lock = load_lock()
    print("=" * 70)
    print("SYNTHESIS-AS-CONSOLIDATION — BINDING EVALUATION")
    print(f"lock sha256 = {lock_sha256()}  (pre-registered)")
    print("=" * 70)

    # 1. Build the organic workload once.
    base_db = str(HERE / "_base.db")
    print("\n[1] building organic workload (real KAOS, genuine "
          "co-retrieval)...")
    idx = build_workload(base_db, SEED, days=90, incidents_per_day=6)
    print(f"    {len(idx.incidents)} incidents -> {len(idx.mem_text)} "
          f"memories")

    # 2. Fork one DB per arm.
    db_paths = {}
    for a in ARMS:
        p = str(HERE / f"_arm_{a}.db")
        shutil.copyfile(base_db, p)
        db_paths[a] = p

    # 3. Run the REAL synthesis feature into the synth arms (cluster-blind
    #    claude CLI, disk-cached).
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / "cache.json"
    cache = json.loads(cache_file.read_text()) if cache_file.exists() else {}
    print("\n[2] running synthesis into FULL/L1/L2/L3 (real claude CLI, "
          f"{len(cache)} cached)...")
    arms_mod.prepare_synthesis_arms(db_paths, cache)
    cache_file.write_text(json.dumps(cache))
    print(f"    synthesized {len(cache)} cluster insights "
          f"(cache now {len(cache)})")

    # 4. Build held-out queries (synthesis-blind generator).
    queries = build_queries(idx)
    print(f"\n[3] {len(queries)} held-out queries "
          f"(>=220/class/split)")

    # 5. Retrieve + judge per arm (blind).
    arm_results: dict[str, ArmResults] = {}
    kappas = []
    print("\n[4] retrieving + blind-judging per arm...")
    for a in ARMS:
        retr = arms_mod.retrieve_all(a, db_paths[a], queries)
        judged = []
        for q, r in zip(queries, retr):
            correct = q.decisive(r.texts)
            judged.append(JudgedQuery(
                qid=q.qid, qclass=q.qclass, split=q.split,
                decisive=frozenset([q.qid]),    # opaque token to judge
                retrieved=frozenset([q.qid]) if correct else frozenset(),
                synth_in_topk=r.any_synth,
                synth_helped=q.synth_helped,
            ))
        results, kappa = judge_arm(a, judged)
        kappas.append(kappa)
        ar = ArmResults(arm=a, per_query=results)
        arm_results[a] = ar
        print(f"    {a:4} hard_acc(in_dist)="
              f"{ar.acc({'compositional_multihop','abstraction_only'}):.3f}"
              f"  verbatim={ar.acc({'verbatim_recall'}):.3f}"
              f"  kappa={kappa:.3f}")

    judge_kappa = min(kappas) if kappas else 1.0

    # 6. Gates + binding verdict.
    outcomes, verdict = compute_gates(lock, arm_results, judge_kappa)
    print("\n" + "=" * 70)
    print("GATES")
    print("=" * 70)
    for g in outcomes:
        flag = "PASS" if g.passed else ("FAIL-KILL" if g.kill else "FAIL/VOID")
        print(f"  [{flag:9}] {g.gate} {g.name}")
        print(f"             {g.detail}")
    print("-" * 70)
    print(f"  BINDING VERDICT: {verdict}")
    print("-" * 70)

    out = {
        "lock_sha256": lock_sha256(),
        "seed": SEED,
        "judge_kappa": judge_kappa,
        "verdict": verdict,
        "arms": {a: {
            "hard_in_dist": arm_results[a].acc(
                {"compositional_multihop", "abstraction_only"}),
            "hard_shift": arm_results[a].acc(
                {"compositional_multihop", "abstraction_only"}, "shift"),
            "verbatim": arm_results[a].acc({"verbatim_recall"}),
            "tail": arm_results[a].acc({"tail_fact_probe"}),
        } for a in ARMS},
        "gates": [{"gate": g.gate, "name": g.name, "passed": g.passed,
                   "kill": g.kill, "detail": g.detail} for g in outcomes],
    }
    (HERE / "results.json").write_text(json.dumps(out, indent=2))

    if verdict == "ACCEPT":
        return 0
    # REJECT and VOID are both non-zero: the feature did not earn the word
    # "works". Per the lock this is the expected, successful outcome of a
    # falsifiable evaluation — not a failure of the evaluation.
    return 2 if verdict.startswith("VOID") else 1


if __name__ == "__main__":
    sys.exit(main())
