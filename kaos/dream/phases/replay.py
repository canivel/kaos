"""Replay phase — walk agent history and derive per-episode signals.

An *episode* is one agent from spawn to completion (or failure). Signals
are the lightweight aggregates a scorer needs:

    - success (bool)
    - tool_calls_count, tool_calls_error
    - total_tokens, total_cost_usd
    - duration_ms (ended_at - started_at)
    - skills_applied (count via skill_uses)
    - memories_written / memories_retrieved
    - checkpoints_made

In M1 we only write to `episode_signals` in ``apply`` mode. In ``dry_run``
mode we compute the rows in-memory and pass them to the narrative phase.

Signals are UPSERTED per agent — re-running dream doesn't duplicate. This
makes dream idempotent and safe to run repeatedly during a session.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from kaos.dream.signals import parse_iso


@dataclass
class EpisodeSignal:
    agent_id: str
    started_at: str | None
    ended_at: str | None
    status: str
    success: int | None
    tool_calls_count: int = 0
    tool_calls_error: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    duration_ms: int | None = None
    skills_applied: int = 0
    memories_written: int = 0
    memories_retrieved: int = 0
    checkpoints_made: int = 0

    def to_row(self) -> tuple[Any, ...]:
        return (
            self.agent_id,
            self.started_at,
            self.ended_at,
            self.status,
            self.success,
            self.tool_calls_count,
            self.tool_calls_error,
            self.total_tokens,
            self.total_cost_usd,
            self.duration_ms,
            self.skills_applied,
            self.memories_written,
            self.memories_retrieved,
            self.checkpoints_made,
        )


@dataclass
class ReplayReport:
    episodes: list[EpisodeSignal] = field(default_factory=list)
    successes: int = 0
    failures: int = 0
    in_flight: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    since_ts: str | None = None


_SUCCESS_STATUSES = {"completed"}
_FAILURE_STATUSES = {"failed", "killed"}


def run(conn: sqlite3.Connection, *, since_ts: str | None = None,
        apply: bool = False) -> ReplayReport:
    """Rebuild episode signals and (optionally) persist them.

    ``since_ts`` limits the replay to agents created at or after the timestamp.
    Useful for incremental dreams (``kaos dream --since 2026-04-20``).
    """
    report = ReplayReport(since_ts=since_ts)
    prev_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        return _run_impl(conn, since_ts=since_ts, apply=apply, report=report)
    finally:
        conn.row_factory = prev_factory


def _run_impl(conn: sqlite3.Connection, *, since_ts: str | None, apply: bool,
              report: ReplayReport) -> ReplayReport:
    agents = _fetch_agents(conn, since_ts=since_ts)
    if not agents:
        return report

    agent_ids = [a["agent_id"] for a in agents]
    tool_stats = _aggregate_tool_calls(conn, agent_ids)
    mem_written = _count_memory_writes(conn, agent_ids)
    mem_retrieved = _count_memory_hits(conn, agent_ids)
    skill_applied = _count_skill_uses(conn, agent_ids)
    cp_made = _count_checkpoints(conn, agent_ids)

    for a in agents:
        aid = a["agent_id"]
        status = a["status"]
        success = 1 if status in _SUCCESS_STATUSES else (
            0 if status in _FAILURE_STATUSES else None
        )
        t = tool_stats.get(aid, {})
        started = a["created_at"]
        ended = a.get("last_heartbeat") if status in _SUCCESS_STATUSES | _FAILURE_STATUSES else None
        duration_ms = _duration_ms(started, ended)

        ep = EpisodeSignal(
            agent_id=aid,
            started_at=started,
            ended_at=ended,
            status=status,
            success=success,
            tool_calls_count=t.get("count", 0),
            tool_calls_error=t.get("errors", 0),
            total_tokens=t.get("tokens", 0),
            total_cost_usd=t.get("cost", 0.0),
            duration_ms=duration_ms,
            skills_applied=skill_applied.get(aid, 0),
            memories_written=mem_written.get(aid, 0),
            memories_retrieved=mem_retrieved.get(aid, 0),
            checkpoints_made=cp_made.get(aid, 0),
        )
        report.episodes.append(ep)

        if success == 1:
            report.successes += 1
        elif success == 0:
            report.failures += 1
        else:
            report.in_flight += 1
        report.total_tokens += ep.total_tokens
        report.total_cost_usd += ep.total_cost_usd

    if apply:
        _upsert_signals(conn, report.episodes)

    return report


def _fetch_agents(conn: sqlite3.Connection, *, since_ts: str | None) -> list[dict[str, Any]]:
    if since_ts:
        rows = conn.execute(
            "SELECT agent_id, name, status, created_at, last_heartbeat "
            "FROM agents WHERE created_at >= ? ORDER BY created_at",
            (since_ts,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT agent_id, name, status, created_at, last_heartbeat "
            "FROM agents ORDER BY created_at"
        ).fetchall()
    return [dict(r) for r in rows]


def _aggregate_tool_calls(conn: sqlite3.Connection,
                          agent_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Sum tool-call counts, error counts, tokens, and cost per agent."""
    if not agent_ids:
        return {}
    placeholders = ",".join("?" * len(agent_ids))
    rows = conn.execute(
        f"""
        SELECT agent_id,
               COUNT(*) AS count,
               SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) AS errors,
               COALESCE(SUM(token_count), 0) AS tokens,
               COALESCE(SUM(cost_usd), 0.0) AS cost
        FROM tool_calls
        WHERE agent_id IN ({placeholders})
        GROUP BY agent_id
        """,
        agent_ids,
    ).fetchall()
    return {
        r["agent_id"]: {
            "count": r["count"],
            "errors": r["errors"] or 0,
            "tokens": r["tokens"] or 0,
            "cost": r["cost"] or 0.0,
        }
        for r in rows
    }


def _count_memory_writes(conn: sqlite3.Connection, agent_ids: list[str]) -> dict[str, int]:
    if not agent_ids:
        return {}
    placeholders = ",".join("?" * len(agent_ids))
    rows = conn.execute(
        f"SELECT agent_id, COUNT(*) AS n FROM memory "
        f"WHERE agent_id IN ({placeholders}) GROUP BY agent_id",
        agent_ids,
    ).fetchall()
    return {r["agent_id"]: r["n"] for r in rows}


def _count_memory_hits(conn: sqlite3.Connection, agent_ids: list[str]) -> dict[str, int]:
    if not agent_ids:
        return {}
    try:
        placeholders = ",".join("?" * len(agent_ids))
        rows = conn.execute(
            f"SELECT agent_id, COUNT(*) AS n FROM memory_hits "
            f"WHERE agent_id IN ({placeholders}) GROUP BY agent_id",
            agent_ids,
        ).fetchall()
        return {r["agent_id"]: r["n"] for r in rows if r["agent_id"]}
    except sqlite3.OperationalError:
        # Fresh DB on older schema
        return {}


def _count_skill_uses(conn: sqlite3.Connection, agent_ids: list[str]) -> dict[str, int]:
    if not agent_ids:
        return {}
    try:
        placeholders = ",".join("?" * len(agent_ids))
        rows = conn.execute(
            f"SELECT agent_id, COUNT(*) AS n FROM skill_uses "
            f"WHERE agent_id IN ({placeholders}) GROUP BY agent_id",
            agent_ids,
        ).fetchall()
        return {r["agent_id"]: r["n"] for r in rows if r["agent_id"]}
    except sqlite3.OperationalError:
        return {}


def _count_checkpoints(conn: sqlite3.Connection, agent_ids: list[str]) -> dict[str, int]:
    if not agent_ids:
        return {}
    placeholders = ",".join("?" * len(agent_ids))
    rows = conn.execute(
        f"SELECT agent_id, COUNT(*) AS n FROM checkpoints "
        f"WHERE agent_id IN ({placeholders}) GROUP BY agent_id",
        agent_ids,
    ).fetchall()
    return {r["agent_id"]: r["n"] for r in rows}


def _duration_ms(started: str | None, ended: str | None) -> int | None:
    if not started or not ended:
        return None
    s = parse_iso(started)
    e = parse_iso(ended)
    if s is None or e is None:
        return None
    delta = (e - s).total_seconds() * 1000.0
    return max(0, int(delta))


def _upsert_signals(conn: sqlite3.Connection, episodes: list[EpisodeSignal]) -> None:
    sql = """
    INSERT INTO episode_signals
        (agent_id, started_at, ended_at, status, success,
         tool_calls_count, tool_calls_error,
         total_tokens, total_cost_usd, duration_ms,
         skills_applied, memories_written, memories_retrieved, checkpoints_made,
         last_computed_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            strftime('%Y-%m-%dT%H:%M:%f','now'))
    ON CONFLICT(agent_id) DO UPDATE SET
        started_at=excluded.started_at,
        ended_at=excluded.ended_at,
        status=excluded.status,
        success=excluded.success,
        tool_calls_count=excluded.tool_calls_count,
        tool_calls_error=excluded.tool_calls_error,
        total_tokens=excluded.total_tokens,
        total_cost_usd=excluded.total_cost_usd,
        duration_ms=excluded.duration_ms,
        skills_applied=excluded.skills_applied,
        memories_written=excluded.memories_written,
        memories_retrieved=excluded.memories_retrieved,
        checkpoints_made=excluded.checkpoints_made,
        last_computed_at=strftime('%Y-%m-%dT%H:%M:%f','now')
    """
    rows = [ep.to_row() for ep in episodes]
    conn.executemany(sql, rows)
    conn.commit()
