"""Primitive scoring functions shared across dream phases.

Deterministic, pure, cheap. No I/O, no DB, no random. Anything that reads
the database lives in a phase file; anything that returns a score lives here.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone


# Default half-life for recency decay. A skill used two weeks ago counts
# for half as much as one used today. Tunable via DreamCycle config later.
DEFAULT_HALF_LIFE_DAYS = 14.0


def parse_iso(ts: str | None) -> datetime | None:
    """Parse a KAOS ISO timestamp. Returns None on empty/garbage input."""
    if not ts:
        return None
    # KAOS stores `YYYY-MM-DDTHH:MM:SS.fff` with no timezone. Treat as UTC.
    try:
        # datetime.fromisoformat handles microseconds fine on py3.11+
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def recency_weight(ts: str | None, *, now: datetime | None = None,
                   half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    """Return a recency multiplier in (0, 1].

    0.0 never produced — an all-time-ago timestamp still yields a tiny positive
    weight rather than zeroing the entry out. Missing/unparseable timestamps
    get a neutral 0.5 so we don't privilege or punish unknowns.
    """
    if ts is None:
        return 0.5
    parsed = parse_iso(ts)
    if parsed is None:
        return 0.5
    current = now or now_utc()
    age_seconds = max(0.0, (current - parsed).total_seconds())
    age_days = age_seconds / 86400.0
    # Exponential decay: weight = 2^(-age / half_life)
    return math.pow(2.0, -age_days / max(half_life_days, 0.001))


def success_rate(uses: int, successes: int) -> float | None:
    """Return successes/uses in [0, 1], or None when uses == 0."""
    if uses <= 0:
        return None
    rate = successes / uses
    if rate < 0.0:
        return 0.0
    if rate > 1.0:
        return 1.0
    return rate


def wilson_lower_bound(successes: int, uses: int, z: float = 1.96) -> float:
    """Wilson score interval lower bound — a conservative success estimator.

    Penalises small sample sizes more than raw success_rate does, so a skill
    with 10/10 successes outranks a skill with 1/1. Returns 0.0 when uses==0.
    """
    if uses <= 0:
        return 0.0
    phat = successes / uses
    n = uses
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    lower = (centre - margin) / denom
    return max(0.0, min(1.0, lower))


def weighted_score(
    *,
    bm25_score: float,
    uses: int,
    successes: int,
    last_used_at: str | None,
    now: datetime | None = None,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    bm25_floor: float = 0.01,
    usage_multiplier: float = 3.0,
) -> float:
    """Combine a retrieval score with usage signals.

    - ``bm25_score``: SQLite FTS5 rank (already negated upstream so higher = better
      when this function receives it). If the caller has nothing, pass 1.0.
    - ``uses``, ``successes``: the lifetime counters.
    - ``last_used_at``: ISO timestamp of the most recent use.

    Returns a positive score; higher = better. The structure is::

        score = max(bm25_score, floor) × usage_factor × recency

    where ``usage_factor`` is::

        0.5                                   (never used)
        0.5 + usage_multiplier × wilson_lower_bound(successes, uses)

    The 0.5 offset keeps never-used entries from scoring zero. The
    ``usage_multiplier=3.0`` default gives a 7× swing between "never used"
    and "proven successful many times" — enough to overcome moderate BM25
    score differences between nearly-equally-relevant documents.
    """
    retrieval = max(bm25_score, bm25_floor)
    if uses == 0:
        usage_factor = 0.5
    else:
        usage_factor = 0.5 + usage_multiplier * wilson_lower_bound(successes, uses)
    return retrieval * usage_factor * recency_weight(
        last_used_at, now=now, half_life_days=half_life_days
    )


def coldness(uses: int, last_used_at: str | None,
             *, now: datetime | None = None,
             half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    """Return a coldness score in [0, 1].

    0 = recently active, 1 = ancient and unused. Useful for pruning candidates
    and for the digest's "cold entries" section.
    """
    if uses == 0 and last_used_at is None:
        return 1.0
    r = recency_weight(last_used_at, now=now, half_life_days=half_life_days)
    # Convert recency (higher=newer) to coldness (higher=older)
    return 1.0 - r
