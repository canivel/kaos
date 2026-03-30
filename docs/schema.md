# KAOS SQLite Schema Reference

> Complete reference for the 8 tables that make up the KAOS database.

Schema version: **1** (defined in `kaos/schema.py`)

---

## Table of Contents

1. [Overview](#overview)
2. [agents](#agents)
3. [files](#files)
4. [blobs](#blobs)
5. [tool_calls](#tool_calls)
6. [state](#state)
7. [events](#events)
8. [checkpoints](#checkpoints)
9. [schema_version](#schema_version)
10. [Relationships](#relationships)
11. [Index Reference](#index-reference)

---

## Overview

KAOS stores all data in a single SQLite database file using WAL (Write-Ahead Logging) mode. The schema consists of 8 tables organized around the concept of isolated agents:

```
agents  ----<  files         (1:N - each agent has many files)
        ----<  tool_calls    (1:N - each agent has many tool calls)
        ----<  state         (1:N - each agent has many KV pairs)
        ----<  events        (1:N - each agent has many events)
        ----<  checkpoints   (1:N - each agent has many checkpoints)

blobs   <----  files         (1:N - many files can share one blob)
```

All timestamps use ISO 8601 format with millisecond precision: `strftime('%Y-%m-%dT%H:%M:%f', 'now')`.

All JSON columns (`config`, `metadata`, `input`, `output`, `payload`, `value`, `file_manifest`, `state_snapshot`) store valid JSON text.

---

## agents

The agent registry. Each row represents one agent with its lifecycle state.

```sql
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
```

### Columns

| Column | Type | Constraints | Description |
|---|---|---|---|
| `agent_id` | TEXT | PRIMARY KEY | ULID-based unique identifier. Time-sortable. |
| `name` | TEXT | NOT NULL | Human-readable name for the agent (e.g., "test-writer"). |
| `parent_id` | TEXT | FK -> agents(agent_id), nullable | Parent agent ID for hierarchical agent spawning. NULL for root agents. |
| `created_at` | TEXT | NOT NULL, auto-generated | ISO 8601 timestamp of agent creation. |
| `status` | TEXT | NOT NULL, CHECK constraint | Current lifecycle state. One of: `initialized`, `running`, `paused`, `completed`, `failed`, `killed`. |
| `config` | TEXT | NOT NULL, default `'{}'` | JSON object with agent configuration (e.g., `{"force_model": "deepseek-r1-70b"}`). |
| `metadata` | TEXT | NOT NULL, default `'{}'` | JSON object with arbitrary metadata. |
| `pid` | INTEGER | nullable | OS process ID when the agent is running. |
| `last_heartbeat` | TEXT | nullable | ISO 8601 timestamp of the last heartbeat update. |

### Indexes

| Index | Columns | Purpose |
|---|---|---|
| `idx_agents_status` | `status` | Fast filtering by lifecycle state (e.g., list all running agents). |
| `idx_agents_parent` | `parent_id` | Fast lookup of child agents for a given parent. |

### Example Queries

```sql
-- List all running agents
SELECT agent_id, name, last_heartbeat
FROM agents WHERE status = 'running';

-- Find agents spawned by a parent
SELECT agent_id, name, status
FROM agents WHERE parent_id = '01HXYZ...';

-- Agent lifecycle summary
SELECT status, COUNT(*) as count
FROM agents GROUP BY status;

-- Find stale agents (no heartbeat in 5 minutes)
SELECT agent_id, name, last_heartbeat
FROM agents
WHERE status = 'running'
AND last_heartbeat < strftime('%Y-%m-%dT%H:%M:%f', 'now', '-5 minutes');
```

---

## files

The virtual filesystem. Each row is a version of a file or directory within an agent's namespace.

```sql
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
```

### Columns

| Column | Type | Constraints | Description |
|---|---|---|---|
| `file_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Internal row identifier. |
| `agent_id` | TEXT | NOT NULL, FK -> agents | The owning agent. All queries are scoped by this. |
| `path` | TEXT | NOT NULL | POSIX-normalized absolute path (e.g., `/src/main.py`). |
| `is_dir` | INTEGER | NOT NULL, default 0 | 1 if this entry is a directory, 0 for files. |
| `content_hash` | TEXT | nullable | SHA-256 hash referencing the `blobs` table. NULL for directories. |
| `size` | INTEGER | NOT NULL, default 0 | Original (uncompressed) size in bytes. |
| `mode` | INTEGER | NOT NULL, default 33188 | Unix file mode. 33188 = `0o100644` (regular file, rw-r--r--). |
| `created_at` | TEXT | NOT NULL, auto-generated | ISO 8601 timestamp of version creation. |
| `modified_at` | TEXT | NOT NULL, auto-generated | ISO 8601 timestamp of last modification. |
| `version` | INTEGER | NOT NULL, default 1 | Version number. Increments on each write to the same path. |
| `deleted` | INTEGER | NOT NULL, default 0 | Soft-delete flag. 1 = deleted (hidden from normal queries but retained for history/checkpoints). |

### Unique Constraint

`UNIQUE(agent_id, path, version)` -- Each agent can have only one entry per path per version number.

### Indexes

| Index | Columns | Filter | Purpose |
|---|---|---|---|
| `idx_files_agent_path` | `agent_id, path` | `WHERE deleted = 0` | Fast file lookup by agent + path, excluding deleted files. Partial index. |
| `idx_files_agent` | `agent_id` | -- | List all files for an agent. |

### Example Queries

```sql
-- List all active files for an agent
SELECT path, size, version, modified_at
FROM files
WHERE agent_id = '01HXYZ...' AND deleted = 0 AND is_dir = 0
ORDER BY path;

-- Get file version history
SELECT version, content_hash, size, created_at, deleted
FROM files
WHERE agent_id = '01HXYZ...' AND path = '/src/app.py'
ORDER BY version;

-- List directory contents (one level deep)
SELECT path, is_dir, size, modified_at
FROM files
WHERE agent_id = '01HXYZ...'
AND deleted = 0
AND path LIKE '/src/%'
AND path NOT LIKE '/src/%/%'
AND path != '/src';

-- Total storage used per agent
SELECT agent_id, SUM(size) as total_bytes, COUNT(*) as file_count
FROM files
WHERE deleted = 0 AND is_dir = 0
GROUP BY agent_id
ORDER BY total_bytes DESC;
```

---

## blobs

Content-addressable blob store with SHA-256 deduplication and optional zstd compression.

```sql
CREATE TABLE IF NOT EXISTS blobs (
    content_hash    TEXT PRIMARY KEY,
    content         BLOB NOT NULL,
    compressed      INTEGER NOT NULL DEFAULT 0,
    ref_count       INTEGER NOT NULL DEFAULT 1
);
```

### Columns

| Column | Type | Constraints | Description |
|---|---|---|---|
| `content_hash` | TEXT | PRIMARY KEY | SHA-256 hex digest of the original (uncompressed) content. |
| `content` | BLOB | NOT NULL | The stored content. May be zstd-compressed (check `compressed` flag). |
| `compressed` | INTEGER | NOT NULL, default 0 | 1 if `content` is zstd-compressed, 0 if stored raw. |
| `ref_count` | INTEGER | NOT NULL, default 1 | Number of file entries referencing this blob. Decremented on file deletion; blob is GC-eligible when <= 0. |

### Design Notes

- **Deduplication**: If two agents write identical file content, only one blob is stored. The `ref_count` is incremented instead.
- **Compression**: When compression is enabled (default), blobs are compressed with zstandard level 3 before storage. The `compressed` flag indicates whether decompression is needed on retrieval.
- **Garbage collection**: `BlobStore.gc()` deletes all blobs where `ref_count <= 0`. This is safe because soft-deleted files retain their `content_hash` reference for checkpoint restoration.

### Example Queries

```sql
-- Blob store statistics
SELECT
    COUNT(*) as total_blobs,
    SUM(LENGTH(content)) as total_stored_bytes,
    SUM(ref_count) as total_references
FROM blobs;

-- Find orphaned blobs (eligible for GC)
SELECT content_hash, LENGTH(content) as stored_size, ref_count
FROM blobs
WHERE ref_count <= 0;

-- Largest blobs by stored size
SELECT content_hash, LENGTH(content) as stored_bytes, ref_count
FROM blobs
ORDER BY LENGTH(content) DESC
LIMIT 10;

-- Blobs shared across multiple files
SELECT content_hash, ref_count
FROM blobs
WHERE ref_count > 1
ORDER BY ref_count DESC;
```

---

## tool_calls

Journal of all tool invocations made by agents during execution.

```sql
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
```

### Columns

| Column | Type | Constraints | Description |
|---|---|---|---|
| `call_id` | TEXT | PRIMARY KEY | ULID-based unique identifier for the tool call. |
| `agent_id` | TEXT | NOT NULL, FK -> agents | The agent that made the call. |
| `tool_name` | TEXT | NOT NULL | Name of the tool (e.g., `fs_read`, `shell_exec`, `fs_write`). |
| `input` | TEXT | NOT NULL | JSON-serialized input arguments. |
| `output` | TEXT | nullable | JSON-serialized output. NULL while pending/running. |
| `status` | TEXT | NOT NULL, CHECK constraint | Call status: `pending`, `running`, `success`, `error`, `timeout`. |
| `started_at` | TEXT | NOT NULL, auto-generated | ISO 8601 timestamp when the call was logged. |
| `completed_at` | TEXT | nullable | ISO 8601 timestamp when the call finished. |
| `duration_ms` | INTEGER | nullable | Execution time in milliseconds (computed on completion). |
| `token_count` | INTEGER | nullable | Number of tokens consumed by the model call that triggered this tool use. |
| `cost_usd` | REAL | default 0.0 | Estimated cost in USD (reserved for future use). |
| `parent_call_id` | TEXT | FK -> tool_calls(call_id), nullable | Links child calls to a parent call for hierarchical tracing. |
| `error_message` | TEXT | nullable | Error message if status is `error`. |

### Indexes

| Index | Columns | Purpose |
|---|---|---|
| `idx_tool_calls_agent` | `agent_id, started_at` | Chronological tool call history per agent. |
| `idx_tool_calls_tool` | `tool_name` | Filter by tool type across all agents. |
| `idx_tool_calls_status` | `status` | Find pending, failed, or timed-out calls. |

### Example Queries

```sql
-- Recent tool calls for an agent
SELECT call_id, tool_name, status, duration_ms, token_count
FROM tool_calls
WHERE agent_id = '01HXYZ...'
ORDER BY started_at DESC
LIMIT 20;

-- Token consumption by agent
SELECT a.name, SUM(tc.token_count) as total_tokens, COUNT(*) as calls
FROM tool_calls tc
JOIN agents a ON tc.agent_id = a.agent_id
WHERE tc.status = 'success'
GROUP BY tc.agent_id
ORDER BY total_tokens DESC;

-- Failed tool calls with error details
SELECT agent_id, tool_name, error_message, started_at
FROM tool_calls
WHERE status = 'error'
ORDER BY started_at DESC;

-- Average duration per tool type
SELECT tool_name, AVG(duration_ms) as avg_ms, COUNT(*) as calls
FROM tool_calls
WHERE status = 'success'
GROUP BY tool_name
ORDER BY avg_ms DESC;

-- Trace a tool call chain (recursive CTE)
WITH RECURSIVE chain AS (
    SELECT call_id, tool_name, parent_call_id, 0 as depth
    FROM tool_calls WHERE call_id = 'target-call-id'
    UNION ALL
    SELECT tc.call_id, tc.tool_name, tc.parent_call_id, c.depth + 1
    FROM tool_calls tc JOIN chain c ON tc.parent_call_id = c.call_id
)
SELECT * FROM chain ORDER BY depth;
```

---

## state

Key-value store for agent runtime state. Supports any JSON-serializable value.

```sql
CREATE TABLE IF NOT EXISTS state (
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    key             TEXT NOT NULL,
    value           TEXT NOT NULL,
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now')),
    PRIMARY KEY (agent_id, key)
);
```

### Columns

| Column | Type | Constraints | Description |
|---|---|---|---|
| `agent_id` | TEXT | NOT NULL, FK -> agents, part of PK | The owning agent. |
| `key` | TEXT | NOT NULL, part of PK | State key name (e.g., `conversation`, `iteration`, `progress`). |
| `value` | TEXT | NOT NULL | JSON-serialized value. Can be string, number, array, or object. |
| `updated_at` | TEXT | NOT NULL, auto-generated | ISO 8601 timestamp of the last update. |

### Design Notes

- **Composite primary key**: `(agent_id, key)` ensures key uniqueness per agent and enables upsert via `ON CONFLICT`.
- **Upsert semantics**: `set_state()` uses `INSERT ... ON CONFLICT DO UPDATE`, so setting an existing key replaces its value atomically.
- **CCR state**: The CCR loop stores `conversation`, `iteration`, `task`, and `result` as state keys, making the agent's full conversation history queryable.

### Example Queries

```sql
-- Get all state for an agent
SELECT key, value, updated_at
FROM state
WHERE agent_id = '01HXYZ...'
ORDER BY key;

-- Get a specific state value
SELECT value FROM state
WHERE agent_id = '01HXYZ...' AND key = 'iteration';

-- Find agents at a specific iteration
SELECT s.agent_id, a.name, s.value as iteration
FROM state s
JOIN agents a ON s.agent_id = a.agent_id
WHERE s.key = 'iteration'
ORDER BY CAST(s.value AS INTEGER) DESC;

-- State key usage across all agents
SELECT key, COUNT(*) as agent_count
FROM state
GROUP BY key
ORDER BY agent_count DESC;
```

---

## events

Append-only event journal for complete audit trails.

```sql
CREATE TABLE IF NOT EXISTS events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
    event_type      TEXT NOT NULL,
    payload         TEXT NOT NULL DEFAULT '{}',
    timestamp       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

### Columns

| Column | Type | Constraints | Description |
|---|---|---|---|
| `event_id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Globally ordered, monotonically increasing event identifier. |
| `agent_id` | TEXT | NOT NULL, FK -> agents | The agent that triggered the event. |
| `event_type` | TEXT | NOT NULL | Event type string (see table below). |
| `payload` | TEXT | NOT NULL, default `'{}'` | JSON object with event-specific data. |
| `timestamp` | TEXT | NOT NULL, auto-generated | ISO 8601 timestamp with millisecond precision. |

### Standard Event Types

| Event Type | Payload Example | Trigger |
|---|---|---|
| `agent_spawn` | `{"name": "...", "parent_id": null, "config": {...}}` | Agent created via `spawn()` |
| `agent_pause` | `{}` | Agent paused |
| `agent_resume` | `{}` | Agent resumed |
| `agent_kill` | `{}` | Agent killed |
| `agent_complete` | `{}` | Agent completed successfully |
| `agent_fail` | `{"error": "..."}` | Agent failed |
| `state_change` | `{"field": "status", "from": "initialized", "to": "running"}` | Status transition |
| `file_read` | `{"path": "/src/app.py"}` | File read from VFS |
| `file_write` | `{"path": "/src/app.py", "size": 1234, "version": 2}` | File written to VFS |
| `file_delete` | `{"path": "/tmp/scratch.txt"}` | File deleted from VFS |
| `tool_call_start` | `{"call_id": "...", "tool_name": "fs_read"}` | Tool execution started |
| `tool_call_end` | `{"call_id": "...", "status": "success"}` | Tool execution completed |
| `checkpoint_create` | `{"checkpoint_id": "...", "label": "pre-refactor"}` | Checkpoint created |
| `checkpoint_restore` | `{"checkpoint_id": "..."}` | Checkpoint restored |
| `error` | `{"message": "..."}` | Runtime error |
| `warning` | `{"message": "..."}` | Runtime warning |

### Indexes

| Index | Columns | Purpose |
|---|---|---|
| `idx_events_agent_time` | `agent_id, timestamp` | Chronological event history per agent. |
| `idx_events_type` | `event_type` | Filter events by type across all agents. |

### Example Queries

```sql
-- Full timeline for an agent
SELECT event_id, event_type, payload, timestamp
FROM events
WHERE agent_id = '01HXYZ...'
ORDER BY event_id;

-- What did an agent do in the last hour?
SELECT event_type, payload, timestamp
FROM events
WHERE agent_id = '01HXYZ...'
AND timestamp > strftime('%Y-%m-%dT%H:%M:%f', 'now', '-1 hour')
ORDER BY event_id;

-- Count events by type for an agent
SELECT event_type, COUNT(*) as count
FROM events
WHERE agent_id = '01HXYZ...'
GROUP BY event_type
ORDER BY count DESC;

-- System-wide activity summary
SELECT event_type, COUNT(*) as count
FROM events
GROUP BY event_type
ORDER BY count DESC;

-- Find all file writes across all agents
SELECT e.agent_id, a.name,
       json_extract(e.payload, '$.path') as file_path,
       json_extract(e.payload, '$.size') as size,
       e.timestamp
FROM events e
JOIN agents a ON e.agent_id = a.agent_id
WHERE e.event_type = 'file_write'
ORDER BY e.timestamp DESC
LIMIT 20;
```

---

## checkpoints

Point-in-time snapshots of an agent's file manifest and state.

```sql
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
```

### Columns

| Column | Type | Constraints | Description |
|---|---|---|---|
| `checkpoint_id` | TEXT | PRIMARY KEY | ULID-based unique identifier. |
| `agent_id` | TEXT | NOT NULL, FK -> agents | The agent this checkpoint belongs to. |
| `label` | TEXT | nullable | Optional human-readable label (e.g., `"pre-refactor"`, `"auto-iter-10"`). |
| `created_at` | TEXT | NOT NULL, auto-generated | ISO 8601 timestamp of checkpoint creation. |
| `event_id` | INTEGER | FK -> events(event_id), nullable | The event_id at the time of checkpoint creation. Used as a watermark for diffing. |
| `file_manifest` | TEXT | NOT NULL | JSON array of file entries: `[{"path": "...", "content_hash": "...", "version": N}, ...]`. |
| `state_snapshot` | TEXT | NOT NULL | JSON object of all KV state at checkpoint time: `{"key1": value1, "key2": value2, ...}`. |
| `metadata` | TEXT | NOT NULL, default `'{}'` | JSON object for arbitrary checkpoint metadata. |

### Indexes

| Index | Columns | Purpose |
|---|---|---|
| `idx_checkpoints_agent` | `agent_id, created_at` | Chronological checkpoint listing per agent. |

### Example Queries

```sql
-- List checkpoints for an agent
SELECT checkpoint_id, label, created_at, event_id
FROM checkpoints
WHERE agent_id = '01HXYZ...'
ORDER BY created_at;

-- Get checkpoint details (file count, state key count)
SELECT
    checkpoint_id,
    label,
    created_at,
    json_array_length(file_manifest) as file_count,
    json_object_length(state_snapshot) as state_keys
FROM checkpoints
WHERE agent_id = '01HXYZ...';

-- Find auto-checkpoints
SELECT checkpoint_id, label, created_at
FROM checkpoints
WHERE label LIKE 'auto-iter-%'
ORDER BY created_at;

-- Inspect a checkpoint's file manifest
SELECT
    json_extract(value, '$.path') as path,
    json_extract(value, '$.content_hash') as hash,
    json_extract(value, '$.version') as version
FROM checkpoints, json_each(file_manifest)
WHERE checkpoint_id = '01HABC...';
```

---

## schema_version

Tracks applied schema migrations.

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version         INTEGER PRIMARY KEY,
    applied_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f', 'now'))
);
```

### Columns

| Column | Type | Constraints | Description |
|---|---|---|---|
| `version` | INTEGER | PRIMARY KEY | Schema version number. Current: 1. |
| `applied_at` | TEXT | NOT NULL, auto-generated | ISO 8601 timestamp when this version was applied. |

### Design Notes

- On first initialization, version 1 is inserted.
- On subsequent opens, if the database version is behind the code's `SCHEMA_VERSION`, incremental migrations are applied via `_apply_migrations()`.
- Future migrations will be added as `if from_version < N:` blocks in `kaos/schema.py`.

### Example Queries

```sql
-- Check current schema version
SELECT MAX(version) as current_version FROM schema_version;

-- Migration history
SELECT version, applied_at FROM schema_version ORDER BY version;
```

---

## Relationships

```
agents.agent_id    ----<  files.agent_id           (one agent, many files)
agents.agent_id    ----<  tool_calls.agent_id      (one agent, many tool calls)
agents.agent_id    ----<  state.agent_id           (one agent, many state keys)
agents.agent_id    ----<  events.agent_id          (one agent, many events)
agents.agent_id    ----<  checkpoints.agent_id     (one agent, many checkpoints)
agents.agent_id    <---   agents.parent_id         (self-referencing parent/child)
blobs.content_hash <---   files.content_hash       (one blob, many file versions)
tool_calls.call_id <---   tool_calls.parent_call_id (self-referencing call chain)
events.event_id    <---   checkpoints.event_id     (checkpoint watermark into event stream)
```

### Foreign Key Enforcement

Foreign keys are enforced via `PRAGMA foreign_keys=ON`, which is set on every connection. This prevents orphaned rows (e.g., creating a file for a non-existent agent).

---

## Index Reference

| Table | Index Name | Columns | Partial? | Purpose |
|---|---|---|---|---|
| agents | `idx_agents_status` | `status` | No | Filter agents by lifecycle state |
| agents | `idx_agents_parent` | `parent_id` | No | Find child agents |
| files | `idx_files_agent_path` | `agent_id, path` | Yes (`deleted=0`) | Fast file lookup excluding deleted |
| files | `idx_files_agent` | `agent_id` | No | List all files for an agent |
| tool_calls | `idx_tool_calls_agent` | `agent_id, started_at` | No | Chronological call history |
| tool_calls | `idx_tool_calls_tool` | `tool_name` | No | Filter by tool type |
| tool_calls | `idx_tool_calls_status` | `status` | No | Find calls by status |
| events | `idx_events_agent_time` | `agent_id, timestamp` | No | Chronological event stream |
| events | `idx_events_type` | `event_type` | No | Filter by event type |
| checkpoints | `idx_checkpoints_agent` | `agent_id, created_at` | No | Chronological checkpoint listing |
