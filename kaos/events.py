"""Append-only event journal for agent audit trails."""

from __future__ import annotations

import json
import sqlite3
from typing import Any


class EventJournal:
    """Append-only event log for full agent auditability."""

    # Standard event types
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    STATE_CHANGE = "state_change"
    AGENT_SPAWN = "agent_spawn"
    AGENT_PAUSE = "agent_pause"
    AGENT_RESUME = "agent_resume"
    AGENT_KILL = "agent_kill"
    AGENT_COMPLETE = "agent_complete"
    AGENT_FAIL = "agent_fail"
    CHECKPOINT_CREATE = "checkpoint_create"
    CHECKPOINT_RESTORE = "checkpoint_restore"
    ERROR = "error"
    WARNING = "warning"

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def log(self, agent_id: str, event_type: str, payload: dict[str, Any] | None = None) -> int:
        """Append an event to the journal. Returns the event_id."""
        cursor = self.conn.execute(
            "INSERT INTO events (agent_id, event_type, payload) VALUES (?, ?, ?)",
            (agent_id, event_type, json.dumps(payload or {})),
        )
        return cursor.lastrowid

    def get_events(
        self,
        agent_id: str,
        event_type: str | None = None,
        since: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query events for an agent with optional filters."""
        query = "SELECT event_id, agent_id, event_type, payload, timestamp FROM events WHERE agent_id = ?"
        params: list[Any] = [agent_id]

        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if since:
            query += " AND timestamp > ?"
            params.append(since)

        query += " ORDER BY event_id DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "event_id": r[0],
                "agent_id": r[1],
                "event_type": r[2],
                "payload": json.loads(r[3]),
                "timestamp": r[4],
            }
            for r in rows
        ]

    def get_latest_event_id(self, agent_id: str) -> int | None:
        """Get the most recent event_id for an agent (used for checkpoint watermarks)."""
        row = self.conn.execute(
            "SELECT MAX(event_id) FROM events WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        return row[0] if row else None

    def count(self, agent_id: str, event_type: str | None = None) -> int:
        """Count events for an agent."""
        if event_type:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE agent_id = ? AND event_type = ?",
                (agent_id, event_type),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) FROM events WHERE agent_id = ?", (agent_id,)
            ).fetchone()
        return row[0]
