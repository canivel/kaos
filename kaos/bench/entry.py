"""E1 — validate-on-entry, the telemetry-proven rung of the ladder (Filter 1).

PLAN v2 §3.1: six conditions, ALL required, constants lock-bound
(admission.lock.json v1). Pure SQL/arithmetic — zero model calls; E1 runs at
harvest time.

A5 (counterfactual lift) is the load-bearing condition (R3): Wilson-over-uses
alone measures "succeeds when used" — SWE-Skills-Bench's 39 zero-gain skills pass
that forever. Only the stratified exposed-vs-unexposed lift kills them. Cost
honesty, by design: at n≈10/arm this detects only LARGE lifts; small effects stay
E0 accumulating organic n — the bench is a library of large proven wins, because
small effects aren't worth cross-agent transfer risk.

A6: graded quality can only DOWNGRADE a binary pass, never rescue a fail.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ── Lock-bound constants (admission.lock.json v1) ──
E1_MIN_USES = 10                 # A1
E1_MIN_AGENTS = 2                # A2
E1_MIN_BUCKETS = 3               # A2
E1_WILSON_FLOOR = 0.60           # A4
E1_MIN_PER_ARM = 8               # A5 pooled per arm
E1_MIN_LIFT_BUCKETS = 2          # A5 buckets contributing both arms
_Z_ONE_SIDED_90 = 1.2815515655446004

ADMISSIBLE_SOURCES = frozenset(   # A3 — self-report is not on this list, on purpose
    {"episode_status", "blind_judge", "test_suite", "human"})


@dataclass
class TelemetryRow:
    """One counted use (exposed) or comparable non-use (unexposed) observation."""
    agent_id: str
    task_hash: str
    success: bool
    outcome_source: str
    quality: float | None = None   # optional graded outcome in [0,1]


@dataclass
class E1Result:
    passed: bool
    floors_met: bool                                # False = still E0 (accumulating), not a dud
    conditions: dict = field(default_factory=dict)  # A1..A6 -> {passed, detail}
    reason: str = ""                                # human-readable why (on fail)

    def to_dict(self) -> dict:
        return {"passed": self.passed, "floors_met": self.floors_met,
                "conditions": self.conditions, "reason": self.reason}


def wilson_lower_bound(successes: int, n: int, z: float = _Z_ONE_SIDED_90) -> float:
    """One-sided Wilson score lower bound (default 90%)."""
    if n == 0:
        return 0.0
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, (centre - margin) / denom)


def _wilson_upper_bound(successes: int, n: int, z: float = _Z_ONE_SIDED_90) -> float:
    if n == 0:
        return 1.0
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return min(1.0, (centre + margin) / denom)


def counterfactual_lift_lb(
    exposed: list[TelemetryRow], unexposed: list[TelemetryRow],
) -> tuple[float | None, dict]:
    """A5: Mantel-Haenszel stratified risk difference (exposed − unexposed) over
    task_hash buckets, with a Newcombe-style one-sided 90% lower bound.

    Approximation, documented: the point estimate is the MH-weighted difference
    over buckets containing both arms; the bound applies the Newcombe
    square-and-add construction to the POOLED arm proportions, centered on the
    MH estimate. Conservative for the large lifts E1 is designed to detect.

    Returns (lower_bound | None, detail). None = not computable (floors unmet).
    """
    buckets: dict[str, list[tuple[int, int, int, int]]] = {}
    per: dict[str, dict[str, list[TelemetryRow]]] = {}
    for r in exposed:
        per.setdefault(r.task_hash, {}).setdefault("e", []).append(r)
    for r in unexposed:
        per.setdefault(r.task_hash, {}).setdefault("u", []).append(r)

    both = {b: d for b, d in per.items() if d.get("e") and d.get("u")}
    n_e = sum(len(d["e"]) for d in both.values())
    n_u = sum(len(d["u"]) for d in both.values())
    detail = {"buckets_with_both_arms": len(both), "pooled_exposed": n_e,
              "pooled_unexposed": n_u}
    if len(both) < E1_MIN_LIFT_BUCKETS or n_e < E1_MIN_PER_ARM or n_u < E1_MIN_PER_ARM:
        return None, detail

    num = den = 0.0
    s_e = s_u = 0
    for d in both.values():
        e, u = d["e"], d["u"]
        ne, nu = len(e), len(u)
        se = sum(r.success for r in e)
        su = sum(r.success for r in u)
        s_e += se
        s_u += su
        w = ne * nu / (ne + nu)          # MH weight
        num += w * (se / ne - su / nu)
        den += w
    rd_mh = num / den

    l1 = wilson_lower_bound(s_e, n_e)
    p1 = s_e / n_e
    u2 = _wilson_upper_bound(s_u, n_u)
    p2 = s_u / n_u
    lb = rd_mh - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    detail.update({"rd_mh": round(rd_mh, 4), "lift_lb": round(lb, 4)})
    return lb, detail


def evaluate_e1(
    exposed: list[TelemetryRow], unexposed: list[TelemetryRow],
) -> E1Result:
    """Apply A1–A6 over the candidate's telemetry. Full reasoning always returned
    (D0.1: the rejection row is the dataset entry)."""
    cond: dict = {}
    failures: list[str] = []

    # A3 holds BY CONSTRUCTION: only admissibly-sourced rows are counted anywhere
    # below. Its bite is the exclusion itself — self-reported rows simply are not
    # evidence, so a skill whose telemetry is all self-report stays at E0 with
    # floors unmet rather than being branded a rejected dud.
    excluded = [r for r in exposed if r.outcome_source not in ADMISSIBLE_SOURCES]
    counted = [r for r in exposed if r.outcome_source in ADMISSIBLE_SOURCES]
    cond["A3"] = {"passed": True,
                  "detail": f"{len(excluded)} inadmissibly-sourced rows excluded "
                            f"(self-report is not evidence); {len(counted)} counted"}
    unexposed = [r for r in unexposed if r.outcome_source in ADMISSIBLE_SOURCES]

    n = len(counted)
    a1 = n >= E1_MIN_USES
    cond["A1"] = {"passed": a1, "detail": f"n={n} (floor {E1_MIN_USES})"}
    if not a1:
        failures.append(f"A1: n={n} < {E1_MIN_USES}")

    agents = {r.agent_id for r in counted}
    bkts = {r.task_hash for r in counted}
    a2 = len(agents) >= E1_MIN_AGENTS and len(bkts) >= E1_MIN_BUCKETS
    cond["A2"] = {"passed": a2,
                  "detail": f"{len(agents)} agents (floor {E1_MIN_AGENTS}), "
                            f"{len(bkts)} buckets (floor {E1_MIN_BUCKETS})"}
    if not a2:
        failures.append(f"A2: diversity {len(agents)} agents/{len(bkts)} buckets")

    succ = sum(r.success for r in counted)
    wlb = wilson_lower_bound(succ, n)
    a4 = wlb >= E1_WILSON_FLOOR
    cond["A4"] = {"passed": a4,
                  "detail": f"wilson_lb={wlb:.3f} (floor {E1_WILSON_FLOOR}) over {succ}/{n}"}
    if not a4:
        failures.append(f"A4: wilson_lb {wlb:.3f} < {E1_WILSON_FLOOR}")

    lift_lb, lift_detail = counterfactual_lift_lb(counted, unexposed)
    a5 = lift_lb is not None and lift_lb > 0.0
    cond["A5"] = {"passed": a5, "detail": lift_detail}
    if lift_lb is None:
        failures.append("A5: counterfactual floors unmet "
                        f"({lift_detail['buckets_with_both_arms']} both-arm buckets, "
                        f"{lift_detail['pooled_exposed']}/{lift_detail['pooled_unexposed']} per arm)")
    elif lift_lb <= 0.0:
        failures.append(f"A5: lift lower bound {lift_lb:.3f} <= 0 — no proven counterfactual gain")

    # A6: graded quality can only downgrade. If quality rows exist and the
    # quality-weighted Wilson bound misses the floor, a binary A4 pass is revoked.
    q_rows = [r for r in counted if r.quality is not None]
    a6 = True
    q_detail = "no graded-quality rows"
    if q_rows and a4:
        q_succ = sum(r.quality for r in q_rows)
        q_lb = wilson_lower_bound(int(round(q_succ)), len(q_rows))
        if q_lb < E1_WILSON_FLOOR:
            a6 = False
            q_detail = (f"quality-weighted wilson_lb {q_lb:.3f} < {E1_WILSON_FLOOR} "
                        f"over {len(q_rows)} graded rows — binary pass downgraded")
            failures.append(f"A6: {q_detail}")
        else:
            q_detail = f"quality-weighted wilson_lb {q_lb:.3f} confirms binary pass"
    cond["A6"] = {"passed": a6, "detail": q_detail}

    # Floors: enough admissible evidence to JUDGE at all. Unmet floors = the
    # candidate stays E0 (accumulating organic n), which is not a rejection.
    floors_met = a1 and a2 and lift_lb is not None

    passed = a1 and a2 and a4 and a5 and a6
    return E1Result(passed=passed, floors_met=floors_met, conditions=cond,
                    reason="; ".join(failures) if failures else "all six conditions met")
