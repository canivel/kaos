"""Run the action-realization probe end-to-end.

Reads kaos.db, samples the three slices, executes every incident
through every arm, runs the blind judge, computes the gates, emits
the binding verdict, and writes results.json + records the
ExperimentStore row.

This script is the ONLY production-side artifact of PR-4. The probe
verdict it emits is binding; per the lock, it cannot be re-tuned.
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Make the bench importable as a package even when run as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from kaos.eval.harness import (  # noqa: E402
    ArmResults, QueryResult, compute_verdict, sha256_file,
)
from kaos.eval.harness.judge import JudgedQuery, judge_arm  # noqa: E402

from demo_action_realization_bench.arms import ARMS  # noqa: E402
from demo_action_realization_bench.gates import (  # noqa: E402
    LOCK_PATH, compute_gates, load,
)
from demo_action_realization_bench.workload import sample_workload  # noqa: E402


def _arm_results_for(arm_name: str, calls: list) -> ArmResults:
    """Turn raw per-call results into the harness's ArmResults shape.
    The 'split' field carries our slice label so gate.acc({label})
    filters cleanly."""
    return ArmResults(
        arm=arm_name,
        per_query=[
            QueryResult(
                qid=c.incident_id,
                qclass=c.notes_label,
                correct=bool(c.completed),
                split="in_dist",
            )
            for c in calls
        ],
    )


def main(out_dir: str | Path = "demo_action_realization_bench",
         db_path: str = "kaos.db") -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # ── Lock verification (tamper-evidence) ───────────────────────
    lock_hash = sha256_file(LOCK_PATH)
    lock = load()
    print(f"[lock] ISA.lock.json sha256={lock_hash} (admitted)")

    # ── Workload ──────────────────────────────────────────────────
    wl = sample_workload(db_path)
    print(f"[workload] action={len(wl.action)}  "
          f"control={len(wl.control)}  sanity={len(wl.sanity)}")
    ok_wl, msg = wl.is_sufficient
    if not ok_wl:
        print(f"[VERDICT] {msg}")
        result = {
            "lock_sha256": lock_hash,
            "verdict": msg,
            "judge_kappa": None,
            "arms": {},
            "gates": [],
            "workload": {"action": len(wl.action),
                         "control": len(wl.control),
                         "sanity": len(wl.sanity)},
        }
        (out / "results.json").write_text(json.dumps(result, indent=2))
        return result

    # ── Execute every incident through every arm ──────────────────
    all_incidents = wl.action + wl.control + wl.sanity
    per_arm_calls: dict[str, list] = {a: [] for a in ARMS}
    inline_us: dict[str, list[float]] = {a: [] for a in ARMS}

    t0 = time.perf_counter()
    for arm_name, fn in ARMS.items():
        for inc in all_incidents:
            r = fn(inc)
            # Annotate the slice label so gates.acc({"action"}) filters.
            r.notes_label = inc.label
            per_arm_calls[arm_name].append(r)
            inline_us[arm_name].append(r.inline_overhead_us)
    print(f"[exec] {sum(len(v) for v in per_arm_calls.values())} "
          f"arm-call evaluations in {time.perf_counter()-t0:.1f}s")

    # ── Blind judge per arm (anonymised, shuffled stream) ─────────
    arm_results: dict[str, ArmResults] = {}
    kappa_min_per_arm: list[float] = []
    for arm_name, calls in per_arm_calls.items():
        judged = [
            JudgedQuery(
                qid=c.incident_id, qclass=c.notes_label,
                split="in_dist", correct=c.completed,
            )
            for c in calls
        ]
        qr, kappa = judge_arm(arm_name, judged)
        arm_results[arm_name] = ArmResults(arm=arm_name, per_query=qr)
        kappa_min_per_arm.append(kappa)
    # This probe uses mechanical decisive-evidence labels with no independent
    # second labeler, so judge_arm returns None (kappa-exempt) per arm. Keep it
    # None rather than coercing to 1.0 — compute_verdict skips the kappa gate.
    real_kappas = [k for k in kappa_min_per_arm if k is not None]
    judge_kappa = min(real_kappas) if real_kappas else None

    # ── Gates + verdict ───────────────────────────────────────────
    outcomes = compute_gates(arm_results, inline_overhead_us_by_arm=inline_us)
    verdict = compute_verdict(outcomes, judge_kappa=judge_kappa,
                              kappa_min=0.85)

    # ── Print ─────────────────────────────────────────────────────
    print("=" * 70)
    print("ACTION-REALIZATION PROBE — BINDING VERDICT")
    print("=" * 70)
    for g in outcomes:
        flag = "PASS" if g.passed else ("FAIL-KILL" if g.kill else "FAIL")
        print(f"  [{flag:9}] {g.gate}  {g.name}")
        print(f"             {g.detail}")
    print("-" * 70)
    _kappa_str = "exempt (mechanical label)" if judge_kappa is None else f"{judge_kappa:.3f}"
    print(f"  judge_kappa = {_kappa_str}")
    print(f"  VERDICT     = {verdict}")
    print("-" * 70)

    # ── Persist results.json ──────────────────────────────────────
    result = {
        "lock_sha256": lock_hash,
        "verdict": verdict,
        "judge_kappa": judge_kappa,
        "arms": {
            name: {
                "acc_action": ar.acc({"action"}),
                "acc_non_action": ar.acc({"non_action"}),
                "acc_sanity": ar.acc({"sanity"}),
                "n_action": ar.n({"action"}),
                "n_non_action": ar.n({"non_action"}),
                "n_sanity": ar.n({"sanity"}),
                "p95_us": (sorted(inline_us[name])[int(
                    0.95 * (len(inline_us[name]) - 1))]
                    if inline_us[name] else None),
                # Persist per_query so `kaos eval probe verify` can reconstruct
                # the arms and recompute the verdict against HEAD's gate code.
                "per_query": [
                    {"qid": q.qid, "qclass": q.qclass, "correct": q.correct,
                     "split": q.split, "extras": q.extras}
                    for q in ar.per_query
                ],
            }
            for name, ar in arm_results.items()
        },
        "gates": [
            {"gate": g.gate, "name": g.name, "passed": g.passed,
             "kill": g.kill, "detail": g.detail}
            for g in outcomes
        ],
        "workload": {"action": len(wl.action),
                     "control": len(wl.control),
                     "sanity": len(wl.sanity)},
    }
    (out / "results.json").write_text(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
