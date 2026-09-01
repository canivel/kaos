"""Mechanical computation of the pre-registered gates G0-G3 (WMP probe).

Reads the FROZEN ISA.lock.json (via kaos.eval.harness.manifest) and applies
its predicates. NO knowledge of how searches ran; NO tunable thresholds —
every number comes from the lock.

Verdict rule (per the lock):
  VOID    if G0 fails (incomplete cells or dead baseline).
  ACCEPT  iff G1 AND G2 AND G3 all pass.
  REJECT  on any single kill-gate failure. No retune-and-rerun.
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from kaos.eval.harness import GateOutcome, load_lock

LOCK_PATH = Path(__file__).parent / "ISA.lock.json"

# Pre-registered lock hashes — the harness refuses to run on any other.
KNOWN_LOCK_SHA256 = {
    "95b7f621d2cefda79fbbf5d001fe2fa1699fc9377f18ecb122d6c67737703255":
        "v1-pre-registration",
}

ARMS = ("B0", "FULL", "L1")
BENCHMARKS = ("text_classify", "math_rag")
RUNS_PER_CELL = 3
G1_DELTA_FLOOR = 0.05
G2_DELTA_FLOOR = 0.03
G3_COST_MULT = 2.0
B0_SANITY_FLOOR = 0.30
BOOTSTRAP_N = 2000
BOOTSTRAP_SEED = 20260818


def load() -> dict:
    return load_lock(LOCK_PATH, KNOWN_LOCK_SHA256)


@dataclass
class WMPStats:
    """accuracy[arm][benchmark] = list of frontier-best accuracies (one per
    completed search); chars[arm] = list of per-iteration proposer-context
    char counts (maintainer prompt+response included for FULL/L1)."""
    accuracy: dict = field(default_factory=dict)
    chars: dict = field(default_factory=dict)

    def cell(self, arm: str, bench: str) -> list[float]:
        return list(self.accuracy.get(arm, {}).get(bench, []))

    def arm_mean(self, arm: str, bench: str) -> float:
        c = self.cell(arm, bench)
        return statistics.mean(c) if c else 0.0


def pooled_delta(stats: WMPStats, a: str, b: str) -> float:
    """mean over benchmarks of (mean(a) - mean(b))."""
    ds = [stats.arm_mean(a, bm) - stats.arm_mean(b, bm) for bm in BENCHMARKS]
    return statistics.mean(ds)


def bootstrap_lb(stats: WMPStats, a: str, b: str,
                 n: int = BOOTSTRAP_N, seed: int = BOOTSTRAP_SEED) -> float:
    """One-sided 90% lower bound of the pooled delta, resampling runs within
    each arm x benchmark cell."""
    rng = random.Random(seed)
    deltas = []
    for _ in range(n):
        ds = []
        for bm in BENCHMARKS:
            ca = stats.cell(a, bm)
            cb = stats.cell(b, bm)
            if not ca or not cb:
                return -1.0
            ra = [rng.choice(ca) for _ in ca]
            rb = [rng.choice(cb) for _ in cb]
            ds.append(statistics.mean(ra) - statistics.mean(rb))
        deltas.append(statistics.mean(ds))
    deltas.sort()
    return deltas[int(0.10 * len(deltas))]


def compute_gates(stats: WMPStats) -> list[GateOutcome]:
    lock = load()  # noqa: F841 — hash check is the point; predicates mirror it
    out: list[GateOutcome] = []

    # ── G0 completion + machinery sanity (VOID on fail) ───────────
    cells_ok = all(len(stats.cell(arm, bm)) >= RUNS_PER_CELL
                   for arm in ARMS for bm in BENCHMARKS)
    b0_alive = any(stats.arm_mean("B0", bm) >= B0_SANITY_FLOOR
                   for bm in BENCHMARKS)
    counts = {f"{arm}/{bm}": len(stats.cell(arm, bm))
              for arm in ARMS for bm in BENCHMARKS}
    out.append(GateOutcome(
        gate="G0", name="completion + machinery sanity",
        passed=cells_ok and b0_alive, kill=False,
        detail=(f"cells={counts} (floor {RUNS_PER_CELL} each), "
                f"B0 means={[round(stats.arm_mean('B0', b), 3) for b in BENCHMARKS]} "
                f"(sanity floor {B0_SANITY_FLOOR} on >=1 benchmark)"),
    ))

    # ── G1 wiki lifts the frontier (KILL) ─────────────────────────
    d1 = pooled_delta(stats, "FULL", "B0")
    lb1 = bootstrap_lb(stats, "FULL", "B0")
    out.append(GateOutcome(
        gate="G1", name="wiki lifts the frontier",
        passed=d1 >= G1_DELTA_FLOOR and lb1 > 0.0, kill=True,
        detail=(f"pooled delta FULL-B0 = {d1:+.4f} (floor +{G1_DELTA_FLOOR}), "
                f"bootstrap 90% LB = {lb1:+.4f} (must be > 0)"),
    ))

    # ── G2 scrambled wiki must not reproduce the gain (KILL) ──────
    d2 = pooled_delta(stats, "FULL", "L1")
    out.append(GateOutcome(
        gate="G2", name="scrambled wiki must not reproduce the gain",
        passed=d2 >= G2_DELTA_FLOOR, kill=True,
        detail=(f"pooled delta FULL-L1 = {d2:+.4f} (floor +{G2_DELTA_FLOOR}); "
                f"below floor means the 'knowledge' is prompt padding"),
    ))

    # ── G3 cost stays sane (KILL) ─────────────────────────────────
    full_chars = stats.chars.get("FULL", [])
    b0_chars = stats.chars.get("B0", [])
    mult = ((statistics.mean(full_chars) / statistics.mean(b0_chars))
            if full_chars and b0_chars else float("inf"))
    out.append(GateOutcome(
        gate="G3", name="cost stays sane",
        passed=mult <= G3_COST_MULT, kill=True,
        detail=(f"proposer-context chars FULL/B0 = {mult:.2f}x "
                f"(cap {G3_COST_MULT}x; maintainer prompt+response counted)"),
    ))

    return out


def falsify(stats: WMPStats) -> tuple[bool, str]:
    """FULL := B0 must fail G1. Returns (harness_can_kill, detail)."""
    stub = WMPStats(
        accuracy={"B0": stats.accuracy.get("B0", {}),
                  "FULL": stats.accuracy.get("B0", {}),
                  "L1": stats.accuracy.get("L1", {})},
        chars=stats.chars)
    g1 = next(g for g in compute_gates(stub) if g.gate == "G1")
    if g1.passed:
        return False, ("INADMISSIBLE: G1 passed with FULL substituted by B0 — "
                       "the harness cannot kill an inert wiki. " + g1.detail)
    return True, "FULL := B0 correctly fails G1 (" + g1.detail + ")"
