"""Checkpoint and restore system for agent time-travel debugging."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import ulid


class CheckpointManager:
    """Manages agent checkpoints for snapshot and restore."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def create(
        self,
        agent_id: str,
        event_id: int | None = None,
        label: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a checkpoint capturing the agent's current file and state snapshots."""
        checkpoint_id = str(ulid.new())

        # Capture file manifest
        files = self.conn.execute(
            "SELECT path, content_hash, version FROM files "
            "WHERE agent_id = ? AND deleted = 0 "
            "ORDER BY path",
            (agent_id,),
        ).fetchall()
        file_manifest = [
            {"path": f[0], "content_hash": f[1], "version": f[2]} for f in files
        ]

        # Capture state snapshot
        state_rows = self.conn.execute(
            "SELECT key, value FROM state WHERE agent_id = ?", (agent_id,)
        ).fetchall()
        state_snapshot = {r[0]: json.loads(r[1]) for r in state_rows}

        self.conn.execute(
            "INSERT INTO checkpoints "
            "(checkpoint_id, agent_id, label, event_id, file_manifest, state_snapshot, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                checkpoint_id,
                agent_id,
                label,
                event_id,
                json.dumps(file_manifest),
                json.dumps(state_snapshot),
                json.dumps(metadata or {}),
            ),
        )
        return checkpoint_id

    def restore(self, agent_id: str, checkpoint_id: str) -> None:
        """Restore an agent to a previous checkpoint state."""
        row = self.conn.execute(
            "SELECT file_manifest, state_snapshot FROM checkpoints "
            "WHERE checkpoint_id = ? AND agent_id = ?",
            (checkpoint_id, agent_id),
        ).fetchone()

        if not row:
            raise ValueError(f"Checkpoint {checkpoint_id} not found for agent {agent_id}")

        file_manifest = json.loads(row[0])
        state_snapshot = json.loads(row[1])

        # Soft-delete all current files
        self.conn.execute(
            "UPDATE files SET deleted = 1 WHERE agent_id = ? AND deleted = 0",
            (agent_id,),
        )

        # Restore files from manifest
        for entry in file_manifest:
            # Check if we have this exact version already
            existing = self.conn.execute(
                "SELECT file_id FROM files "
                "WHERE agent_id = ? AND path = ? AND version = ?",
                (agent_id, entry["path"], entry["version"]),
            ).fetchone()

            if existing:
                # Un-delete it
                self.conn.execute(
                    "UPDATE files SET deleted = 0 WHERE file_id = ?", (existing[0],)
                )
            else:
                # Get the size from the blob
                size_row = self.conn.execute(
                    "SELECT LENGTH(content) FROM blobs WHERE content_hash = ?",
                    (entry["content_hash"],),
                ).fetchone()
                size = size_row[0] if size_row else 0

                self.conn.execute(
                    "INSERT INTO files (agent_id, path, content_hash, size, version, deleted) "
                    "VALUES (?, ?, ?, ?, ?, 0)",
                    (agent_id, entry["path"], entry["content_hash"], size, entry["version"]),
                )

        # Restore state — clear current and insert snapshot
        self.conn.execute("DELETE FROM state WHERE agent_id = ?", (agent_id,))
        for key, value in state_snapshot.items():
            self.conn.execute(
                "INSERT INTO state (agent_id, key, value) VALUES (?, ?, ?)",
                (agent_id, key, json.dumps(value)),
            )

    def list(self, agent_id: str) -> list[dict]:
        """List all checkpoints for an agent."""
        rows = self.conn.execute(
            "SELECT checkpoint_id, label, created_at, event_id, metadata "
            "FROM checkpoints WHERE agent_id = ? ORDER BY created_at",
            (agent_id,),
        ).fetchall()
        return [
            {
                "checkpoint_id": r[0],
                "label": r[1],
                "created_at": r[2],
                "event_id": r[3],
                "metadata": json.loads(r[4]),
            }
            for r in rows
        ]

    def diff(self, agent_id: str, from_cp: str, to_cp: str) -> dict:
        """Compare two checkpoints, returning file and state diffs."""
        from_row = self.conn.execute(
            "SELECT file_manifest, state_snapshot FROM checkpoints "
            "WHERE checkpoint_id = ? AND agent_id = ?",
            (from_cp, agent_id),
        ).fetchone()
        to_row = self.conn.execute(
            "SELECT file_manifest, state_snapshot FROM checkpoints "
            "WHERE checkpoint_id = ? AND agent_id = ?",
            (to_cp, agent_id),
        ).fetchone()

        if not from_row or not to_row:
            raise ValueError("One or both checkpoints not found")

        from_files = {f["path"]: f for f in json.loads(from_row[0])}
        to_files = {f["path"]: f for f in json.loads(to_row[0])}
        from_state = json.loads(from_row[1])
        to_state = json.loads(to_row[1])

        # File diff
        added = [p for p in to_files if p not in from_files]
        removed = [p for p in from_files if p not in to_files]
        modified = [
            p
            for p in to_files
            if p in from_files and to_files[p]["content_hash"] != from_files[p]["content_hash"]
        ]

        # State diff
        state_added = {k: v for k, v in to_state.items() if k not in from_state}
        state_removed = {k: v for k, v in from_state.items() if k not in to_state}
        state_modified = {
            k: {"from": from_state[k], "to": to_state[k]}
            for k in to_state
            if k in from_state and to_state[k] != from_state[k]
        }

        # Tool calls between checkpoints
        from_event = self.conn.execute(
            "SELECT event_id FROM checkpoints WHERE checkpoint_id = ?", (from_cp,)
        ).fetchone()[0]
        to_event = self.conn.execute(
            "SELECT event_id FROM checkpoints WHERE checkpoint_id = ?", (to_cp,)
        ).fetchone()[0]

        tool_calls = []
        if from_event and to_event:
            rows = self.conn.execute(
                "SELECT call_id, tool_name, status, duration_ms, token_count "
                "FROM tool_calls WHERE agent_id = ? "
                "AND started_at >= (SELECT timestamp FROM events WHERE event_id = ?) "
                "AND started_at <= (SELECT timestamp FROM events WHERE event_id = ?)",
                (agent_id, from_event, to_event),
            ).fetchall()
            tool_calls = [
                {
                    "call_id": r[0],
                    "tool_name": r[1],
                    "status": r[2],
                    "duration_ms": r[3],
                    "token_count": r[4],
                }
                for r in rows
            ]

        return {
            "files": {"added": added, "removed": removed, "modified": modified},
            "state": {
                "added": state_added,
                "removed": state_removed,
                "modified": state_modified,
            },
            "tool_calls": tool_calls,
        }
