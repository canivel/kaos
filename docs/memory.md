# Cross-Agent Memory

KAOS's cross-agent memory store lets every agent in a project write persistent, searchable knowledge that any future agent can retrieve — across iterations, across sessions, across workers.

> Inspired by [claude-mem](https://github.com/thedotmack/claude-mem) by Alex Newman ([@thedotmack](https://github.com/thedotmack)), AGPL-3.0.
> Adapted for KAOS's multi-agent, SQLite-backed architecture with FTS5 full-text search.

---

## Overview

Memory entries are stored in a SQLite table with an FTS5 virtual table for full-text search. All agents in the same `.db` file share one memory store.

**Memory types:**

| Type | Use case |
|------|----------|
| `observation` | Runtime findings, intermediate results |
| `result` | Final outputs, benchmark scores |
| `skill` | Reusable patterns, code templates |
| `insight` | Analysis, lessons learned |
| `error` | Known failure modes to avoid |

---

## Quick Start

```python
from kaos import Kaos
from kaos.memory import MemoryStore

kaos = Kaos("project.db")
mem  = MemoryStore(kaos.conn)

# Any agent writes a result
mid = mem.write(
    agent_id="proposer-iter-3",
    content="Ensemble voting with 3 Sonnet calls achieved accuracy=0.847.",
    type="result",
    key="iter3-best",
    metadata={"accuracy": 0.847, "cost": 18.2},
)

# Any other agent can search across all memory
hits = mem.search("ensemble accuracy")
for h in hits:
    print(h.content)
```

---

## API Reference

### `MemoryStore.write(agent_id, content, type, key, metadata) -> int`

Persist a memory entry. Returns the `memory_id`.

```python
mid = mem.write(
    agent_id="agent-01",
    content="Chain-of-thought prompting reduces errors by 23%.",
    type="skill",
    key="cot-numbered-steps",
    metadata={"benchmark": "math_rag"},
)
```

### `MemoryStore.search(query, limit, type, agent_id) -> list[MemoryEntry]`

Full-text search using SQLite FTS5 with porter stemming. Results are ranked by BM25 relevance.

Supports FTS5 query syntax:
- Phrase: `"chain of thought"`
- NOT: `reasoning NOT error`
- OR: `ensemble OR majority`
- Wildcard: `accurac*`

```python
# Search across all agents, all types
hits = mem.search("ensemble voting math", limit=5)

# Filter to only 'error' entries
errors = mem.search("JSON decode", type="error")

# Filter to one agent
hits = mem.search("ensemble", agent_id="proposer-iter-3")
```

### `MemoryStore.list(agent_id, type, limit, offset) -> list[MemoryEntry]`

List entries (most recent first) with optional filters.

```python
# All entries
entries = mem.list()

# Skills only
skills = mem.list(type="skill", limit=20)

# Paginate
page2 = mem.list(offset=20, limit=20)
```

### `MemoryStore.get(memory_id) -> MemoryEntry | None`

Fetch a single entry by primary key.

### `MemoryStore.get_by_key(key, agent_id) -> MemoryEntry | None`

Fetch the most recent entry with a given key.

### `MemoryStore.delete(memory_id) -> bool`

Delete an entry (also removes from FTS index via trigger).

### `MemoryStore.stats() -> dict`

Return total count and per-type breakdown.

---

## CLI

```bash
# Write a memory entry
uv run kaos memory write <agent_id> "Ensemble voting improved accuracy by 12%." --type insight --key ensemble-v1

# Full-text search
uv run kaos memory search "ensemble accuracy"
uv run kaos memory search "JSON error" --type error

# List recent entries
uv run kaos memory ls
uv run kaos memory ls --type result --limit 5

# JSON output for piping
uv run kaos --json memory search "ensemble" | jq '.[].content'
```

---

## MCP Tools

When using KAOS via Claude Code or MCP:

```
agent_memory_write   — persist a memory entry
agent_memory_search  — FTS5 search across all agents
agent_memory_read    — fetch by memory_id or list recent
```

---

## Meta-Harness Integration

The Meta-Harness automatically writes improved harnesses and known failures to memory after each iteration. The proposer agent receives a "Cross-Session Memory" block in its prompt for context from prior searches.

This means: **even if you restart a search, the proposer knows what has worked before.**

```python
# Memory is auto-written in _store_result() for improved/failed harnesses
# Memory is auto-queried in proposer._load_memory_context()
```

---

## Schema

```sql
CREATE TABLE memory (
    memory_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id    TEXT NOT NULL REFERENCES agents(agent_id),
    type        TEXT NOT NULL DEFAULT 'observation',
    key         TEXT,
    content     TEXT NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);

CREATE VIRTUAL TABLE memory_fts USING fts5(
    content, key,
    type UNINDEXED, agent_id UNINDEXED, memory_id UNINDEXED, created_at UNINDEXED,
    tokenize = 'porter unicode61'
);
-- FTS is kept in sync via INSERT/UPDATE/DELETE triggers
```

---

## Example

See [examples/memory_search.py](../examples/memory_search.py) for a complete demo.

---

## Credits

Inspired by [claude-mem](https://github.com/thedotmack/claude-mem) by Alex Newman ([@thedotmack](https://github.com/thedotmack)), licensed AGPL-3.0.

The core idea — agents writing compact, searchable memories for cross-session retrieval — is taken directly from claude-mem. KAOS adapts it for:
- SQLite FTS5 instead of a separate file store
- Multi-agent (many writers, many readers) instead of single-agent
- Typed entries (result, skill, error, insight, observation) for structured retrieval
- Automatic meta-harness integration
