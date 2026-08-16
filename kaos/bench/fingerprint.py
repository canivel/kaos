"""Task-shape fingerprinting + transfer-match-on-pull (Filter 2).

Implements PLAN v2 §2.3 (fingerprint) and §3.2 (match) from the attraktor
repo. Milliseconds, deterministic, no embeddings, no LLM.

The four axes are ordinal levels, never floats (R2: numeric ranges are false
precision that invites tuning):

    unknown < absent < weak < present < strong

The GDL lesson is mechanized twice: (a) M1's vacuity guard — label diversity < 3
means M1 is UNKNOWN, and unknown is NEVER treated as present; (b) consumed axes
gate HARD with no partial credit — GDL's 81-point benchmark delta was real on its
bench and worthless at organic reuse 1.000; at weight 0.5 it would still have been
injected. Down-weighting exists only for context drift on non-consumed axes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum

AXES = ("M1", "M2", "M3", "M4")

# Lock-bound constants (admission.lock.json v1 — change = lock version change).
CTX_FULL_THRESHOLD = 0.70
PARTIAL_WEIGHT = 0.5
M1_MIN_LABEL_DIVERSITY = 3


class Level(IntEnum):
    """Ordinal axis level. UNKNOWN is the floor by design: an unmeasured axis can
    never satisfy a consumed-axis requirement (unknown != present)."""
    UNKNOWN = 0
    ABSENT = 1
    WEAK = 2
    PRESENT = 3
    STRONG = 4


class Grain(IntEnum):
    """Outcome-signal grain for monitorability (I3): a task must be monitorable at
    least as finely as the record's envelope requires."""
    NONE = 0
    EPISODE = 1
    STEP = 2


# The W3 anchor regexes (paper2 workload-shape audit) — fixed, part of the lock.
_ANCHORS = {
    "path": re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+|\w+\.(?:py|md|json|yaml|yml|sql|toml|txt|db|html|tex|js|ts)\b"),
    "identifier": re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b|\b[a-z]+[A-Z][A-Za-z]+\b"),
    "error_code": re.compile(r"\b(?:exit \d+|E\d{2,}|errno|traceback|exception)\b", re.I),
    "hex_or_hash": re.compile(r"\b[0-9a-f]{7,}\b"),
    "version_or_num": re.compile(r"\bv?\d+\.\d+(?:\.\d+)?\b"),
}
_TOKEN = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class TaskShape:
    """The pulling task's measured shape. m3_anchor_tokens is kept as a set —
    M3 is scored per-candidate as anchor-token overlap with the record's verbatim
    retrieval keys, not as a global level."""
    m1: Level = Level.UNKNOWN
    m2: Level = Level.UNKNOWN
    m4: Level = Level.UNKNOWN
    m2_grain: Grain = Grain.NONE
    m3_anchor_tokens: set[str] = field(default_factory=set)

    def level(self, axis: str, envelope: "Envelope | None" = None) -> Level:
        if axis == "M1":
            return self.m1
        if axis == "M2":
            return self.m2
        if axis == "M4":
            return self.m4
        if axis == "M3":
            # Per-candidate: overlap of task anchors with the record's keys.
            if envelope is None or not envelope.retrieval_keys:
                return Level.UNKNOWN
            if not self.m3_anchor_tokens:
                return Level.ABSENT
            hits = len(self.m3_anchor_tokens & envelope.retrieval_keys)
            if hits == 0:
                return Level.ABSENT
            return Level.STRONG if hits >= 3 else Level.PRESENT
        raise ValueError(f"unknown axis {axis!r}")


@dataclass
class Envelope:
    """A record's transfer envelope: the axes its premise CONSUMES (hard gate) and
    the levels MEASURED on its validating traffic (soft context)."""
    consumes: tuple[str, ...] = ()
    measured: dict[str, Level] = field(default_factory=dict)
    m2_grain: Grain = Grain.EPISODE
    retrieval_keys: set[str] = field(default_factory=set)


@dataclass
class MatchResult:
    decision: str            # 'PULL' | 'WITHHOLD'
    weight: float = 0.0      # 1.0 full, PARTIAL_WEIGHT partial, 0.0 withheld
    fidelity: str = ""       # 'full' | 'partial' (stamped on the pull, stratifies outcomes)
    reason: str = ""         # withhold reason: 'axis-unknown' | 'axis-absent' | 'unmonitorable'
    axis: str | None = None  # the axis that withheld, if any
    ctx_score: float = 0.0


def anchor_tokens(text: str) -> set[str]:
    """Verbatim anchor tokens of a text (paths, identifiers, error codes, hashes,
    versions) — the M3 currency. Set intersection at pull time, microseconds."""
    out: set[str] = set()
    for rx in _ANCHORS.values():
        for m in rx.finditer(text):
            out.update(t.lower() for t in _TOKEN.findall(m.group(0)))
    return out


def m1_level(
    *, covered_fraction: float, median_reuse: float, label_diversity: int,
) -> Level:
    """Closed-vocab profile → level, with the vacuity guard (GDL lesson): fewer
    than M1_MIN_LABEL_DIVERSITY distinct labels means the reuse statistic is
    meaningless in BOTH degenerate directions → UNKNOWN, and unknown is never
    'present'."""
    if label_diversity < M1_MIN_LABEL_DIVERSITY:
        return Level.UNKNOWN
    if median_reuse >= 1.3 and covered_fraction >= 0.5:
        return Level.STRONG
    if median_reuse >= 1.3 or covered_fraction >= 0.5:
        return Level.PRESENT
    if median_reuse > 1.1 or covered_fraction >= 0.25:
        return Level.WEAK
    return Level.ABSENT


def m2_level(*, checkable_predicates: int, outcome_grain: Grain) -> Level:
    """Outcome-signal density of THIS task: how many checkable success predicates
    exist (tests referenced, output schema, judge configured, verify-numerics
    applicable) and at what grain outcomes get written."""
    if outcome_grain == Grain.NONE:
        return Level.ABSENT if checkable_predicates == 0 else Level.WEAK
    if checkable_predicates >= 2 and outcome_grain == Grain.STEP:
        return Level.STRONG
    if checkable_predicates >= 1:
        return Level.PRESENT
    return Level.WEAK


def m4_level(*, strong_provider_reachable: bool, matched_episode: bool,
             matched_episode_diversity: int = 0) -> Level:
    """Expert-reference availability. A loose matched episode only counts when it
    has label diversity >= 3 — mono-label pairs are undiffable (GDL, measured)."""
    diffable_match = matched_episode and matched_episode_diversity >= M1_MIN_LABEL_DIVERSITY
    if strong_provider_reachable and diffable_match:
        return Level.STRONG
    if strong_provider_reachable or diffable_match:
        return Level.PRESENT
    if matched_episode:  # match exists but is mono-label — weak, not usable for diffing
        return Level.WEAK
    return Level.ABSENT


def _similarity(task_level: Level, measured: Level | None) -> float:
    """Context similarity on a NON-consumed axis: same level 1.0, adjacent 0.5,
    else 0.0. Unknown on either side contributes 0.0 — never free credit."""
    if measured is None or task_level == Level.UNKNOWN or measured == Level.UNKNOWN:
        return 0.0
    d = abs(int(task_level) - int(measured))
    return 1.0 if d == 0 else (0.5 if d == 1 else 0.0)


def match(envelope: Envelope, task: TaskShape) -> MatchResult:
    """Filter 2 (PLAN v2 §3.2), verbatim semantics.

    Consumed axes gate HARD (I2): unknown or absent on any consumed axis →
    WITHHOLD, no partial credit ever. Monitorability (I3): the task must write
    outcomes at least as finely as the envelope's grain, else pulled items can
    never be held accountable. Context drift on non-consumed axes only softens
    weight (full vs partial pull) — and partial is stamped so outcomes stratify.
    """
    for axis in envelope.consumes:
        lvl = task.level(axis, envelope)
        if lvl == Level.UNKNOWN:
            return MatchResult("WITHHOLD", reason="axis-unknown", axis=axis)
        if lvl <= Level.ABSENT:
            return MatchResult("WITHHOLD", reason="axis-absent", axis=axis)

    if task.m2_grain < envelope.m2_grain:
        return MatchResult("WITHHOLD", reason="unmonitorable", axis="M2")

    non_consumed = [a for a in AXES if a not in envelope.consumes]
    if non_consumed:
        def _axis_sim(a: str) -> float:
            if a == "M3":
                # M3 has no measured envelope level by construction (it is a
                # per-candidate set intersection) — its context similarity IS the
                # overlap: strong 1.0, present 0.75, else 0.0.
                lvl = task.level("M3", envelope)
                return {Level.STRONG: 1.0, Level.PRESENT: 0.75}.get(lvl, 0.0)
            return _similarity(task.level(a, envelope), envelope.measured.get(a))

        ctx = sum(_axis_sim(a) for a in non_consumed) / len(non_consumed)
    else:
        ctx = 1.0

    if ctx >= CTX_FULL_THRESHOLD:
        return MatchResult("PULL", weight=1.0, fidelity="full", ctx_score=round(ctx, 3))
    return MatchResult("PULL", weight=PARTIAL_WEIGHT, fidelity="partial", ctx_score=round(ctx, 3))
