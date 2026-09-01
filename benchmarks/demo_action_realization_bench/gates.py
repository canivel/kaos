"""Mechanical computation of the pre-registered gates G0-G4.

Reads the FROZEN ISA.lock.json (via kaos.eval.harness.manifest) and
applies its predicates. NO knowledge of arm internals; NO tunable
thresholds — every number comes from the lock.

Verdict rule (per the lock):
  VOID    if G0 fails, judge-audit kappa < 0.85, or n minima unmet.
  ACCEPT  iff G1 AND G2 AND G3 AND G4 all pass.
  REJECT  on any single kill-gate failure. No retune.
"""

from __future__ import annotations

import statistics
from pathlib import Path

from kaos.eval.harness import (
    ArmResults,
    GateOutcome,
    bootstrap_diff_ci,
    load_lock,
)

LOCK_PATH = Path(__file__).parent / "ISA.lock.json"

# Pre-registered lock hashes — the harness refuses to run on any
# other. A change to the lock requires a new entry here AND a new
# pre-registration commit.
KNOWN_LOCK_SHA256 = {
    "3ca89983c5914d1f1f77377cf124bac223dba4bc391a59d5e329e671b79187e2":
        "v1-pre-registration",
}


def load() -> dict:
    return load_lock(LOCK_PATH, KNOWN_LOCK_SHA256)


def compute_gates(
    arms: dict[str, ArmResults],
    *,
    inline_overhead_us_by_arm: dict[str, list[float]],
) -> list[GateOutcome]:
    """Return the gate-outcome list. Verdict is computed by
    kaos.eval.harness.verdict.compute_verdict over this list."""
    lock = load()
    out: list[GateOutcome] = []

    # ── G0 sanity floor (VOID on fail) ────────────────────────────
    g0_bits: list[str] = []
    g0_ok = True
    for name, ar in arms.items():
        acc = ar.acc({"sanity"})
        g0_bits.append(f"{name}={acc:.3f}")
        if acc < 0.95:
            g0_ok = False
    out.append(GateOutcome(
        gate="G0", name="sanity floor", passed=g0_ok, kill=False,
        detail=f"sanity-slice completion per arm: {', '.join(g0_bits)} "
               f"(need >=0.95 each)",
    ))

    def a(name: str) -> ArmResults:
        return arms[name]

    # ── G1: FULL beats v0.8.3 native (B1) on action-class ─────────
    full_a = a("FULL").labels({"action"})
    b1_a = a("B1").labels({"action"})
    n_action = a("FULL").n({"action"})
    md, lo, hi = bootstrap_diff_ci(full_a, b1_a, iters=2000)
    g1_thresh = float(lock["kill_gates"]["G1"]["threshold_pp"]) / 100.0
    g1_n_ok = n_action >= int(
        lock["workload_invariants"]["action_class_slice"]["n_min"])
    g1 = (md >= g1_thresh) and (lo > 0.0) and g1_n_ok
    out.append(GateOutcome(
        gate="G1", name="beats v0.8.3 native baseline", passed=g1,
        kill=True,
        detail=(
            f"FULL-B1 on action={md:+.3f} (need >=+{g1_thresh:.3f}), "
            f"bootstrap95 CI=({lo:+.3f},{hi:+.3f}) (need lo>0), "
            f"n_action={n_action} (need >= "
            f"{lock['workload_invariants']['action_class_slice']['n_min']})"
        ),
    ))

    # ── G2: causal isolation via lesions ──────────────────────────
    diff_l1 = a("FULL").acc({"action"}) - a("L1").acc({"action"})
    diff_l2 = a("FULL").acc({"action"}) - a("L2").acc({"action"})
    t_l1 = float(lock["kill_gates"]["G2"]["threshold_vs_l1_pp"]) / 100.0
    t_l2 = float(lock["kill_gates"]["G2"]["threshold_vs_l2_pp"]) / 100.0
    g2 = (diff_l1 >= t_l1) and (diff_l2 >= t_l2)
    out.append(GateOutcome(
        gate="G2", name="causal isolation via lesions", passed=g2,
        kill=True,
        detail=(
            f"FULL-L1={diff_l1:+.3f} (need >=+{t_l1:.3f}); "
            f"FULL-L2={diff_l2:+.3f} (need >=+{t_l2:.3f})"
        ),
    ))

    # ── G3: no regression on non-action control slice ─────────────
    full_c = a("FULL").acc({"non_action"})
    b1_c = a("B1").acc({"non_action"})
    g3_max_reg = float(lock["kill_gates"]["G3"]["max_regression_pp"]) / 100.0
    diff_c = full_c - b1_c
    g3 = diff_c >= -g3_max_reg
    out.append(GateOutcome(
        gate="G3", name="no regression on control slice", passed=g3,
        kill=True,
        detail=(
            f"FULL-B1 on non-action={diff_c:+.3f} (need >=-{g3_max_reg:.3f})"
        ),
    ))

    # ── G4: inline overhead p95 < budget ──────────────────────────
    full_us = sorted(inline_overhead_us_by_arm.get("FULL", []))
    if full_us:
        idx = int(0.95 * (len(full_us) - 1))
        p95 = full_us[idx]
    else:
        p95 = float("nan")
    budget = float(lock["kill_gates"]["G4"]["budget_us"])
    g4 = (p95 == p95) and (p95 < budget)
    out.append(GateOutcome(
        gate="G4", name="inline overhead within budget", passed=g4,
        kill=True,
        detail=f"FULL p95={p95:.1f} us (budget <{budget:.0f} us), "
               f"n_calls={len(full_us)}",
    ))

    return out
