"""Shared append-only log for multi-agent coordination (LogAct protocol).

Inspired by LogAct: Enabling Agentic Reliability via Shared Logs
(Balakrishnan et al., 2026, arXiv:2604.07988, Meta).

Adapted for KAOS's SQLite-backed architecture.  The shared log is a
monotonically-growing, position-ordered sequence of typed entries that gives
every agent in a project a consistent view of collective intent, votes, and
decisions — without requiring a central coordinator process.

Entry types:
    intent    – agent declares what it plans to do (requires vote before acting)
    vote      – another agent approves or rejects an intent
    decision  – outcome after vote tally (pass/fail/abstain)
    commit    – agent reports a completed, committed action
    result    – final output or artefact produced by an action
    abort     – intent or action was cancelled
    policy    – standing rule injected by a supervisor or human
    mail      – direct async message from one agent to another
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Any

LOG_TYPES = ("intent", "vote", "decision", "commit", "result", "abort", "policy", "mail")


@dataclass
class LogEntry:
    log_id: int
    position: int
    type: str
    agent_id: str
    ref_id: int | None
    payload: dict[str, Any]
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "LogEntry":
        return cls(
            log_id=row["log_id"],
            position=row["position"],
            type=row["type"],
            agent_id=row["agent_id"],
            ref_id=row["ref_id"],
            payload=json.loads(row["payload"] or "{}"),
            created_at=row["created_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "log_id": self.log_id,
            "position": self.position,
            "type": self.type,
            "agent_id": self.agent_id,
            "ref_id": self.ref_id,
            "payload": self.payload,
            "created_at": self.created_at,
        }


@dataclass
class VoteSummary:
    intent_id: int
    approve: int
    reject: int
    abstain: int
    votes: list[LogEntry]

    @property
    def passed(self) -> bool:
        return self.approve > self.reject


class SharedLog:
    """Append-only coordination log shared by all agents in a KAOS project.

    The log implements the four-stage LogAct loop:

        1. **Intent**  — agent broadcasts what it plans to do
        2. **Vote**    — peers approve or reject within a time window
        3. **Decision**— outcome recorded after tally
        4. **Commit / Result** — action taken, artefact produced

    Usage::

        from kaos import Kaos
        from kaos.shared_log import SharedLog

        kaos = Kaos("project.db")
        log  = SharedLog(kaos.conn)

        # Agent A declares intent
        intent_id = log.intent("agent-A", "delete all checkpoints older than 7d")

        # Agent B votes
        log.vote("agent-B", intent_id, approve=True, reason="safe, matches retention policy")

        # Tally and decide
        summary  = log.tally(intent_id)
        decision = log.decide(intent_id, "agent-A")

        if decision.payload["passed"]:
            # ... do the work ...
            log.commit("agent-A", intent_id, summary="Removed 42 old checkpoints")
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    # ── Internal ──────────────────────────────────────────────────────

    def _next_position(self) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(position), -1) + 1 FROM shared_log"
        ).fetchone()
        return row[0]

    def _append(
        self,
        type: str,
        agent_id: str,
        payload: dict[str, Any],
        ref_id: int | None = None,
    ) -> LogEntry:
        if type not in LOG_TYPES:
            raise ValueError(f"type must be one of {LOG_TYPES!r}, got {type!r}")

        position = self._next_position()
        cur = self._conn.execute(
            """
            INSERT INTO shared_log (position, type, agent_id, ref_id, payload)
            VALUES (?, ?, ?, ?, ?)
            """,
            (position, type, agent_id, ref_id, json.dumps(payload)),
        )
        self._conn.commit()
        log_id = cur.lastrowid
        row = self._conn.execute(
            "SELECT * FROM shared_log WHERE log_id = ?", (log_id,)
        ).fetchone()
        return LogEntry.from_row(row)

    # ── Core API ─────────────────────────────────────────────────────

    def append(
        self,
        agent_id: str,
        type: str,
        payload: dict[str, Any] | None = None,
        ref_id: int | None = None,
    ) -> LogEntry:
        """Low-level: append any entry type to the log.

        Prefer the typed helpers (intent, vote, commit, etc.) for structured use.
        """
        return self._append(type, agent_id, payload or {}, ref_id)

    # ── LogAct Typed Helpers ──────────────────────────────────────────

    def intent(
        self,
        agent_id: str,
        action: str,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Broadcast an intent and return its log_id (used as the intent reference)."""
        entry = self._append(
            "intent",
            agent_id,
            {"action": action, **(metadata or {})},
        )
        return entry.log_id

    def vote(
        self,
        agent_id: str,
        intent_id: int,
        approve: bool,
        reason: str = "",
    ) -> LogEntry:
        """Cast a vote on an intent.

        Args:
            agent_id:  Voting agent.
            intent_id: log_id of the intent being voted on.
            approve:   True = approve, False = reject.
            reason:    Optional free-text rationale.
        """
        return self._append(
            "vote",
            agent_id,
            {"approve": approve, "reason": reason},
            ref_id=intent_id,
        )

    def tally(self, intent_id: int) -> VoteSummary:
        """Count votes on an intent (does not mutate the log)."""
        rows = self._conn.execute(
            """
            SELECT * FROM shared_log
            WHERE type = 'vote' AND ref_id = ?
            ORDER BY position
            """,
            (intent_id,),
        ).fetchall()
        votes = [LogEntry.from_row(r) for r in rows]
        approve = sum(1 for v in votes if v.payload.get("approve"))
        reject = sum(1 for v in votes if not v.payload.get("approve"))
        abstain = len(votes) - approve - reject
        return VoteSummary(
            intent_id=intent_id,
            approve=approve,
            reject=reject,
            abstain=abstain,
            votes=votes,
        )

    def decide(self, intent_id: int, agent_id: str) -> LogEntry:
        """Record a decision entry based on current vote tally.

        Idempotent: if a decision already exists for this intent, returns it.
        """
        existing = self._conn.execute(
            "SELECT * FROM shared_log WHERE type = 'decision' AND ref_id = ? LIMIT 1",
            (intent_id,),
        ).fetchone()
        if existing:
            return LogEntry.from_row(existing)

        summary = self.tally(intent_id)
        return self._append(
            "decision",
            agent_id,
            {
                "passed": summary.passed,
                "approve": summary.approve,
                "reject": summary.reject,
                "abstain": summary.abstain,
            },
            ref_id=intent_id,
        )

    def commit(
        self,
        agent_id: str,
        intent_id: int,
        summary: str,
        metadata: dict[str, Any] | None = None,
    ) -> LogEntry:
        """Record that an intent was executed successfully."""
        return self._append(
            "commit",
            agent_id,
            {"summary": summary, **(metadata or {})},
            ref_id=intent_id,
        )

    def result(
        self,
        agent_id: str,
        ref_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> LogEntry:
        """Record a final artefact or output."""
        return self._append("result", agent_id, payload or {}, ref_id=ref_id)

    def abort(
        self,
        agent_id: str,
        ref_id: int,
        reason: str = "",
    ) -> LogEntry:
        """Record that an intent or action was cancelled."""
        return self._append("abort", agent_id, {"reason": reason}, ref_id=ref_id)

    def policy(
        self,
        agent_id: str,
        rule: str,
        metadata: dict[str, Any] | None = None,
    ) -> LogEntry:
        """Inject a standing policy rule (supervisor / human-in-the-loop)."""
        return self._append("policy", agent_id, {"rule": rule, **(metadata or {})})

    def mail(
        self,
        from_agent: str,
        to_agent: str,
        message: str,
        ref_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LogEntry:
        """Send a direct async message to another agent."""
        return self._append(
            "mail",
            from_agent,
            {"to": to_agent, "message": message, **(metadata or {})},
            ref_id=ref_id,
        )

    # ── Read ──────────────────────────────────────────────────────────

    def read(
        self,
        since_position: int = 0,
        limit: int = 100,
        type: str | None = None,
        agent_id: str | None = None,
    ) -> list[LogEntry]:
        """Read entries from the log in position order.

        Args:
            since_position: Start reading from this position (inclusive).
            limit:          Max entries to return.
            type:           Optional filter by entry type.
            agent_id:       Optional filter by agent.
        """
        clauses = ["position >= ?"]
        params: list[Any] = [since_position]

        if type:
            clauses.append("type = ?")
            params.append(type)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)

        where = "WHERE " + " AND ".join(clauses)
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT * FROM shared_log {where} ORDER BY position LIMIT ?",
            params,
        ).fetchall()
        return [LogEntry.from_row(r) for r in rows]

    def tail(self, n: int = 20) -> list[LogEntry]:
        """Return the last n entries in chronological order."""
        rows = self._conn.execute(
            """
            SELECT * FROM (
                SELECT * FROM shared_log ORDER BY position DESC LIMIT ?
            ) ORDER BY position ASC
            """,
            (n,),
        ).fetchall()
        return [LogEntry.from_row(r) for r in rows]

    def get(self, log_id: int) -> LogEntry | None:
        """Fetch a single entry by log_id."""
        row = self._conn.execute(
            "SELECT * FROM shared_log WHERE log_id = ?", (log_id,)
        ).fetchone()
        return LogEntry.from_row(row) if row else None

    def thread(self, root_id: int) -> list[LogEntry]:
        """Return all entries that reference a root log_id (votes, commits, etc.)."""
        rows = self._conn.execute(
            """
            SELECT * FROM shared_log
            WHERE log_id = ? OR ref_id = ?
            ORDER BY position
            """,
            (root_id, root_id),
        ).fetchall()
        return [LogEntry.from_row(r) for r in rows]

    # ── Stats ─────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return per-type counts and total entries."""
        rows = self._conn.execute(
            "SELECT type, COUNT(*) AS n FROM shared_log GROUP BY type"
        ).fetchall()
        total = self._conn.execute("SELECT COUNT(*) FROM shared_log").fetchone()[0]
        return {
            "total": total,
            "by_type": {r["type"]: r["n"] for r in rows},
        }
