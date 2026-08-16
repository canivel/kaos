"""Mechanical computation of the pre-registered gates G0-G4 (Attraktor
loop binding probe).

Reads the FROZEN ISA.lock.json (via kaos.eval.harness.manifest) and applies
its predicates. NO knowledge of how episodes were produced; NO tunable
thresholds — every number comes from the lock.

Verdict rule (per the lock):
  VOID    if G0 fails (floors unmet or arm balance drifted).
  ACCEPT  iff G1 AND G2 AND G3 AND G4 all pass.
  REJECT  on any single kill-gate failure. No retune-and-rerun.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path

from kaos.eval.harness import GateOutcome, load_lock

LOCK_PATH = Path(__file__).parent / "ISA.lock.json"

# Pre-registered lock hashes — the harness refuses to run on any other.
# A change to the lock requires a new entry here AND a new commit.
KNOWN_LOCK_SHA256 = {
    "4de65deec006d0f4f6815960b790279ce657e655615e687b5a1bd21b2032135e":
        "v1-pre-registration",
}

# Lock-bound constants (mirrors of the frozen lock; the hash check is the
# authority — these exist so predicates below are grep-able).
Z_ONE_SIDED_90 = 1.2815515655446004
FLOOR_ON = 30
FLOOR_OFF = 30
FLOOR_SCRAMBLED = 10
FLOOR_PULLS = 75
LATENCY_P95_MS = 150.0
MATCH_RATE_FLOOR = 0.20
ARM_RATES = {"on": 0.45, "off": 0.45, "scrambled": 0.10}
ARM_BALANCE_TOL = 0.15


def load() -> dict:
    return load_lock(LOCK_PATH, KNOWN_LOCK_SHA256)


@dataclass
class LoopStats:
    """Everything the gates consume, read mechanically from bench.db."""
    outcomes: dict[str, list[int]] = field(default_factory=dict)  # arm -> 0/1 per episode
    latencies_ms: list[float] = field(default_factory=list)       # arm-assigned pulls
    n_pulls: int = 0                                              # arm-assigned pulls
    n_matched_pulls: int = 0                                      # >=1 served/shadow

    def n(self, arm: str) -> int:
        return len(self.outcomes.get(arm, ()))

    def wins(self, arm: str) -> int:
        return sum(self.outcomes.get(arm, ()))

    def rate(self, arm: str) -> float:
        n = self.n(arm)
        return self.wins(arm) / n if n else 0.0


def _wilson_bounds(s: int, n: int, z: float = Z_ONE_SIDED_90) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = s / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom), min(1.0, (centre + margin) / denom)


def newcombe_diff_lb(s1: int, n1: int, s2: int, n2: int,
                     z: float = Z_ONE_SIDED_90) -> float:
    """One-sided 90% lower bound of (p1 - p2), Newcombe square-and-add."""
    if n1 == 0 or n2 == 0:
        return -1.0
    p1, p2 = s1 / n1, s2 / n2
    l1, _ = _wilson_bounds(s1, n1, z)
    _, u2 = _wilson_bounds(s2, n2, z)
    return (p1 - p2) - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)


def p95(values: list[float]) -> float:
    if not values:
        return float("inf")
    v = sorted(values)
    return v[max(0, math.ceil(0.95 * len(v)) - 1)]


def compute_gates(stats: LoopStats) -> list[GateOutcome]:
    """Return the gate-outcome list. Verdict is computed by
    kaos.eval.harness.verdict.compute_verdict over this list."""
    lock = load()  # noqa: F841 — hash check is the point; predicates mirror it
    out: list[GateOutcome] = []

    n_on, n_off, n_scr = stats.n("on"), stats.n("off"), stats.n("scrambled")

    # ── G0 floors + arm balance (VOID on fail) ────────────────────
    floors_ok = (n_on >= FLOOR_ON and n_off >= FLOOR_OFF
                 and n_scr >= FLOOR_SCRAMBLED and stats.n_pulls >= FLOOR_PULLS)
    n_eps = n_on + n_off + n_scr
    balance_ok = True
    shares = {}
    if n_eps > 0:
        for arm, rate in ARM_RATES.items():
            share = stats.n(arm) / n_eps
            shares[arm] = round(share, 3)
            if abs(share - rate) > ARM_BALANCE_TOL:
                balance_ok = False
    out.append(GateOutcome(
        gate="G0", name="floors + arm-balance sanity",
        passed=floors_ok and balance_ok, kill=False,
        detail=(f"on={n_on}/{FLOOR_ON}, off={n_off}/{FLOOR_OFF}, "
                f"scrambled={n_scr}/{FLOOR_SCRAMBLED}, "
                f"pulls={stats.n_pulls}/{FLOOR_PULLS}, shares={shares} "
                f"(tol ±{ARM_BALANCE_TOL} of {ARM_RATES})"),
    ))

    # ── G1 brain-on beats brain-off (KILL) ────────────────────────
    g1_lb = newcombe_diff_lb(stats.wins("on"), n_on, stats.wins("off"), n_off)
    out.append(GateOutcome(
        gate="G1", name="brain-on beats brain-off", passed=g1_lb > 0.0, kill=True,
        detail=(f"p_on={stats.rate('on'):.3f} (n={n_on}), "
                f"p_off={stats.rate('off'):.3f} (n={n_off}), "
                f"Newcombe 90% LB of diff={g1_lb:+.4f} (must be > 0)"),
    ))

    # ── G2 pull latency hot-path budget (KILL) ────────────────────
    lat_p95 = p95(stats.latencies_ms)
    out.append(GateOutcome(
        gate="G2", name="pull latency hot-path budget",
        passed=lat_p95 < LATENCY_P95_MS and len(stats.latencies_ms) >= FLOOR_PULLS,
        kill=True,
        detail=(f"p95={lat_p95:.1f}ms over n={len(stats.latencies_ms)} pulls "
                f"(budget {LATENCY_P95_MS}ms, floor n={FLOOR_PULLS})"),
    ))

    # ── G3 match-rate floor, D1 (KILL) ────────────────────────────
    match_rate = stats.n_matched_pulls / stats.n_pulls if stats.n_pulls else 0.0
    out.append(GateOutcome(
        gate="G3", name="match-rate floor (D1)",
        passed=match_rate >= MATCH_RATE_FLOOR, kill=True,
        detail=(f"matched={stats.n_matched_pulls}/{stats.n_pulls} = "
                f"{match_rate:.3f} (floor {MATCH_RATE_FLOOR})"),
    ))

    # ── G4 scrambled placebo falsification (KILL) ─────────────────
    g4_lb = newcombe_diff_lb(stats.wins("scrambled"), n_scr, stats.wins("off"), n_off)
    out.append(GateOutcome(
        gate="G4", name="scrambled placebo falsification",
        passed=g4_lb <= 0.0, kill=True,
        detail=(f"p_scrambled={stats.rate('scrambled'):.3f} (n={n_scr}), "
                f"p_off={stats.rate('off'):.3f}, Newcombe 90% LB of diff="
                f"{g4_lb:+.4f} (KILL if > 0: padding reproduces the 'gain')"),
    ))

    return out
