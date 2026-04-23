"""Failures phase — scan agents for missed fingerprints, expose lookup API.

Inline hooks (auto.on_agent_completion) capture fingerprints as failures
happen. This phase performs a catch-up scan so fingerprints from pre-M2
failures (or from agents that failed before the hooks were installed) are
retroactively recorded.

Also exposes ``lookup(error_text)`` — the fast agent-time helper: given a new
error message, return the best matching historical fingerprint and its
recorded fix, so an agent can try the known fix BEFORE going back to the LLM.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any

from kaos.dream.auto import fingerprint_of, normalise_error, record_failure_fingerprint


@dataclass
class FailureEntry:
    fp_id: int
    fingerprint: str
    count: int
    tool_name: str | None
    example_error: str | None
    first_seen: str
    last_seen: str
    fix_summary: str | None
    fix_skill_id: int | None


@dataclass
class FailuresReport:
    total_fingerprints: int = 0
    recurring: list[FailureEntry] = field(default_factory=list)
    newly_added: int = 0


def run(conn: sqlite3.Connection, *, min_count_for_recurring: int = 2) -> FailuresReport:
    """Scan failed agents, fill any missed fingerprints, return top recurring."""
    report = FailuresReport()
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        try:
            failed_agents = conn.execute(
                "SELECT agent_id FROM agents WHERE status IN ('failed','killed')"
            ).fetchall()
        except sqlite3.OperationalError:
            return report

        for row in failed_agents:
            aid = row["agent_id"]
            # Only add fingerprints we don't already have for this agent's
            # most recent error. record_failure_fingerprint is idempotent on
            # the (tool_name, normalised_error) tuple via UNIQUE constraint.
            err_row = conn.execute(
                "SELECT tool_name, error_message FROM tool_calls "
                "WHERE agent_id = ? AND status='error' AND error_message IS NOT NULL "
                "ORDER BY started_at DESC LIMIT 1",
                (aid,),
            ).fetchone()
            if not err_row or not err_row["error_message"]:
                continue
            fp = fingerprint_of(err_row["tool_name"] or "<unknown>",
                                err_row["error_message"])
            before = conn.execute(
                "SELECT fp_id FROM failure_fingerprints WHERE fingerprint = ?",
                (fp,),
            ).fetchone()
            fp_id = record_failure_fingerprint(conn, aid)
            if fp_id and not before:
                report.newly_added += 1

        total = conn.execute(
            "SELECT COUNT(*) FROM failure_fingerprints"
        ).fetchone()[0]
        report.total_fingerprints = total

        rows = conn.execute(
            """
            SELECT fp_id, fingerprint, count, tool_name, example_error,
                   first_seen, last_seen, fix_summary, fix_skill_id
            FROM failure_fingerprints
            WHERE count >= ?
            ORDER BY count DESC, last_seen DESC
            LIMIT 20
            """,
            (min_count_for_recurring,),
        ).fetchall()
        for r in rows:
            report.recurring.append(FailureEntry(
                fp_id=r["fp_id"], fingerprint=r["fingerprint"],
                count=r["count"], tool_name=r["tool_name"],
                example_error=r["example_error"],
                first_seen=r["first_seen"], last_seen=r["last_seen"],
                fix_summary=r["fix_summary"], fix_skill_id=r["fix_skill_id"],
            ))
    finally:
        conn.row_factory = prev

    return report


def lookup(conn: sqlite3.Connection, tool_name: str, error_message: str) -> dict[str, Any] | None:
    """Agent-time fast path: given a fresh error, return the historical
    fingerprint record (if any) with its recorded fix.

    Returns None on miss. Callers should consult this BEFORE invoking the LLM
    to diagnose a failure — if there's a known fix it may apply directly.
    """
    fp = fingerprint_of(tool_name or "<unknown>", error_message)
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT fp_id, fingerprint, count, tool_name, example_error, "
            "first_seen, last_seen, fix_summary, fix_skill_id "
            "FROM failure_fingerprints WHERE fingerprint = ?",
            (fp,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.row_factory = prev
    if row is None:
        return None
    return dict(row)


def attach_fix(
    conn: sqlite3.Connection,
    fp_id: int,
    *,
    fix_agent_id: str | None = None,
    fix_summary: str | None = None,
    fix_skill_id: int | None = None,
) -> None:
    """Record that a particular failure fingerprint has a known fix."""
    try:
        conn.execute(
            "UPDATE failure_fingerprints "
            "SET fix_agent_id = ?, fix_summary = ?, fix_skill_id = ? "
            "WHERE fp_id = ?",
            (fix_agent_id, fix_summary, fix_skill_id, fp_id),
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
