"""Kaos VFS Engine — the core of the agentic filesystem framework."""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import PurePosixPath
from typing import Any

import ulid

from kaos.blobs import BlobStore
from kaos.checkpoints import CheckpointManager
from kaos.events import EventJournal
from kaos.schema import init_schema


class Kaos:
    """
    One instance per .db file. Thread-safe via SQLite WAL mode.

    Provides isolated virtual filesystems, state management, tool call tracking,
    checkpoint/restore, and a full audit trail — all backed by a single SQLite file.
    """

    def __init__(self, db_path: str = "agents.db", compression: str = "zstd"):
        self.db_path = db_path
        self._local = threading.local()
        self._compression = compression

        # Initialize with a primary connection
        conn = self._get_conn()
        init_schema(conn)

        self.blobs = BlobStore(conn, compression=compression)
        self.events = EventJournal(conn)
        self.checkpoints = CheckpointManager(conn)

    def _get_conn(self) -> sqlite3.Connection:
        """Get a thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self.db_path, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("PRAGMA wal_autocheckpoint=100")
            self._local.conn = conn
        return self._local.conn

    def _open_fresh_conn(self, timeout: float = 30.0) -> sqlite3.Connection:
        """Open a brand-new connection (not thread-local) for recovery operations."""
        conn = sqlite3.connect(self.db_path, timeout=timeout, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
        return conn

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    # ── Agent Lifecycle ──────────────────────────────────────────────

    def spawn(
        self,
        name: str,
        config: dict | None = None,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """Create a new agent with an isolated virtual filesystem. Returns agent_id.

        Retries on OperationalError (database locked) to handle concurrent spawns.
        """
        agent_id = str(ulid.new())
        for attempt in range(3):
            try:
                self.conn.execute(
                    "INSERT INTO agents (agent_id, name, parent_id, config, metadata) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        agent_id,
                        name,
                        parent_id,
                        json.dumps(config or {}),
                        json.dumps(metadata or {}),
                    ),
                )
                self.conn.execute(
                    "INSERT INTO files (agent_id, path, is_dir) VALUES (?, '/', 1)",
                    (agent_id,),
                )
                self.events.log(
                    agent_id,
                    EventJournal.AGENT_SPAWN,
                    {"name": name, "parent_id": parent_id, "config": config or {}},
                )
                self.conn.commit()
                break
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() and attempt < 2:
                    import time
                    time.sleep(0.5 * (attempt + 1))
                    continue
                raise
        return agent_id

    def set_status(self, agent_id: str, status: str, pid: int | None = None) -> None:
        """Update an agent's status."""
        self._assert_agent_exists(agent_id)
        old_status = self.status(agent_id)["status"]
        updates = ["status = ?"]
        params: list[Any] = [status]
        if pid is not None:
            updates.append("pid = ?")
            params.append(pid)
        if status == "running":
            updates.append("last_heartbeat = strftime('%Y-%m-%dT%H:%M:%f', 'now')")
        params.append(agent_id)
        self.conn.execute(
            f"UPDATE agents SET {', '.join(updates)} WHERE agent_id = ?", params
        )
        self.events.log(
            agent_id,
            EventJournal.STATE_CHANGE,
            {"field": "status", "from": old_status, "to": status},
        )
        self.conn.commit()

    def pause(self, agent_id: str) -> None:
        """Pause a running agent."""
        self.set_status(agent_id, "paused")
        self.events.log(agent_id, EventJournal.AGENT_PAUSE)
        self.conn.commit()

    def resume(self, agent_id: str) -> None:
        """Resume a paused agent."""
        self.set_status(agent_id, "running")
        self.events.log(agent_id, EventJournal.AGENT_RESUME)
        self.conn.commit()

    def kill(self, agent_id: str) -> None:
        """Kill an agent. Falls back to a fresh connection if the DB is locked."""
        try:
            self.set_status(agent_id, "killed")
            self.events.log(agent_id, EventJournal.AGENT_KILL)
            self.conn.commit()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            # Thread-local connection is blocked — try a fresh one
            self._force_kill(agent_id)

    def _force_kill(self, agent_id: str) -> None:
        """Kill via a fresh connection after a WAL checkpoint attempt."""
        conn = self._open_fresh_conn(timeout=30.0)
        try:
            conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
            conn.execute(
                "UPDATE agents SET status='killed' WHERE agent_id=?", (agent_id,)
            )
            conn.execute(
                "INSERT INTO events (agent_id, event_type, payload) VALUES (?, 'agent_kill', '{}')",
                (agent_id,),
            )
            conn.commit()
        finally:
            conn.close()

    def complete(self, agent_id: str) -> None:
        """Mark an agent as completed."""
        self.set_status(agent_id, "completed")
        self.events.log(agent_id, EventJournal.AGENT_COMPLETE)
        self.conn.commit()

    def fail(self, agent_id: str, error: str | None = None) -> None:
        """Mark an agent as failed."""
        self.set_status(agent_id, "failed")
        self.events.log(agent_id, EventJournal.AGENT_FAIL, {"error": error})
        self.conn.commit()

    def status(self, agent_id: str) -> dict:
        """Get full status of an agent."""
        row = self.conn.execute(
            "SELECT agent_id, name, parent_id, created_at, status, config, metadata, pid, last_heartbeat "
            "FROM agents WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        if not row:
            raise ValueError(f"Agent not found: {agent_id}")
        return {
            "agent_id": row[0],
            "name": row[1],
            "parent_id": row[2],
            "created_at": row[3],
            "status": row[4],
            "config": json.loads(row[5]),
            "metadata": json.loads(row[6]),
            "pid": row[7],
            "last_heartbeat": row[8],
        }

    def list_agents(self, status_filter: str | None = None) -> list[dict]:
        """List all agents, optionally filtered by status."""
        if status_filter:
            rows = self.conn.execute(
                "SELECT agent_id, name, status, created_at FROM agents WHERE status = ? ORDER BY created_at",
                (status_filter,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT agent_id, name, status, created_at FROM agents ORDER BY created_at"
            ).fetchall()
        return [
            {"agent_id": r[0], "name": r[1], "status": r[2], "created_at": r[3]}
            for r in rows
        ]

    def heartbeat(self, agent_id: str) -> None:
        """Update the agent's heartbeat timestamp."""
        self.conn.execute(
            "UPDATE agents SET last_heartbeat = strftime('%Y-%m-%dT%H:%M:%f', 'now') "
            "WHERE agent_id = ?",
            (agent_id,),
        )
        self.conn.commit()

    # ── Filesystem Operations ────────────────────────────────────────

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize a path to a canonical POSIX form."""
        p = PurePosixPath("/" + path.strip("/"))
        return str(p)

    def read(self, agent_id: str, path: str) -> bytes:
        """Read a file from an agent's virtual filesystem."""
        path = self._normalize_path(path)
        row = self.conn.execute(
            "SELECT content_hash FROM files "
            "WHERE agent_id = ? AND path = ? AND deleted = 0 AND is_dir = 0 "
            "ORDER BY version DESC LIMIT 1",
            (agent_id, path),
        ).fetchone()

        if not row:
            raise FileNotFoundError(f"{agent_id}:{path}")

        self.events.log(agent_id, EventJournal.FILE_READ, {"path": path})
        return self.blobs.retrieve(row[0])

    def write(self, agent_id: str, path: str, content: bytes) -> None:
        """Write a file to an agent's virtual filesystem."""
        self._assert_agent_exists(agent_id)
        path = self._normalize_path(path)

        # Ensure parent directories exist
        self._ensure_parents(agent_id, path)

        content_hash, size = self.blobs.store(content)

        # Get current version
        current = self.conn.execute(
            "SELECT MAX(version), content_hash FROM files "
            "WHERE agent_id = ? AND path = ? AND deleted = 0",
            (agent_id, path),
        ).fetchone()

        if current and current[0] is not None:
            new_version = current[0] + 1
            # Soft-delete old version (keep blob for history/checkpoint restore)
            self.conn.execute(
                "UPDATE files SET deleted = 1 WHERE agent_id = ? AND path = ? AND deleted = 0",
                (agent_id, path),
            )
        else:
            new_version = 1

        self.conn.execute(
            "INSERT INTO files (agent_id, path, content_hash, size, version) "
            "VALUES (?, ?, ?, ?, ?)",
            (agent_id, path, content_hash, size, new_version),
        )

        self.events.log(
            agent_id,
            EventJournal.FILE_WRITE,
            {"path": path, "size": size, "version": new_version},
        )
        self.conn.commit()

    def delete(self, agent_id: str, path: str) -> None:
        """Soft-delete a file from an agent's virtual filesystem."""
        path = self._normalize_path(path)
        row = self.conn.execute(
            "SELECT content_hash FROM files "
            "WHERE agent_id = ? AND path = ? AND deleted = 0 AND is_dir = 0",
            (agent_id, path),
        ).fetchone()

        if not row:
            raise FileNotFoundError(f"{agent_id}:{path}")

        # Soft-delete only — keep blob for history/checkpoint restore
        self.conn.execute(
            "UPDATE files SET deleted = 1 WHERE agent_id = ? AND path = ? AND deleted = 0",
            (agent_id, path),
        )
        self.events.log(agent_id, EventJournal.FILE_DELETE, {"path": path})
        self.conn.commit()

    def ls(self, agent_id: str, path: str = "/") -> list[dict]:
        """List files and directories at a path."""
        path = self._normalize_path(path)
        prefix = path.rstrip("/") + "/"
        if path == "/":
            prefix = "/"

        rows = self.conn.execute(
            "SELECT path, is_dir, size, modified_at, version FROM files "
            "WHERE agent_id = ? AND deleted = 0 "
            "AND path LIKE ? AND path != ? "
            "AND path NOT LIKE ? "
            "ORDER BY path",
            (agent_id, prefix + "%", path, prefix + "%/%"),
        ).fetchall()

        return [
            {
                "path": r[0],
                "name": PurePosixPath(r[0]).name,
                "is_dir": bool(r[1]),
                "size": r[2],
                "modified_at": r[3],
                "version": r[4],
            }
            for r in rows
        ]

    def stat(self, agent_id: str, path: str) -> dict:
        """Get file metadata."""
        path = self._normalize_path(path)
        row = self.conn.execute(
            "SELECT path, is_dir, size, mode, created_at, modified_at, version, content_hash "
            "FROM files WHERE agent_id = ? AND path = ? AND deleted = 0 "
            "ORDER BY version DESC LIMIT 1",
            (agent_id, path),
        ).fetchone()

        if not row:
            raise FileNotFoundError(f"{agent_id}:{path}")

        return {
            "path": row[0],
            "is_dir": bool(row[1]),
            "size": row[2],
            "mode": row[3],
            "created_at": row[4],
            "modified_at": row[5],
            "version": row[6],
            "content_hash": row[7],
        }

    def exists(self, agent_id: str, path: str) -> bool:
        """Check if a file or directory exists."""
        path = self._normalize_path(path)
        row = self.conn.execute(
            "SELECT 1 FROM files WHERE agent_id = ? AND path = ? AND deleted = 0 LIMIT 1",
            (agent_id, path),
        ).fetchone()
        return row is not None

    def mkdir(self, agent_id: str, path: str) -> None:
        """Create a directory."""
        self._assert_agent_exists(agent_id)
        path = self._normalize_path(path)
        if self.exists(agent_id, path):
            return
        self._ensure_parents(agent_id, path)
        self.conn.execute(
            "INSERT INTO files (agent_id, path, is_dir) VALUES (?, ?, 1)",
            (agent_id, path),
        )
        self.conn.commit()

    def _ensure_parents(self, agent_id: str, path: str) -> None:
        """Recursively create parent directories if they don't exist."""
        parts = PurePosixPath(path).parts
        for i in range(1, len(parts)):
            parent = str(PurePosixPath(*parts[:i]))
            if parent == ".":
                parent = "/"
            if not self.exists(agent_id, parent):
                self.conn.execute(
                    "INSERT OR IGNORE INTO files (agent_id, path, is_dir) VALUES (?, ?, 1)",
                    (agent_id, parent),
                )

    def file_history(self, agent_id: str, path: str) -> list[dict]:
        """Get version history for a file."""
        path = self._normalize_path(path)
        rows = self.conn.execute(
            "SELECT version, content_hash, size, created_at, modified_at, deleted "
            "FROM files WHERE agent_id = ? AND path = ? ORDER BY version",
            (agent_id, path),
        ).fetchall()
        return [
            {
                "version": r[0],
                "content_hash": r[1],
                "size": r[2],
                "created_at": r[3],
                "modified_at": r[4],
                "deleted": bool(r[5]),
            }
            for r in rows
        ]

    # ── State Management ─────────────────────────────────────────────

    def get_state(self, agent_id: str, key: str) -> Any:
        """Get a state value for an agent."""
        row = self.conn.execute(
            "SELECT value FROM state WHERE agent_id = ? AND key = ?",
            (agent_id, key),
        ).fetchone()
        if not row:
            raise KeyError(f"State key not found: {agent_id}:{key}")
        return json.loads(row[0])

    def get_state_or(self, agent_id: str, key: str, default: Any = None) -> Any:
        """Get a state value with a default fallback."""
        try:
            return self.get_state(agent_id, key)
        except KeyError:
            return default

    def set_state(self, agent_id: str, key: str, value: Any) -> None:
        """Set a state value for an agent (upsert)."""
        self._assert_agent_exists(agent_id)
        self.conn.execute(
            "INSERT INTO state (agent_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(agent_id, key) DO UPDATE SET value = excluded.value, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%f', 'now')",
            (agent_id, key, json.dumps(value)),
        )
        self.conn.commit()

    def delete_state(self, agent_id: str, key: str) -> None:
        """Delete a state key."""
        self.conn.execute(
            "DELETE FROM state WHERE agent_id = ? AND key = ?",
            (agent_id, key),
        )
        self.conn.commit()

    def get_all_state(self, agent_id: str) -> dict:
        """Get all state key-value pairs for an agent."""
        rows = self.conn.execute(
            "SELECT key, value FROM state WHERE agent_id = ?", (agent_id,)
        ).fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}

    # ── Tool Call Tracking ───────────────────────────────────────────

    def log_tool_call(
        self,
        agent_id: str,
        tool_name: str,
        input_data: dict,
        parent_call_id: str | None = None,
    ) -> str:
        """Log a tool call. Returns call_id."""
        call_id = str(ulid.new())
        self.conn.execute(
            "INSERT INTO tool_calls (call_id, agent_id, tool_name, input, status, parent_call_id) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (call_id, agent_id, tool_name, json.dumps(input_data), parent_call_id),
        )
        self.events.log(
            agent_id,
            EventJournal.TOOL_CALL_START,
            {"call_id": call_id, "tool_name": tool_name},
        )
        self.conn.commit()
        return call_id

    def start_tool_call(self, call_id: str) -> None:
        """Mark a tool call as running."""
        self.conn.execute(
            "UPDATE tool_calls SET status = 'running', "
            "started_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') "
            "WHERE call_id = ?",
            (call_id,),
        )
        self.conn.commit()

    def complete_tool_call(
        self,
        call_id: str,
        output: dict,
        status: str = "success",
        token_count: int | None = None,
        error_message: str | None = None,
    ) -> None:
        """Complete a tool call with results."""
        self.conn.execute(
            "UPDATE tool_calls SET output = ?, status = ?, "
            "completed_at = strftime('%Y-%m-%dT%H:%M:%f', 'now'), "
            "duration_ms = CAST((julianday(strftime('%Y-%m-%dT%H:%M:%f', 'now')) - "
            "julianday(started_at)) * 86400000 AS INTEGER), "
            "token_count = ?, error_message = ? "
            "WHERE call_id = ?",
            (json.dumps(output), status, token_count, error_message, call_id),
        )

        # Get agent_id for event logging
        row = self.conn.execute(
            "SELECT agent_id FROM tool_calls WHERE call_id = ?", (call_id,)
        ).fetchone()
        if row:
            self.events.log(
                row[0],
                EventJournal.TOOL_CALL_END,
                {"call_id": call_id, "status": status},
            )
        self.conn.commit()

    def get_tool_calls(
        self,
        agent_id: str,
        tool_name: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        """Query tool calls for an agent."""
        query = (
            "SELECT call_id, tool_name, input, output, status, "
            "started_at, completed_at, duration_ms, token_count, error_message "
            "FROM tool_calls WHERE agent_id = ?"
        )
        params: list[Any] = [agent_id]
        if tool_name:
            query += " AND tool_name = ?"
            params.append(tool_name)
        if status:
            query += " AND status = ?"
            params.append(status)
        query += " ORDER BY started_at DESC LIMIT ?"
        params.append(limit)

        rows = self.conn.execute(query, params).fetchall()
        return [
            {
                "call_id": r[0],
                "tool_name": r[1],
                "input": json.loads(r[2]),
                "output": json.loads(r[3]) if r[3] else None,
                "status": r[4],
                "started_at": r[5],
                "completed_at": r[6],
                "duration_ms": r[7],
                "token_count": r[8],
                "error_message": r[9],
            }
            for r in rows
        ]

    # ── Checkpoints ──────────────────────────────────────────────────

    def checkpoint(self, agent_id: str, label: str | None = None) -> str:
        """Create a checkpoint of the agent's current state."""
        self._assert_agent_exists(agent_id)
        event_id = self.events.get_latest_event_id(agent_id)
        cp_id = self.checkpoints.create(agent_id, event_id=event_id, label=label)
        self.events.log(
            agent_id,
            EventJournal.CHECKPOINT_CREATE,
            {"checkpoint_id": cp_id, "label": label},
        )
        self.conn.commit()
        return cp_id

    def restore(self, agent_id: str, checkpoint_id: str) -> None:
        """Restore an agent to a previous checkpoint."""
        self._assert_agent_exists(agent_id)
        self.checkpoints.restore(agent_id, checkpoint_id)
        self.events.log(
            agent_id,
            EventJournal.CHECKPOINT_RESTORE,
            {"checkpoint_id": checkpoint_id},
        )
        self.conn.commit()

    def list_checkpoints(self, agent_id: str) -> list[dict]:
        """List all checkpoints for an agent."""
        return self.checkpoints.list(agent_id)

    def diff_checkpoints(self, agent_id: str, from_cp: str, to_cp: str) -> dict:
        """Diff two checkpoints."""
        return self.checkpoints.diff(agent_id, from_cp, to_cp)

    # ── Querying ─────────────────────────────────────────────────────

    def query(self, sql: str, params: tuple = ()) -> list[dict]:
        """Run a read-only SQL query against the agent database."""
        # Enforce read-only by checking for write keywords
        normalized = sql.strip().upper()
        if any(
            normalized.startswith(kw)
            for kw in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE")
        ):
            raise PermissionError("Only SELECT queries are allowed via query()")

        cursor = self.conn.execute(sql, params)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    # ── Internal Helpers ─────────────────────────────────────────────

    def _assert_agent_exists(self, agent_id: str) -> None:
        """Raise ValueError if agent doesn't exist."""
        row = self.conn.execute(
            "SELECT 1 FROM agents WHERE agent_id = ?", (agent_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Agent not found: {agent_id}")

    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
