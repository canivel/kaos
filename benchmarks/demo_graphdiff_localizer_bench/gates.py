"""Mechanical computation of the pre-registered gates G0-G4 (GDL probe).

Reads the FROZEN ISA.lock.json (via kaos.eval.harness.manifest) and
applies its predicates. NO knowledge of arm internals; NO tunable
thresholds — every number comes from the lock.

Verdict rule (per the lock):
  VOID    if G0 fails OR organic slice n < 30 agents OR localization
          slice n < 40 (both encoded as non-kill gates below).
  ACCEPT  iff G1 AND G2 AND G3 AND G4 all pass.
  REJECT  on any single kill-gate failure. No retune-and-rerun.
"""

from __future__ import annotations

from pathlib import Path

from kaos.eval.harness import ArmResults, GateOutcome, load_lock

LOCK_PATH = Path(__file__).parent / "ISA.lock.json"

# Pre-registered lock hashes — the harness refuses to run on any
# other. A change to the lock requires a new entry here AND a new
# pre-registration commit.
KNOWN_LOCK_SHA256 = {
    "979127576a1196db60deb78df19d64b49f78118ab8274d1a37d2841554e2232c":
        "v1-pre-registration",
}

ALL_CLASSES = {"silent_wrong_branch", "error_visible"}


def load() -> dict:
    return load_lock(LOCK_PATH, KNOWN_LOCK_SHA256)


def compute_gates(
    arms: dict[str, ArmResults],
    *,
    organic_median_reuse: float,
    organic_n_agents: int,
    pairing_same_family_rate: float,
) -> list[GateOutcome]:
    """Return the gate-outcome list. Verdict is computed by
    kaos.eval.harness.verdict.compute_verdict over this list."""
    lock = load()  # noqa: F841 — hash check is the point; predicates below mirror it
    out: list[GateOutcome] = []

    n_workload = arms["FULL"].n(ALL_CLASSES) if "FULL" in arms else 0

    # ── G0 workload sanity (VOID on fail) ─────────────────────────
    cover_ok = all(a.n(ALL_CLASSES) == n_workload for a in arms.values())
    b0_acc = arms["B0"].acc(ALL_CLASSES) if "B0" in arms else 1.0
    g0_ok = cover_ok and b0_acc <= 0.35 and n_workload > 0
    out.append(GateOutcome(
        gate="G0", name="workload sanity", passed=g0_ok, kill=False,
        detail=(f"coverage_equal={cover_ok}, B0 acc={b0_acc:.3f} "
                f"(must be <= 0.35), n={n_workload}"),
    ))

    # ── G0f pre-registered floors (VOID on fail) ──────────────────
    floors_ok = n_workload >= 40 and organic_n_agents >= 30
    out.append(GateOutcome(
        gate="G0f", name="workload floors", passed=floors_ok, kill=False,
        detail=(f"localization n={n_workload} (floor 40), organic "
                f"agents={organic_n_agents} (floor 30)"),
    ))

    full = arms.get("FULL")
    b1 = arms.get("B1")
    l1 = arms.get("L1")
    full_acc = full.acc(ALL_CLASSES) if full else 0.0
    b1_acc = b1.acc(ALL_CLASSES) if b1 else 1.0
    l1_acc = l1.acc(ALL_CLASSES) if l1 else 1.0

    # ── G1 beats v0.8.3 native localizer (KILL) ───────────────────
    g1_ok = full_acc >= 0.70 and (full_acc - b1_acc) >= 0.10 and n_workload >= 40
    out.append(GateOutcome(
        gate="G1", name="beats v0.8.3 native localizer", passed=g1_ok, kill=True,
        detail=(f"FULL={full_acc:.3f} (floor 0.70), B1={b1_acc:.3f}, "
                f"delta={full_acc - b1_acc:+.3f} (floor +0.10), n={n_workload}"),
    ))

    # ── G2 causal isolation via wrong-pair lesion (KILL) ──────────
    g2_ok = (full_acc - l1_acc) >= 0.10
    out.append(GateOutcome(
        gate="G2", name="causal isolation via wrong-pair lesion",
        passed=g2_ok, kill=True,
        detail=(f"FULL={full_acc:.3f}, L1(wrong-pair)={l1_acc:.3f}, "
                f"delta={full_acc - l1_acc:+.3f} (floor +0.10)"),
    ))

    # ── G3 organic non-degeneracy (KILL) ──────────────────────────
    g3_ok = organic_median_reuse >= 1.30
    out.append(GateOutcome(
        gate="G3", name="organic non-degeneracy", passed=g3_ok, kill=True,
        detail=(f"median node-reuse on organic slice = "
                f"{organic_median_reuse:.3f} (floor 1.30, "
                f"n_agents={organic_n_agents})"),
    ))

    # ── G4 pairing precision (KILL) ───────────────────────────────
    g4_ok = pairing_same_family_rate >= 0.80
    out.append(GateOutcome(
        gate="G4", name="pairing precision", passed=g4_ok, kill=True,
        detail=(f"BM25 top-1 same-family rate = "
                f"{pairing_same_family_rate:.3f} (floor 0.80)"),
    ))

    return out
