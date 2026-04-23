"""Weights phase — rank skills and memory by usage-weighted scores.

Reads the lifetime counters (agent_skills.use_count/success_count), the
per-use telemetry (skill_uses, memory_hits), and produces ranked lists for
the digest. Nothing is persisted in M1 — the scores are recomputed on every
dream run, which is cheap even at 10k skills.

The weighted_score function is shared with SkillStore.search(rank="weighted")
and MemoryStore.search(rank="weighted") so the ordering the digest reports is
the same one agents see at runtime.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from kaos.dream.signals import (
    coldness,
    now_utc,
    recency_weight,
    weighted_score,
)


@dataclass
class SkillScore:
    skill_id: int
    name: str
    uses: int
    successes: int
    created_at: str
    last_used_at: str | None
    success_rate: float | None
    score: float
    coldness: float


@dataclass
class MemoryScore:
    memory_id: int
    key: str | None
    type: str
    hits: int
    created_at: str
    last_hit_at: str | None
    score: float
    coldness: float


@dataclass
class WeightsReport:
    skills: list[SkillScore] = field(default_factory=list)
    memory: list[MemoryScore] = field(default_factory=list)
    hot_skills: list[SkillScore] = field(default_factory=list)
    cold_skills: list[SkillScore] = field(default_factory=list)
    hot_memory: list[MemoryScore] = field(default_factory=list)
    cold_memory: list[MemoryScore] = field(default_factory=list)


def run(conn: sqlite3.Connection, *, now: datetime | None = None,
        top_n: int = 10) -> WeightsReport:
    """Score every skill and memory entry, then produce hot/cold splits."""
    now_dt = now or now_utc()

    prev_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        skills = _score_skills(conn, now=now_dt)
        memory = _score_memory(conn, now=now_dt)
    finally:
        conn.row_factory = prev_factory

    report = WeightsReport(skills=skills, memory=memory)
    report.hot_skills = sorted(skills, key=lambda s: -s.score)[:top_n]
    report.cold_skills = sorted(skills, key=lambda s: -s.coldness)[:top_n]
    report.hot_memory = sorted(memory, key=lambda m: -m.score)[:top_n]
    report.cold_memory = sorted(memory, key=lambda m: -m.coldness)[:top_n]
    return report


def _score_skills(conn: sqlite3.Connection, *, now: datetime) -> list[SkillScore]:
    last_used = _skill_last_used(conn)
    rows = conn.execute(
        "SELECT skill_id, name, use_count, success_count, created_at, updated_at "
        "FROM agent_skills"
    ).fetchall()
    out: list[SkillScore] = []
    for r in rows:
        sid = r["skill_id"]
        uses = r["use_count"]
        succ = r["success_count"]
        # Actual last use (None if never used) — used for coldness.
        real_last = last_used.get(sid)
        # Scoring uses a fallback so never-used skills still get a reasonable
        # recency signal (library-creation time, not epoch zero).
        score_last = real_last or r["updated_at"] or r["created_at"]
        score = weighted_score(
            bm25_score=1.0,
            uses=uses,
            successes=succ,
            last_used_at=score_last,
            now=now,
        )
        out.append(SkillScore(
            skill_id=sid,
            name=r["name"],
            uses=uses,
            successes=succ,
            created_at=r["created_at"],
            last_used_at=real_last,
            success_rate=(succ / uses) if uses > 0 else None,
            score=score,
            coldness=coldness(uses, real_last, now=now),
        ))
    return out


def _skill_last_used(conn: sqlite3.Connection) -> dict[int, str]:
    try:
        rows = conn.execute(
            "SELECT skill_id, MAX(used_at) AS last_used_at "
            "FROM skill_uses GROUP BY skill_id"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}
    return {r["skill_id"]: r["last_used_at"] for r in rows if r["last_used_at"]}


def _score_memory(conn: sqlite3.Connection, *, now: datetime) -> list[MemoryScore]:
    hits, last_hits = _memory_hits_agg(conn)
    rows = conn.execute(
        "SELECT memory_id, key, type, created_at FROM memory"
    ).fetchall()
    out: list[MemoryScore] = []
    for r in rows:
        mid = r["memory_id"]
        n_hits = hits.get(mid, 0)
        last = last_hits.get(mid) or r["created_at"]
        # Memory has no success/failure signal — treat every hit as a success
        # for the Wilson-based scorer.
        score = weighted_score(
            bm25_score=1.0,
            uses=n_hits,
            successes=n_hits,
            last_used_at=last,
            now=now,
        )
        out.append(MemoryScore(
            memory_id=mid,
            key=r["key"],
            type=r["type"],
            hits=n_hits,
            created_at=r["created_at"],
            last_hit_at=last_hits.get(mid),
            score=score,
            coldness=coldness(n_hits, last, now=now),
        ))
    return out


def _memory_hits_agg(conn: sqlite3.Connection) -> tuple[dict[int, int], dict[int, str]]:
    try:
        rows = conn.execute(
            "SELECT memory_id, COUNT(*) AS n, MAX(hit_at) AS last_hit "
            "FROM memory_hits GROUP BY memory_id"
        ).fetchall()
    except sqlite3.OperationalError:
        return {}, {}
    counts: dict[int, int] = {}
    lasts: dict[int, str] = {}
    for r in rows:
        counts[r["memory_id"]] = r["n"]
        if r["last_hit"]:
            lasts[r["memory_id"]] = r["last_hit"]
    return counts, lasts
