"""SQLite schema definitions and migrations for Kaos."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 6

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


# Migration to v4: neuroplasticity substrate — usage telemetry + dream runs.
# Additive only. No existing tables changed. No behavior change until the
# caller opts in via `rank="weighted"` or invokes `kaos dream`.
MIGRATION_V4_SQL = """
-- Per-application record of a skill being used by an agent.
CREATE TABLE IF NOT EXISTS skill_uses (
    use_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    skill_id    INTEGER NOT NULL REFERENCES agent_skills(skill_id),
    agent_id    TEXT REFERENCES agents(agent_id),
    used_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    success     INTEGER,          -- NULL = unreported, 0/1 otherwise
    task_hash   TEXT              -- optional bucket id for per-context weighting
);

CREATE INDEX IF NOT EXISTS idx_skill_uses_skill  ON skill_uses(skill_id, used_at);
CREATE INDEX IF NOT EXISTS idx_skill_uses_agent  ON skill_uses(agent_id, used_at);

-- Per-retrieval record of a memory entry being searched for / surfaced.
CREATE TABLE IF NOT EXISTS memory_hits (
    hit_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_id   INTEGER NOT NULL REFERENCES memory(memory_id),
    agent_id    TEXT REFERENCES agents(agent_id),
    hit_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    query       TEXT,
    rank_pos    INTEGER           -- position in the result set (1-indexed)
);

CREATE INDEX IF NOT EXISTS idx_memory_hits_mem    ON memory_hits(memory_id, hit_at);
CREATE INDEX IF NOT EXISTS idx_memory_hits_agent  ON memory_hits(agent_id, hit_at);

-- One row per `kaos dream` invocation.
CREATE TABLE IF NOT EXISTS dream_runs (
    run_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    finished_at    TEXT,
    since_ts       TEXT,          -- --since parameter (null = all-time)
    mode           TEXT NOT NULL DEFAULT 'dry_run'
                   CHECK (mode IN ('dry_run','apply')),
    episodes       INTEGER NOT NULL DEFAULT 0,
    skills_scored  INTEGER NOT NULL DEFAULT 0,
    memories_scored INTEGER NOT NULL DEFAULT 0,
    digest_path    TEXT,
    phase_timings  TEXT NOT NULL DEFAULT '{}',
    summary        TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_dream_runs_started ON dream_runs(started_at);

-- Per-agent-run derived signals produced by the replay phase.
-- One row per agent completion. If the replay runs again against the same
-- event history the row is upserted (idempotent).
CREATE TABLE IF NOT EXISTS episode_signals (
    agent_id           TEXT PRIMARY KEY REFERENCES agents(agent_id),
    started_at         TEXT,
    ended_at           TEXT,
    status             TEXT,
    success            INTEGER,        -- 1 if status in (completed), 0 if failed/killed, NULL if running
    tool_calls_count   INTEGER NOT NULL DEFAULT 0,
    tool_calls_error   INTEGER NOT NULL DEFAULT 0,
    total_tokens       INTEGER NOT NULL DEFAULT 0,
    total_cost_usd     REAL    NOT NULL DEFAULT 0.0,
    duration_ms        INTEGER,
    skills_applied     INTEGER NOT NULL DEFAULT 0,
    memories_written   INTEGER NOT NULL DEFAULT 0,
    memories_retrieved INTEGER NOT NULL DEFAULT 0,
    checkpoints_made   INTEGER NOT NULL DEFAULT 0,
    last_computed_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE INDEX IF NOT EXISTS idx_episode_signals_success ON episode_signals(success);
"""


# Migration to v5: neuroplasticity mechanism — associations (Hebbian graph),
# failure fingerprints, auto-promoted shared-log policies, and a proposal
# journal for consolidation actions. All additive.
MIGRATION_V5_SQL = """
-- Hebbian co-occurrence graph.
-- One row per ordered pair (kind_a, id_a) -> (kind_b, id_b). We store both
-- directions so lookups are cheap.  `weight` is the decayed co-fire count,
-- `uses` is the raw unweighted count, `last_seen` drives decay on read.
CREATE TABLE IF NOT EXISTS associations (
    kind_a      TEXT NOT NULL,
    id_a        INTEGER NOT NULL,
    kind_b      TEXT NOT NULL,
    id_b        INTEGER NOT NULL,
    weight      REAL NOT NULL DEFAULT 1.0,
    uses        INTEGER NOT NULL DEFAULT 1,
    first_seen  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    last_seen   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    PRIMARY KEY (kind_a, id_a, kind_b, id_b)
);

CREATE INDEX IF NOT EXISTS idx_associations_a ON associations(kind_a, id_a);
CREATE INDEX IF NOT EXISTS idx_associations_b ON associations(kind_b, id_b);
CREATE INDEX IF NOT EXISTS idx_associations_last_seen ON associations(last_seen);

-- Failure fingerprints — normalised error signatures extracted from tool_calls
-- when agents fail. Agents can consult this table BEFORE invoking the LLM on
-- a recurring failure ("this exact error has a known fix").
CREATE TABLE IF NOT EXISTS failure_fingerprints (
    fp_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fingerprint   TEXT UNIQUE NOT NULL,
    first_seen    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    last_seen     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    count         INTEGER NOT NULL DEFAULT 1,
    example_error TEXT,
    tool_name     TEXT,
    fix_agent_id  TEXT,
    fix_summary   TEXT,
    fix_skill_id  INTEGER REFERENCES agent_skills(skill_id)
);

CREATE INDEX IF NOT EXISTS idx_fp_last_seen ON failure_fingerprints(last_seen);
CREATE INDEX IF NOT EXISTS idx_fp_count     ON failure_fingerprints(count);

-- Promoted shared-log policies. When a decision pattern repeats above a
-- confidence threshold, the consolidation phase promotes it here so future
-- intents matching the pattern can short-circuit the intent/vote loop.
CREATE TABLE IF NOT EXISTS policies (
    policy_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    action_pattern  TEXT NOT NULL,
    approval_rate   REAL NOT NULL,
    sample_size     INTEGER NOT NULL,
    promoted_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    last_applied_at TEXT,
    applied_count   INTEGER NOT NULL DEFAULT 0,
    enabled         INTEGER NOT NULL DEFAULT 1,
    source_runs     TEXT NOT NULL DEFAULT '[]'
);

CREATE INDEX IF NOT EXISTS idx_policies_enabled ON policies(enabled);

-- Consolidation proposals journal. Every structural change the consolidation
-- phase identifies gets a row, even in dry-run mode. Applied proposals flip
-- `applied=1` and record `applied_at`. This is the audit trail for
-- structural plasticity.
CREATE TABLE IF NOT EXISTS consolidation_proposals (
    proposal_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       INTEGER REFERENCES dream_runs(run_id),
    kind         TEXT NOT NULL
                 CHECK (kind IN ('promote','prune','merge','split')),
    targets      TEXT NOT NULL,
    rationale    TEXT,
    applied      INTEGER NOT NULL DEFAULT 0,
    applied_at   TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE INDEX IF NOT EXISTS idx_proposals_run     ON consolidation_proposals(run_id);
CREATE INDEX IF NOT EXISTS idx_proposals_applied ON consolidation_proposals(applied);

-- Mark skills as deprecated without deleting them. Soft-delete preserves
-- history and references; consolidation writes here rather than DELETE.
ALTER TABLE agent_skills ADD COLUMN deprecated INTEGER NOT NULL DEFAULT 0;
ALTER TABLE agent_skills ADD COLUMN deprecated_at TEXT;
ALTER TABLE agent_skills ADD COLUMN deprecated_reason TEXT;
"""


# Migration to v6: failure intelligence — root-cause categorisation, fix
# outcome tracking, and systemic detection. Additive.
MIGRATION_V6_SQL = """
-- Extend failure_fingerprints with diagnostic metadata.
ALTER TABLE failure_fingerprints ADD COLUMN category TEXT NOT NULL DEFAULT 'unknown';
ALTER TABLE failure_fingerprints ADD COLUMN root_cause TEXT;
ALTER TABLE failure_fingerprints ADD COLUMN suggested_action TEXT;
ALTER TABLE failure_fingerprints ADD COLUMN diagnostic_method TEXT;
ALTER TABLE failure_fingerprints ADD COLUMN diagnosed_at TEXT;
ALTER TABLE failure_fingerprints ADD COLUMN fix_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE failure_fingerprints ADD COLUMN fix_success_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE failure_fingerprints ADD COLUMN last_systemic_alert_at TEXT;

-- Every time an error is seen, record the occurrence. Lets us compute
-- sliding-window counts per fingerprint (systemic detection) without
-- parsing the tool_calls table repeatedly.
CREATE TABLE IF NOT EXISTS failure_occurrences (
    occurrence_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    fp_id           INTEGER NOT NULL REFERENCES failure_fingerprints(fp_id),
    agent_id        TEXT,
    occurred_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE INDEX IF NOT EXISTS idx_fo_fp_time
  ON failure_occurrences(fp_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_fo_agent
  ON failure_occurrences(agent_id);

-- Systemic alerts: when >=N agents hit the same fingerprint in a short
-- window, we flag it as infrastructure-level and halt auto-spawns.
CREATE TABLE IF NOT EXISTS systemic_alerts (
    alert_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fp_id            INTEGER NOT NULL REFERENCES failure_fingerprints(fp_id),
    detected_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now')),
    agent_count      INTEGER NOT NULL,
    window_seconds   INTEGER NOT NULL,
    root_cause       TEXT,
    acked_at         TEXT,
    acked_by         TEXT,
    resolved_at      TEXT,
    resolved_by      TEXT
);

CREATE INDEX IF NOT EXISTS idx_alerts_unresolved
  ON systemic_alerts(resolved_at, detected_at);
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
        conn.executescript(MIGRATION_V4_SQL)
        conn.executescript(MIGRATION_V5_SQL)
        conn.executescript(MIGRATION_V6_SQL)
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
    if from_version < 4:
        conn.executescript(MIGRATION_V4_SQL)
    if from_version < 5:
        conn.executescript(MIGRATION_V5_SQL)
    if from_version < 6:
        conn.executescript(MIGRATION_V6_SQL)
    conn.execute(
        "INSERT INTO schema_version (version) VALUES (?)", (to_version,)
    )
    conn.commit()
