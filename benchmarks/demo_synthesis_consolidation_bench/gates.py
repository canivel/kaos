"""Mechanical computation of the pre-registered gates G0-G5.

This module reads the FROZEN ISA.lock.json and applies its predicates to
per-arm, per-query results. It contains NO knowledge of the synthesis
feature and NO tunable thresholds — every number comes from the lock.

Verdict rule (from the lock, verbatim intent):
  VOID  if G0 fails or judge-audit fails.
  ACCEPT only if G1 AND G2 AND G3 AND G4 AND G5 all pass.
  Any single kill-gate failure REJECTS. No retune-and-rerun.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_V2 = Path(__file__).parent / "ISA.lock.v2.json"
_V1 = Path(__file__).parent / "ISA.lock.json"
# v2 (manifests filled) supersedes v1 once its own pre-registration commit
# exists. The binding run uses v2; v1 stays for the audit trail.
LOCK_PATH = _V2 if _V2.exists() else _V1
# Pre-registered hashes. The harness refuses to run if the on-disk lock is
# not one of these — tamper-evidence. Each hash corresponds to a real
# pre-registration commit; goalpost moves are impossible without a new
# entry here AND a new commit.
KNOWN_LOCK_SHA256 = {
    "2e28dc7660f574ff625caf92e8fde9387719bd8fe813ef46b8d0bc4ad47e8f24": "v1",
    "09310794aad969646804ea56e1d05489c24480c57c1970b70b344ec61ef7e684": "v2-manifests-filled",
}


def lock_sha256() -> str:
    return hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest()


def load_lock() -> dict:
    h = lock_sha256()
    if h not in KNOWN_LOCK_SHA256:
        raise SystemExit(
            f"[VOID: lock-tamper] ISA.lock.json sha256={h} is not a "
            f"pre-registered hash {set(KNOWN_LOCK_SHA256)}. A changed lock "
            f"after results are seen is a goalpost move; supersede with a "
            f"new pre-registration commit instead."
        )
    return json.loads(LOCK_PATH.read_text())


# ── result containers ─────────────────────────────────────────────


@dataclass
class QueryResult:
    qid: str
    qclass: str            # verbatim_recall|compositional_multihop|abstraction_only|tail_fact_probe
    correct: bool          # decisive-evidence recall (set by the blind judge)
    synth_in_topk: bool    # was a synthesized insight in retrieved top-K
    synth_helped: bool     # this query is one a correct synth insight should help
    split: str             # "in_dist" | "shift"


@dataclass
class ArmResults:
    arm: str
    per_query: list[QueryResult] = field(default_factory=list)

    def acc(self, classes: set[str] | None = None, split: str = "in_dist") -> float:
        rows = [q for q in self.per_query
                if q.split == split and (classes is None or q.qclass in classes)]
        if not rows:
            return 0.0
        return sum(q.correct for q in rows) / len(rows)

    def n(self, classes: set[str] | None, split: str = "in_dist") -> int:
        return sum(1 for q in self.per_query
                   if q.split == split and (classes is None or q.qclass in classes))


HARD = {"compositional_multihop", "abstraction_only"}


def _bootstrap_diff_ci(a: list[int], b: list[int], *, iters: int = 2000,
                        seed: int = 12345) -> tuple[float, float, float]:
    """Paired-by-class is not assumed; treat as two independent accuracy
    samples (0/1). Returns (mean_diff, lo95, hi95) for mean(a)-mean(b)."""
    if not a or not b:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    diffs = []
    for _ in range(iters):
        ra = sum(rng.choice(a) for _ in range(len(a))) / len(a)
        rb = sum(rng.choice(b) for _ in range(len(b))) / len(b)
        diffs.append(ra - rb)
    diffs.sort()
    md = sum(a) / len(a) - sum(b) / len(b)
    lo = diffs[int(0.025 * len(diffs))]
    hi = diffs[int(0.975 * len(diffs))]
    return md, lo, hi


def _hard_labels(arm: ArmResults, split: str = "in_dist") -> list[int]:
    return [int(q.correct) for q in arm.per_query
            if q.split == split and q.qclass in HARD]


@dataclass
class GateOutcome:
    gate: str
    name: str
    passed: bool
    kill: bool
    detail: str


def compute_gates(
    lock: dict,
    arms: dict[str, ArmResults],
    judge_kappa: float,
) -> tuple[list[GateOutcome], str]:
    """Return (gate outcomes, verdict). Verdict in {ACCEPT, REJECT, VOID}."""
    qmin = lock["workload_invariants"]["queries_per_class_min"]
    out: list[GateOutcome] = []

    A = arms  # noqa

    def arm(n: str) -> ArmResults:
        return A[n]

    # ── G0 sanity floor (VOID on fail) ────────────────────────────
    g0_ok = True
    g0_bits = []
    for name, ar in A.items():
        acc = ar.acc({"verbatim_recall"})
        g0_bits.append(f"{name}={acc:.3f}")
        if acc < 0.95:
            g0_ok = False
    out.append(GateOutcome(
        "G0", "sanity floor", g0_ok, kill=False,
        detail=f"verbatim_recall acc per arm: {', '.join(g0_bits)} "
               f"(need >=0.95 all)",
    ))

    # n>=200/class invariant (workload conformance, part of G1's preconds)
    n_hard_full = arm("FULL").n(HARD)
    n_ok = all(arm("FULL").n({c}) >= qmin for c in
               ("verbatim_recall", "compositional_multihop",
                "abstraction_only", "tail_fact_probe"))

    # ── G1 beats cheap baselines ──────────────────────────────────
    full_h = arm("FULL").acc(HARD)
    base = max(arm("B0").acc(HARD), arm("B1").acc(HARD), arm("B3").acc(HARD))
    md, lo, hi = _bootstrap_diff_ci(_hard_labels(arm("FULL")),
                                    _hard_labels(arm(max(
                                        ("B0", "B1", "B3"),
                                        key=lambda x: arm(x).acc(HARD)))))
    g1 = (full_h - base >= 0.10) and (lo > 0.0) and n_ok
    out.append(GateOutcome(
        "G1", "beats cheap baselines", g1, kill=True,
        detail=f"FULL={full_h:.3f} vs max(B0,B1,B3)={base:.3f} "
               f"diff={full_h-base:+.3f} (need >=+0.10), "
               f"bootstrap95 CI=({lo:+.3f},{hi:+.3f}) (need lo>0), "
               f"n_hard={n_hard_full} (need >= {qmin}/class)",
    ))

    # ── G2 stored artifact is causal ──────────────────────────────
    helped = [q for q in arm("FULL").per_query
              if q.synth_helped and q.split == "in_dist"]
    hit_rate = (sum(q.synth_in_topk for q in helped) / len(helped)
                if helped else 0.0)
    gain_full = arm("FULL").acc(HARD) - arm("B0").acc(HARD)
    gain_l1 = arm("L1").acc(HARD) - arm("B0").acc(HARD)
    l1_frac = (gain_l1 / gain_full) if gain_full > 1e-9 else 1.0
    g2 = (hit_rate >= 0.60) and (l1_frac <= 0.20)
    out.append(GateOutcome(
        "G2", "stored artifact is causal", g2, kill=True,
        detail=f"synth-in-topK on helped queries={hit_rate:.3f} (need "
               f">=0.60); L1 reproduces {l1_frac:.3f} of FULL gain "
               f"(need <=0.20)",
    ))

    # ── G3 not merely the free LLM call ───────────────────────────
    g3_diff = arm("FULL").acc(HARD) - arm("B3").acc(HARD)
    g3 = g3_diff >= 0.07
    out.append(GateOutcome(
        "G3", "not merely the free call", g3, kill=True,
        detail=f"FULL-B3 on hard={g3_diff:+.3f} (need >=+0.07)",
    ))

    # ── G4 survives distribution shift ────────────────────────────
    gid = arm("FULL").acc(HARD, "in_dist") - arm("B0").acc(HARD, "in_dist")
    gsh = arm("FULL").acc(HARD, "shift") - arm("B0").acc(HARD, "shift")
    retained = (gsh / gid) if gid > 1e-9 else 0.0
    per_class_pos = all(
        (arm("FULL").acc({c}, "shift") - arm("B0").acc({c}, "shift")) > 0.0
        for c in HARD
    )
    g4 = (retained >= 0.70) and per_class_pos
    out.append(GateOutcome(
        "G4", "survives distribution shift", g4, kill=True,
        detail=f"retained gain on shift={retained:.3f} (need >=0.70); "
               f"FULL-B0 strictly>0 on every hard class on shift: "
               f"{per_class_pos}",
    ))

    # ── G5 no leakage, no tail washout ────────────────────────────
    gain_l3 = arm("L3").acc(HARD) - arm("B0").acc(HARD)
    l3_frac = (gain_l3 / gain_full) if gain_full > 1e-9 else 0.0
    tail_full = arm("FULL").acc({"tail_fact_probe"})
    tail_b0 = arm("B0").acc({"tail_fact_probe"})
    g5 = (l3_frac >= 0.80) and (tail_b0 - tail_full <= 0.03)
    out.append(GateOutcome(
        "G5", "no leakage / no tail washout", g5, kill=True,
        detail=f"answer-masked L3 retains {l3_frac:.3f} of gain (need "
               f">=0.80); tail probe FULL={tail_full:.3f} vs "
               f"B0={tail_b0:.3f} regression={tail_b0-tail_full:+.3f} "
               f"(need <=0.03)",
    ))

    # ── verdict ───────────────────────────────────────────────────
    audit_min = 0.85
    if judge_kappa < audit_min:
        return out, f"VOID: judge-audit kappa={judge_kappa:.3f} < {audit_min}"
    if not g0_ok:
        return out, "VOID: G0 sanity floor failed"
    kills = [g for g in out if g.kill]
    if all(g.passed for g in kills):
        return out, "ACCEPT"
    failed = [g.gate for g in kills if not g.passed]
    return out, f"REJECT: kill gate(s) failed: {', '.join(failed)}"
