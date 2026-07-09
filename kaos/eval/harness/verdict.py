"""Verdict assembly from a list of GateOutcome.

The verdict rule is uniform across probes:

    VOID    if there are no kill-gates at all (a probe that gates nothing
            cannot ACCEPT), if judge_kappa is below kappa_min, or if any
            non-kill sanity gate fails (typically G0).
    ACCEPT  iff there is at least one kill-gate and every kill-gate passes.
    REJECT  if any kill-gate fails.

``judge_kappa`` may be ``None``, meaning the probe uses a mechanical
ground-truth label with no independent second labeler — the kappa audit
is not applicable and is skipped (NOT treated as a passing 1.0).

This is the only verdict computation in KAOS. Probes assemble their
own gate list (domain-specific predicates) but route the final
{ACCEPT, REJECT, VOID} decision through here so no probe can invent a
softer rule mid-run.
"""

from __future__ import annotations

from kaos.eval.harness.types import GateOutcome


def compute_verdict(
    outcomes: list[GateOutcome],
    *,
    judge_kappa: float | None,
    kappa_min: float = 0.85,
) -> str:
    """Return one of ``ACCEPT`` / ``REJECT: ...`` / ``VOID: ...``."""
    if judge_kappa is not None and judge_kappa < kappa_min:
        return f"VOID: judge-audit kappa={judge_kappa:.3f} < {kappa_min}"
    failed_sanity = [g for g in outcomes if not g.kill and not g.passed]
    if failed_sanity:
        names = ", ".join(g.gate for g in failed_sanity)
        return f"VOID: sanity gate(s) failed: {names}"
    kills = [g for g in outcomes if g.kill]
    if not kills:
        # A probe with no kill-gates cannot ACCEPT — all([]) is True, so the
        # old code silently passed a probe that gated nothing. That is an
        # inadmissible harness, not a success.
        return "VOID: no kill-gates registered (nothing to falsify)"
    if all(g.passed for g in kills):
        return "ACCEPT"
    failed = [g.gate for g in kills if not g.passed]
    return f"REJECT: kill gate(s) failed: {', '.join(failed)}"
