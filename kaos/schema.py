"""SQLite schema definitions and migrations for Kaos."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 1

SCHEMA_SQL = """
-- Agent Registry
CREATE TABLE IF NOT EXISTS agents (
    agent_id        TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    parent_id       TEXT REFERENCES agents(agent_id),
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    status          TEXT NOT NULL DEFAULT 'initialized'
                    CHECK (status IN ('initialized','running','paused','completed','failed','killed')),
    config          TEXT NOT NULL DEFAULT '{}',
    metadata        TEXT NOT NULL DEFAULT '{}',
    pid             INTEGER,
    last_heartbeat  TEXT
);

CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_parent ON agents(parent_id);

-- Virtual Filesystem
CREATE TABLE IF NOT EXISTS files (
    file_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    path            TEXT NOT NULL,
    is_dir          INTEGER NOT NULL DEFAULT 0,
    content_hash    TEXT,
    size            INTEGER NOT NULL DEFAULT 0,
    mode            INTEGER NOT NULL DEFAULT 33188,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    modified_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    version         INTEGER NOT NULL DEFAULT 1,
    deleted         INTEGER NOT NULL DEFAULT 0,
    UNIQUE(agent_id, path, version)
);

CREATE INDEX IF NOT EXISTS idx_files_agent_path ON files(agent_id, path) WHERE deleted = 0;
CREATE INDEX IF NOT EXISTS idx_files_agent ON files(agent_id);

-- Content-Addressable Blob Store
CREATE TABLE IF NOT EXISTS blobs (
    content_hash    TEXT PRIMARY KEY,
    content         BLOB NOT NULL,
    compressed      INTEGER NOT NULL DEFAULT 0,
    ref_count       INTEGER NOT NULL DEFAULT 1
);

-- Tool Call Journal
CREATE TABLE IF NOT EXISTS tool_calls (
    call_id         TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    tool_name       TEXT NOT NULL,
    input           TEXT NOT NULL,
    output          TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','running','success','error','timeout')),
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    completed_at    TEXT,
    duration_ms     INTEGER,
    token_count     INTEGER,
    cost_usd        REAL DEFAULT 0.0,
    parent_call_id  TEXT REFERENCES tool_calls(call_id),
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_agent ON tool_calls(agent_id, started_at);
CREATE INDEX IF NOT EXISTS idx_tool_calls_tool ON tool_calls(tool_name);
CREATE INDEX IF NOT EXISTS idx_tool_calls_status ON tool_calls(status);

-- Agent State (KV Store)
CREATE TABLE IF NOT EXISTS state (
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    key             TEXT NOT NULL,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (agent_id, key)
);

-- Event Log (Append-Only Audit Trail)
CREATE TABLE IF NOT EXISTS events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_events_agent_time ON events(agent_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

-- Checkpoints (Time Travel)
CREATE TABLE IF NOT EXISTS checkpoints (
    checkpoint_id   TEXT PRIMARY KEY,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    label           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    event_id        INTEGER REFERENCES events(event_id),
    file_manifest   TEXT NOT NULL,
    state_snapshot  TEXT NOT NULL,
    metadata        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_checkpoints_agent ON checkpoints(agent_id, created_at);

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,
    applied_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    """Initialize the database schema, applying migrations if needed."""
    conn.executescript(SCHEMA_SQL)

    current = conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()[0]

    if current is None:
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        conn.commit()
    elif current < SCHEMA_VERSION:
        _apply_migrations(conn, current, SCHEMA_VERSION)


def _apply_migrations(conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
    """Apply incremental schema migrations."""
    # Future migrations go here as version increases
    # Example:
    # if from_version < 2:
    #     conn.execute("ALTER TABLE agents ADD COLUMN priority INTEGER DEFAULT 0")
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)", (to_version,)
    )
    conn.commit()
