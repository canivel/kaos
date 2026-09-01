"""Mechanical computation of the pre-registered gates G0-G5 (PFA probe).

Every threshold comes from the FROZEN ISA.lock.json; the harness refuses
to run on an edited lock (sha256 pinned below).

Verdict rule (per lock): VOID if G0 fails; ACCEPT iff G1..G5 all pass;
any kill-gate failure REJECTS. No retune-and-rerun. Post-run instrument
audit per docs/falsifiable-eval.md @ 3d1b4d5 (all gates, downgrade-only).
"""

from __future__ import annotations

from pathlib import Path

from kaos.eval.harness import GateOutcome, load_lock

LOCK_PATH = Path(__file__).parent / "ISA.lock.json"

KNOWN_LOCK_SHA256 = {
    "4f820f7354a3421a6e763c57fb14430e1696071a75cbd01167b8e12a89c01f2a":
        "v1-pre-registration",
}


def load() -> dict:
    return load_lock(LOCK_PATH, KNOWN_LOCK_SHA256)


def separation(flagged: list[bool], failed: list[bool]) -> float:
    """P(failure | flagged) - P(failure | unflagged); zero flagged -> 0."""
    f_fail = [fa for fl, fa in zip(flagged, failed) if fl]
    u_fail = [fa for fl, fa in zip(flagged, failed) if not fl]
    if not f_fail or not u_fail:
        return 0.0
    return (sum(f_fail) / len(f_fail)) - (sum(u_fail) / len(u_fail))


def compute_gates(
    *,
    n_failure: int,
    n_completed: int,
    parse_ok_rate: float,
    leak_guard_ok: bool,
    full_flagged: list[bool],
    det_flagged: list[bool],
    rand_flagged: list[bool],
    failed: list[bool],
    evidence_resolved_rate: float,
    n_flag_instances: int,
) -> list[GateOutcome]:
    load()  # tamper check
    n = len(failed)
    out: list[GateOutcome] = []

    g0 = (parse_ok_rate >= 0.95 and leak_guard_ok
          and n_failure >= 40 and n_completed >= 80)
    out.append(GateOutcome(
        gate="G0", name="coverage + floors + leak guard", passed=g0, kill=False,
        detail=(f"parse_ok={parse_ok_rate:.3f} (floor 0.95), leak_guard={leak_guard_ok}, "
                f"n_failure={n_failure} (floor 40), n_completed={n_completed} (floor 80)"),
    ))

    sep_full = separation(full_flagged, failed)
    sep_det = separation(det_flagged, failed)
    sep_rand = separation(rand_flagged, failed)

    g1 = sep_full >= 0.15 and n >= 120
    out.append(GateOutcome(
        gate="G1", name="outcome separation", passed=g1, kill=True,
        detail=f"FULL separation={sep_full:+.3f} (floor +0.150), n={n}",
    ))

    g2 = sep_full >= sep_det + 0.05
    out.append(GateOutcome(
        gate="G2", name="beats deterministic detector", passed=g2, kill=True,
        detail=(f"FULL={sep_full:+.3f} vs DET={sep_det:+.3f}, "
                f"delta={sep_full - sep_det:+.3f} (floor +0.050)"),
    ))

    rate = sum(full_flagged) / n if n else 0.0
    g3 = 0.05 <= rate <= 0.60
    out.append(GateOutcome(
        gate="G3", name="bidirectional non-degeneracy", passed=g3, kill=True,
        detail=f"FULL flag rate={rate:.3f} (band [0.05, 0.60])",
    ))

    g4 = evidence_resolved_rate >= 0.70
    out.append(GateOutcome(
        gate="G4", name="evidence integrity", passed=g4, kill=True,
        detail=(f"resolved evidence rate={evidence_resolved_rate:.3f} "
                f"(floor 0.70) over {n_flag_instances} flag instances"),
    ))

    g5 = sep_full >= sep_rand + 0.10
    out.append(GateOutcome(
        gate="G5", name="causal isolation vs random control", passed=g5, kill=True,
        detail=(f"FULL={sep_full:+.3f} vs RAND={sep_rand:+.3f}, "
                f"delta={sep_full - sep_rand:+.3f} (floor +0.100)"),
    ))
    return out
