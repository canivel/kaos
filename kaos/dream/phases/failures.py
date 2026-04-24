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


# ── Fix-outcome tracking (plasticity on the fix itself) ────────────


# After this many attempts at a recorded fix, if the success rate drops
# below the threshold we auto-downgrade (blank out the fix suggestion).
FIX_DOWNGRADE_MIN_ATTEMPTS = 5
FIX_DOWNGRADE_SUCCESS_RATE = 0.5


def record_fix_outcome(
    conn: sqlite3.Connection,
    fp_id: int,
    *,
    succeeded: bool,
) -> dict[str, Any]:
    """Record whether a previously-suggested fix actually resolved the error.

    Agents should call this after trying a known fix so the system can
    learn which fixes work. If the success rate drops below
    ``FIX_DOWNGRADE_SUCCESS_RATE`` after ``FIX_DOWNGRADE_MIN_ATTEMPTS``
    tries, the fix_summary is auto-cleared so future agents don't keep
    applying the broken suggestion.

    Returns a dict with post-update fix_attempts, fix_success_count,
    success_rate, and whether the fix got downgraded this call.
    """
    try:
        conn.execute(
            "UPDATE failure_fingerprints "
            "SET fix_attempts = fix_attempts + 1, "
            "    fix_success_count = fix_success_count + ? "
            "WHERE fp_id = ?",
            (1 if succeeded else 0, fp_id),
        )
        row = conn.execute(
            "SELECT fix_attempts, fix_success_count, fix_summary "
            "FROM failure_fingerprints WHERE fp_id = ?",
            (fp_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return {"fp_id": fp_id, "error": "schema too old"}

    if row is None:
        return {"fp_id": fp_id, "error": "fingerprint not found"}

    attempts, successes, fix_summary = row[0], row[1], row[2]
    rate = successes / attempts if attempts else 0.0
    downgraded = False
    if (attempts >= FIX_DOWNGRADE_MIN_ATTEMPTS
            and rate < FIX_DOWNGRADE_SUCCESS_RATE
            and fix_summary):
        conn.execute(
            "UPDATE failure_fingerprints "
            "SET fix_summary = NULL, fix_skill_id = NULL "
            "WHERE fp_id = ?",
            (fp_id,),
        )
        downgraded = True

    conn.commit()
    return {
        "fp_id": fp_id,
        "fix_attempts": attempts,
        "fix_success_count": successes,
        "fix_success_rate": round(rate, 3),
        "downgraded": downgraded,
    }


# ── Systemic alert query surface ───────────────────────────────────


def list_active_alerts(
    conn: sqlite3.Connection,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List unresolved systemic alerts — agents should refuse to spawn when
    any active alerts exist until a human resolves them.
    """
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                """
                SELECT a.alert_id, a.fp_id, a.detected_at, a.agent_count,
                       a.window_seconds, a.root_cause, a.acked_at, a.acked_by,
                       f.fingerprint, f.tool_name, f.example_error, f.category
                FROM systemic_alerts a
                LEFT JOIN failure_fingerprints f ON f.fp_id = a.fp_id
                WHERE a.resolved_at IS NULL
                ORDER BY a.detected_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.row_factory = prev
    return [dict(r) for r in rows]


def ack_alert(
    conn: sqlite3.Connection,
    alert_id: int,
    *,
    acked_by: str | None = None,
) -> bool:
    try:
        cur = conn.execute(
            "UPDATE systemic_alerts "
            "SET acked_at = strftime('%Y-%m-%dT%H:%M:%f','now'), acked_by = ? "
            "WHERE alert_id = ? AND resolved_at IS NULL",
            (acked_by, alert_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.OperationalError:
        return False


def resolve_alert(
    conn: sqlite3.Connection,
    alert_id: int,
    *,
    resolved_by: str | None = None,
) -> bool:
    try:
        cur = conn.execute(
            "UPDATE systemic_alerts "
            "SET resolved_at = strftime('%Y-%m-%dT%H:%M:%f','now'), "
            "    resolved_by = ? "
            "WHERE alert_id = ?",
            (resolved_by, alert_id),
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.OperationalError:
        return False


# ── Manual (re)categorisation ──────────────────────────────────────


def set_category(
    conn: sqlite3.Connection,
    fp_id: int,
    *,
    category: str,
    root_cause: str | None = None,
    suggested_action: str | None = None,
) -> bool:
    """Manually override the category for a fingerprint (user knows best)."""
    try:
        conn.execute(
            """
            UPDATE failure_fingerprints
            SET category = ?,
                root_cause = COALESCE(?, root_cause),
                suggested_action = COALESCE(?, suggested_action),
                diagnostic_method = 'user',
                diagnosed_at = strftime('%Y-%m-%dT%H:%M:%f','now')
            WHERE fp_id = ?
            """,
            (category, root_cause, suggested_action, fp_id),
        )
        conn.commit()
        return True
    except sqlite3.OperationalError:
        return False


def recategorise_all(conn: sqlite3.Connection) -> int:
    """Re-run heuristic diagnosis on every fingerprint still marked 'unknown'.

    Useful after registering a new diagnoser — catches up fingerprints that
    got default-categorised before the diagnoser existed.

    Returns the number of fingerprints updated.
    """
    from kaos.dream.diagnosis import diagnose

    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                "SELECT fp_id, tool_name, example_error FROM failure_fingerprints "
                "WHERE category = 'unknown' OR category IS NULL"
            ).fetchall()
        except sqlite3.OperationalError:
            return 0
    finally:
        conn.row_factory = prev

    updated = 0
    for r in rows:
        result = diagnose(r["tool_name"] or "<unknown>",
                          r["example_error"] or "")
        if result.confidence == 0.0:
            continue
        conn.execute(
            """
            UPDATE failure_fingerprints
            SET category = ?, root_cause = ?, suggested_action = ?,
                diagnostic_method = ?,
                diagnosed_at = strftime('%Y-%m-%dT%H:%M:%f','now')
            WHERE fp_id = ?
            """,
            (result.category, result.root_cause, result.suggested_action,
             result.method, r["fp_id"]),
        )
        updated += 1
    conn.commit()
    return updated
