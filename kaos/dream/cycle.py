"""DreamCycle — orchestrates the dream phases and persists a run record.

One cycle = replay → weights → narrative. Phases run sequentially; each is
timed and the timings are stored in ``dream_runs.phase_timings``.

In ``dry_run`` mode the cycle reads the database but never mutates it (except
writing the ``dream_runs`` row itself — that tracks that the dream happened).
In ``apply`` mode it additionally upserts ``episode_signals`` so downstream
tools (and future milestones) can query reconciled per-agent aggregates.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from kaos.core import Kaos
from kaos.dream.phases import narrative, replay, weights
from kaos.dream.signals import now_utc


@dataclass
class DreamResult:
    """What the caller of DreamCycle.run() gets back."""

    run_id: int
    mode: str
    started_at: datetime
    finished_at: datetime
    since_ts: str | None
    episodes: int
    skills_scored: int
    memories_scored: int
    phase_timings_ms: dict[str, int]
    digest_markdown: str
    digest_path: str | None
    replay_report: replay.ReplayReport = field(default=None)  # type: ignore[assignment]
    weights_report: weights.WeightsReport = field(default=None)  # type: ignore[assignment]

    def summary(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "mode": self.mode,
            "since": self.since_ts,
            "episodes": self.episodes,
            "successes": self.replay_report.successes if self.replay_report else None,
            "failures": self.replay_report.failures if self.replay_report else None,
            "skills_scored": self.skills_scored,
            "memories_scored": self.memories_scored,
            "phase_timings_ms": self.phase_timings_ms,
            "digest_path": self.digest_path,
        }


class DreamCycle:
    """Orchestrates the dream phases against a Kaos instance."""

    def __init__(
        self,
        kaos: Kaos,
        *,
        kaos_version: str = "0.7.0",
        digest_dir: str | Path | None = None,
    ) -> None:
        self.kaos = kaos
        self.kaos_version = kaos_version
        self.digest_dir = Path(digest_dir) if digest_dir else None

    def run(
        self,
        *,
        dry_run: bool = True,
        since_ts: str | None = None,
        write_digest: bool = True,
    ) -> DreamResult:
        mode = "dry_run" if dry_run else "apply"
        started_at = now_utc()
        start_perf = time.perf_counter()
        phase_timings: dict[str, int] = {}

        conn = self.kaos.conn

        # Phase 1 — replay
        t0 = time.perf_counter()
        replay_report = replay.run(conn, since_ts=since_ts, apply=not dry_run)
        phase_timings["replay_ms"] = int((time.perf_counter() - t0) * 1000)

        # Phase 2 — weights
        t0 = time.perf_counter()
        weights_report = weights.run(conn, now=started_at)
        phase_timings["weights_ms"] = int((time.perf_counter() - t0) * 1000)

        finished_at = now_utc()

        # Phase 3 — narrative
        t0 = time.perf_counter()
        digest_md = narrative.render_digest(
            replay=replay_report,
            weights=weights_report,
            mode=mode,
            since_ts=since_ts,
            started_at=started_at,
            finished_at=finished_at,
            db_path=self.kaos.db_path,
            kaos_version=self.kaos_version,
        )
        phase_timings["narrative_ms"] = int((time.perf_counter() - t0) * 1000)

        # Persist the dream_runs row (always — even in dry_run, because a
        # dream happening is itself useful history).
        digest_path: str | None = None
        if write_digest and self.digest_dir:
            self.digest_dir.mkdir(parents=True, exist_ok=True)
            fname = started_at.strftime("%Y-%m-%d-%H%M%S") + ".md"
            p = self.digest_dir / fname
            p.write_text(digest_md, encoding="utf-8")
            digest_path = str(p)

        run_id = _insert_dream_run(
            conn,
            started_at=started_at,
            finished_at=finished_at,
            mode=mode,
            since_ts=since_ts,
            episodes=len(replay_report.episodes),
            skills_scored=len(weights_report.skills),
            memories_scored=len(weights_report.memory),
            phase_timings=phase_timings,
            digest_path=digest_path,
            summary={
                "successes": replay_report.successes,
                "failures": replay_report.failures,
                "in_flight": replay_report.in_flight,
                "total_tokens": replay_report.total_tokens,
                "total_cost_usd": replay_report.total_cost_usd,
                "hot_skills": [s.name for s in weights_report.hot_skills[:5]],
                "cold_skills": [s.name for s in weights_report.cold_skills[:5]
                                if s.coldness >= 0.5],
            },
        )
        total_ms = int((time.perf_counter() - start_perf) * 1000)
        phase_timings["total_ms"] = total_ms

        return DreamResult(
            run_id=run_id,
            mode=mode,
            started_at=started_at,
            finished_at=finished_at,
            since_ts=since_ts,
            episodes=len(replay_report.episodes),
            skills_scored=len(weights_report.skills),
            memories_scored=len(weights_report.memory),
            phase_timings_ms=phase_timings,
            digest_markdown=digest_md,
            digest_path=digest_path,
            replay_report=replay_report,
            weights_report=weights_report,
        )


def list_runs(conn: sqlite3.Connection, *, limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent dream_runs rows, newest first."""
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT run_id, started_at, finished_at, mode, since_ts, episodes, "
            "skills_scored, memories_scored, digest_path, summary "
            "FROM dream_runs ORDER BY run_id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    finally:
        conn.row_factory = prev
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["summary"] = json.loads(d["summary"] or "{}")
        except (json.JSONDecodeError, TypeError):
            d["summary"] = {}
        out.append(d)
    return out


def get_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT run_id, started_at, finished_at, mode, since_ts, episodes, "
            "skills_scored, memories_scored, digest_path, phase_timings, summary "
            "FROM dream_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    finally:
        conn.row_factory = prev
    if row is None:
        return None
    d = dict(row)
    for field_name in ("phase_timings", "summary"):
        try:
            d[field_name] = json.loads(d[field_name] or "{}")
        except (json.JSONDecodeError, TypeError):
            d[field_name] = {}
    return d


def _insert_dream_run(
    conn: sqlite3.Connection,
    *,
    started_at: datetime,
    finished_at: datetime,
    mode: str,
    since_ts: str | None,
    episodes: int,
    skills_scored: int,
    memories_scored: int,
    phase_timings: dict[str, int],
    digest_path: str | None,
    summary: dict[str, Any],
) -> int:
    cur = conn.execute(
        """
        INSERT INTO dream_runs
            (started_at, finished_at, since_ts, mode,
             episodes, skills_scored, memories_scored,
             digest_path, phase_timings, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            started_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
            finished_at.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3],
            since_ts,
            mode,
            episodes,
            skills_scored,
            memories_scored,
            digest_path,
            json.dumps(phase_timings),
            json.dumps(summary),
        ),
    )
    conn.commit()
    return cur.lastrowid  # type: ignore[return-value]
