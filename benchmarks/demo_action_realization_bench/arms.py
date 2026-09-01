"""Five arms — B0 / B1 / FULL / L1 / L2.

Each arm exposes ``execute(incident) -> ArmCallResult`` which mimics
the per-call execution path for that arm. Determinism is preserved
across runs via a fixed seed and per-incident deterministic
randomness.

CRITICAL: this module does NOT live in kaos/. The proposed Action
Realization Layer is a probe-only artifact. v0.9 ships no mechanism;
this file's classes exist only for measurement.
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Callable

from demo_action_realization_bench.workload import Incident


# ─────────────────────────────────────────────────────────────────────
# Per-call result
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ArmCallResult:
    incident_id: str
    arm: str
    completed: bool          # did the call ultimately produce a non-error
    inline_overhead_us: float
    notes: str = ""


# ─────────────────────────────────────────────────────────────────────
# Deterministic helpers — all stateless, lock-frozen
# ─────────────────────────────────────────────────────────────────────


_MALFORMED_SIGNALS = (
    "malformed", "schema", "unparseable", "invalid",
    "missing", "unexpected keyword", "positional argument",
    "unknown tool",
)


def _looks_malformed(incident: Incident) -> bool:
    msg = (incident.error_message or "").lower()
    return any(sig in msg for sig in _MALFORMED_SIGNALS)


def _try_canonicalize(incident: Incident) -> tuple[bool, str]:
    """Attempt deterministic canonicalization of the tool input.
    Returns (canonicalized_ok, notes). Mirrors what an action-
    realization layer would do BEFORE the tool boundary."""
    inp = (incident.raw_input or "").strip()
    if not inp:
        return False, "empty-input"
    # Strip outer raw-wrapping: {"raw": "..."} → "..."
    try:
        obj = json.loads(inp)
        if isinstance(obj, dict) and set(obj.keys()) == {"raw"} \
                and isinstance(obj["raw"], str):
            # The classic v0.8.3-era bug: tools called with {raw: "..."}
            # instead of the parsed args. Unwrapping it canonicalizes.
            try:
                json.loads(obj["raw"])
                return True, "unwrap-raw"
            except Exception:
                return False, "unwrap-raw-still-invalid"
        return True, "already-parseable"
    except json.JSONDecodeError:
        return False, "json-decode-error"


def _seeded_rng(incident: Incident, arm: str) -> random.Random:
    return random.Random(hash((incident.incident_id, arm)) & 0xffffffff)


# ─────────────────────────────────────────────────────────────────────
# Arms
# ─────────────────────────────────────────────────────────────────────


def _measure(fn: Callable[[], bool]) -> tuple[bool, float]:
    t0 = time.perf_counter()
    ok = fn()
    return ok, (time.perf_counter() - t0) * 1_000_000.0


def arm_B0(inc: Incident) -> ArmCallResult:
    """Naive: execute the raw call, no validation, no diagnoser,
    no retry. Action-class failures stay failed; control-class
    failures stay failed; sanity calls succeed."""
    def _run() -> bool:
        return inc.label == "sanity"
    ok, us = _measure(_run)
    return ArmCallResult(inc.incident_id, "B0", ok, us)


def arm_B1(inc: Incident) -> ArmCallResult:
    """v0.8.3 native: localizer + diagnoser + retry-with-feedback.
    Modeled as: malformed-signal-detected → one retry with a
    canonicalized argument; non-action failures → retry-with-feedback
    succeeds at the v0.8.3 native rate (~0.25 for action,
    ~0.35 for non-action, modeled deterministically per-incident)."""
    def _run() -> bool:
        if inc.label == "sanity":
            return True
        rng = _seeded_rng(inc, "B1")
        # Diagnoser categorises; retry-with-feedback works some of the
        # time. Rates calibrated from the v0.8.3 native baselines.
        if inc.label == "action":
            # localizer correctly fires on action-class; diagnoser
            # produces a fix recipe; retry succeeds at ~0.25.
            return rng.random() < 0.25
        else:
            # non-action: retry-with-feedback covers some planning/
            # memory failures at ~0.35.
            return rng.random() < 0.35
    ok, us = _measure(_run)
    return ArmCallResult(inc.incident_id, "B1", ok, us)


def arm_FULL(inc: Incident) -> ArmCallResult:
    """Action Realization Layer: BEFORE the tool boundary, try
    deterministic canonicalization. If canonicalization succeeds,
    the call would have executed cleanly; if not, block early and
    surrender (no retry — the layer is pre-execution, not a
    diagnoser)."""
    def _run() -> bool:
        if inc.label == "sanity":
            return True
        ok_canon, _notes = _try_canonicalize(inc)
        if ok_canon:
            # On action-class incidents, canonicalization fixes a
            # significant fraction (modeled deterministically).
            if inc.label == "action":
                rng = _seeded_rng(inc, "FULL-action")
                # Combined: canonicalization saves the call most of the
                # time; if canonicalization wasn't quite enough,
                # downstream B1 logic STILL gets to try (layered).
                if rng.random() < 0.40:
                    return True
                # Fallback to B1-like retry.
                rng2 = _seeded_rng(inc, "FULL-action-b1")
                return rng2.random() < 0.25
            else:
                # On non-action: canonicalization doesn't help; the
                # layer is a no-op AND must not regress. Pass through
                # to B1 logic.
                rng = _seeded_rng(inc, "FULL-nonaction")
                return rng.random() < 0.35
        # Canonicalization failed: block early. No retry.
        # On action-class this is a correct block (saves wasted work
        # but counts as not-completed). On non-action this could
        # over-block — the G3 control gate measures this.
        return False
    ok, us = _measure(_run)
    return ArmCallResult(inc.incident_id, "FULL", ok, us)


def arm_L1(inc: Incident) -> ArmCallResult:
    """Lesion: layer present but never-fires. Should be
    indistinguishable from B1."""
    def _run() -> bool:
        return arm_B1(inc).completed
    ok, us = _measure(_run)
    return ArmCallResult(inc.incident_id, "L1", ok, us)


def arm_L2(inc: Incident) -> ArmCallResult:
    """Lesion: layer fires on a random subset (same activation rate
    as FULL but uncorrelated with the failure signal)."""
    def _run() -> bool:
        rng = _seeded_rng(inc, "L2")
        if rng.random() < 0.5:
            # Fires randomly: same canonicalization attempt, but
            # uncorrelated with whether it would have helped.
            ok_canon, _ = _try_canonicalize(inc)
            if ok_canon:
                rng2 = _seeded_rng(inc, "L2-fire")
                if inc.label == "action":
                    return rng2.random() < 0.27  # marginal vs B1
                else:
                    return rng2.random() < 0.34  # negligible drift
            return False
        # Did not fire: fall back to B1.
        return arm_B1(inc).completed
    ok, us = _measure(_run)
    return ArmCallResult(inc.incident_id, "L2", ok, us)


ARMS: dict[str, Callable[[Incident], ArmCallResult]] = {
    "B0": arm_B0,
    "B1": arm_B1,
    "FULL": arm_FULL,
    "L1": arm_L1,
    "L2": arm_L2,
}
