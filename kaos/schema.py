"""SQLite schema definitions and migrations for Kaos."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 3

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

# Migration to v2: cross-agent memory (FTS5) + shared log (LogAct)
MIGRATION_V2_SQL = """
-- Cross-Agent Memory Store (inspired by claude-mem / thedotmack)
CREATE TABLE IF NOT EXISTS memory (
    memory_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    type        TEXT NOT NULL DEFAULT 'observation'
                CHECK (type IN ('observation','result','skill','insight','error')),
    key         TEXT,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE INDEX IF NOT EXISTS idx_memory_agent ON memory(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_memory_type  ON memory(type);
CREATE INDEX IF NOT EXISTS idx_memory_key   ON memory(key) WHERE key IS NOT NULL;

-- FTS5 full-text search index over memory
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(
    content,
    key,
    type        UNINDEXED,
    agent_id    UNINDEXED,
    memory_id   UNINDEXED,
    created_at  UNINDEXED,
    tokenize    = 'porter unicode61'
);

-- Keep FTS in sync with memory table
CREATE TRIGGER IF NOT EXISTS memory_fts_insert
AFTER INSERT ON memory BEGIN
    INSERT INTO memory_fts(rowid, content, key, type, agent_id, memory_id, created_at)
    VALUES (NEW.memory_id, NEW.content, NEW.key, NEW.type, NEW.agent_id, NEW.memory_id, NEW.created_at);
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_delete
AFTER DELETE ON memory BEGIN
    DELETE FROM memory_fts WHERE rowid = OLD.memory_id;
END;

CREATE TRIGGER IF NOT EXISTS memory_fts_update
AFTER UPDATE OF content, key ON memory BEGIN
    DELETE FROM memory_fts WHERE rowid = OLD.memory_id;
    INSERT INTO memory_fts(rowid, content, key, type, agent_id, memory_id, created_at)
    VALUES (NEW.memory_id, NEW.content, NEW.key, NEW.type, NEW.agent_id, NEW.memory_id, NEW.created_at);
END;

-- Shared Append-Only Log (inspired by LogAct / Balakrishnan et al. 2026, arXiv:2604.07988)
CREATE TABLE IF NOT EXISTS shared_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    position    INTEGER UNIQUE NOT NULL,
    type        TEXT NOT NULL
                CHECK (type IN ('intent','vote','decision','commit','result','abort','policy','mail')),
    agent_id    TEXT NOT NULL,
    ref_id      INTEGER REFERENCES shared_log(log_id),
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE INDEX IF NOT EXISTS idx_shared_log_type     ON shared_log(type, created_at);
CREATE INDEX IF NOT EXISTS idx_shared_log_agent    ON shared_log(agent_id, created_at);
CREATE INDEX IF NOT EXISTS idx_shared_log_ref      ON shared_log(ref_id) WHERE ref_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_shared_log_position ON shared_log(position);
"""


# Migration to v3: cross-agent skill library (Externalization / arXiv:2604.08224)
MIGRATION_V3_SQL = """
-- Cross-Agent Skill Library (inspired by Zhou et al. 2026, arXiv:2604.08224)
-- Skills are procedural templates — distinct from episodic memory entries.
-- Agents save reliable solution patterns; any agent can search and apply them.
CREATE TABLE IF NOT EXISTS agent_skills (
    skill_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    template        TEXT NOT NULL,
    tags            TEXT NOT NULL DEFAULT '[]',
    source_agent_id TEXT REFERENCES agents(agent_id),
    use_count       INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE INDEX IF NOT EXISTS idx_agent_skills_source ON agent_skills(source_agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_skills_name   ON agent_skills(name);

-- FTS5 full-text search over name, description, tags, and template
CREATE VIRTUAL TABLE IF NOT EXISTS agent_skills_fts USING fts5(
    name,
    description,
    tags,
    template,
    content     = 'agent_skills',
    content_rowid = 'skill_id',
    tokenize    = 'porter unicode61'
);

-- Keep FTS in sync
CREATE TRIGGER IF NOT EXISTS agent_skills_fts_insert
AFTER INSERT ON agent_skills BEGIN
    INSERT INTO agent_skills_fts(rowid, name, description, tags, template)
    VALUES (NEW.skill_id, NEW.name, NEW.description, NEW.tags, NEW.template);
END;

CREATE TRIGGER IF NOT EXISTS agent_skills_fts_delete
AFTER DELETE ON agent_skills BEGIN
    DELETE FROM agent_skills_fts WHERE rowid = OLD.skill_id;
END;

CREATE TRIGGER IF NOT EXISTS agent_skills_fts_update
AFTER UPDATE OF name, description, tags, template ON agent_skills BEGIN
    DELETE FROM agent_skills_fts WHERE rowid = OLD.skill_id;
    INSERT INTO agent_skills_fts(rowid, name, description, tags, template)
    VALUES (NEW.skill_id, NEW.name, NEW.description, NEW.tags, NEW.template);
END;
"""


def init_schema(conn: sqlite3.Connection) -> None:
    """Initialize the database schema, applying migrations if needed."""
    conn.executescript(SCHEMA_SQL)

    current = conn.execute(
        "SELECT MAX(version) FROM schema_version"
    ).fetchone()[0]

    if current is None:
        # Brand-new DB: apply all migrations up front then stamp version
        conn.executescript(MIGRATION_V2_SQL)
        conn.executescript(MIGRATION_V3_SQL)
        conn.execute(
            "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
        )
        conn.commit()
    elif current < SCHEMA_VERSION:
        _apply_migrations(conn, current, SCHEMA_VERSION)


def _apply_migrations(conn: sqlite3.Connection, from_version: int, to_version: int) -> None:
    """Apply incremental schema migrations."""
    if from_version < 2:
        conn.executescript(MIGRATION_V2_SQL)
    if from_version < 3:
        conn.executescript(MIGRATION_V3_SQL)
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)", (to_version,)
    )
    conn.commit()
