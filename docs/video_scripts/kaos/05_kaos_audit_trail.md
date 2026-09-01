# Tutorial 05 — KAOS Audit Trail: Query Everything Your Agents Did
**Duration:** 5 minutes  
**Level:** Intermediate  
**Goal:** Use the event journal and SQL query interface to reconstruct what agents did, track token spend, find failures, and search across agent VFS content.

---

## SCENE 1 — Hook [0:00–0:20]

**[VISUAL: Agent finished — codebase changed in unexpected ways. Developer stares at `git log`. Nothing useful. Switches to KAOS query — full timeline of every action in seconds.]**

> "An agent finished and something's wrong, but you don't know what it did. With standard tools you grep through logs and hope. With KAOS every operation — every file write, every tool call, every state change — is in an append-only event journal you can query with SQL in seconds."

---

## SCENE 2 — The Event Journal [0:20–1:10]

**[VISUAL: Schema diagram of the events table]**

> "Every KAOS operation writes an event. The events table has a simple schema:"

```sql
-- events table (append-only — nothing is ever deleted)
SELECT event_id,
       agent_id,
       event_type,   -- "file_write", "tool_call", "state_set", "checkpoint", ...
       payload,      -- JSON with operation details
       timestamp
FROM events
LIMIT 5;
```

**[VISUAL: Sample output — 5 rows with realistic event types]**
```
event_type    payload (truncated)
file_write    {"path": "/src/auth.py", "size_bytes": 1240}
tool_call     {"tool": "bash", "command": "pytest tests/", "exit_code": 0}
state_set     {"key": "progress", "value": 75}
file_write    {"path": "/tests/test_auth.py", "size_bytes": 890}
checkpoint    {"label": "pre-migration", "file_count": 4}
```

> "It's append-only by design. No operation is ever deleted or modified. You always have the full history."

---

## SCENE 3 — What Did an Agent Do? [1:10–2:00]

**[VISUAL: Query for a specific agent's timeline]**

> "Reconstruct exactly what one agent did, in order:"

```python
from kaos import Kaos

db = Kaos("project.db")

# Get every event for an agent, chronologically
timeline = db.query("""
    SELECT event_type,
           json_extract(payload, '$.path')    AS file_path,
           json_extract(payload, '$.tool')    AS tool_name,
           json_extract(payload, '$.command') AS command,
           timestamp
    FROM events
    WHERE agent_id = ?
    ORDER BY timestamp ASC
""", [agent_id])

for event in timeline:
    print(f"[{event['timestamp']}] {event['event_type']:12}  {event['file_path'] or event['command'] or ''}")
```

**[VISUAL: Timeline output — clean chronological list of every action]**
```
[10:42:01] file_write   /src/auth.py
[10:42:04] tool_call    pytest tests/auth/
[10:42:11] file_write   /tests/test_auth.py
[10:42:12] state_set    
[10:42:15] checkpoint   
[10:42:20] file_write   /src/database.py   ← the problem
```

---

## SCENE 4 — Token & Cost Tracking [2:00–2:50]

**[VISUAL: Token usage queries]**

> "Query token consumption across agents. KAOS tracks every token used in every tool call."

```python
# Total tokens per agent for a parallel run
costs = db.query("""
    SELECT a.name,
           COUNT(tc.call_id)   AS tool_calls,
           SUM(tc.token_count) AS total_tokens,
           SUM(tc.token_count) * 0.000003 AS cost_usd  -- adjust per model
    FROM agents a
    JOIN tool_calls tc ON a.agent_id = tc.agent_id
    WHERE a.created_at > datetime('now', '-1 day')
    GROUP BY a.agent_id
    ORDER BY total_tokens DESC
""")

for row in costs:
    print(f"{row['name']:20} {row['tool_calls']:3} calls  "
          f"{row['total_tokens']:6} tokens  ${row['cost_usd']:.4f}")
```

**[VISUAL: Output table with per-agent breakdown]**

> "You can slice this by time window, by model, by task type — any dimension you want because it's just SQL."

---

## SCENE 5 — Finding Failures [2:50–3:30]

**[VISUAL: Query for failed tool calls]**

> "Find every failed tool call across all agents in a run:"

```python
failures = db.query("""
    SELECT a.name  AS agent,
           json_extract(payload, '$.tool')      AS tool,
           json_extract(payload, '$.error')     AS error,
           json_extract(payload, '$.exit_code') AS exit_code,
           timestamp
    FROM events e
    JOIN agents a ON e.agent_id = a.agent_id
    WHERE event_type = 'tool_call'
      AND json_extract(payload, '$.exit_code') != 0
    ORDER BY timestamp DESC
    LIMIT 20
""")

for f in failures:
    print(f"[{f['agent']}] {f['tool']} → exit {f['exit_code']}: {f['error'][:80]}")
```

> "Find the first failure, trace back what file was being modified just before it, and you have your root cause in under a minute."

---

## SCENE 6 — Full-Text Search Across Agents [3:30–4:20]

**[VISUAL: `kaos search` and Python search API]**

> "KAOS has full-text search across all agent VFS files — search for a symbol, a string, or a pattern across every file every agent ever wrote."

```bash
# CLI: search across all agent files
kaos search "broken_migration"
```

**[VISUAL: Results — file path, agent name, line number, matching line]**
```
01JQREF.../src/database.py:1   DROP TABLE users;
01JQREF.../src/auth.py:3       broken_migration()
```

```python
# Python API
results = db.search("broken_migration")
for r in results:
    print(r["agent_id"][:12], r["path"], r["line"])
```

> "Useful for finding which agents introduced a problematic pattern, or for quickly locating where a function is defined across a multi-agent codebase."

---

## SCENE 7 — kaos logs [4:20–5:00]

**[VISUAL: `kaos logs` command in terminal]**

> "The quickest way to inspect a specific agent is the `logs` command. It streams the conversation and event log with human-readable formatting."

```bash
# Full event log
kaos logs <agent-id>

# Last 20 events only
kaos logs <agent-id> --tail 20

# Filter to file events only
kaos logs <agent-id> --filter file_write
```

> "The logs command is your first stop when debugging a misbehaving agent — before you write any SQL.

You now have a complete picture of KAOS's observability: event journal, token tracking, failure queries, full-text search, and the logs command. Next tutorial: Meta-Harness search — the autonomous harness optimization engine built on top of all of this."

---

## AI VIDEO GENERATION NOTES
- **Voice tone:** Analytical, confident. SQL queries are the star — make them feel powerful, not intimidating.
- **Highlight (Scene 3):** The line `[10:42:20] file_write   /src/database.py` should be highlighted in red with a "← the problem" annotation animating in.
- **Scene 4:** Show the cost table with a subtle dollar sign callout — this is a real pain point developers feel.
- **Terminal (Scene 6):** The search results should highlight the matching text in yellow, like grep --color.
