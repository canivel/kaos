# KAOS

**Kernel for Agent Orchestration & Sandboxing**

> Your agents share filesystems, lose state on crash, and you have no idea what they did. KAOS fixes that. Every agent gets an isolated virtual filesystem inside a single SQLite file — with full history, checkpoint/restore, and SQL-queryable audit trails.

Named after the enemy spy agency in *Get Smart* (1965). Ironic, because KAOS is how you **control** your agents.

[![Tests](https://img.shields.io/badge/tests-84%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-orange)]()
[![Dependencies](https://img.shields.io/badge/deps-44%20total-lightgrey)]()
[![Website](https://img.shields.io/badge/website-canivel.github.io%2Fkaos-blueviolet)](https://canivel.github.io/kaos/)

---

## The Problem

You're running multiple AI agents. Maybe they're reviewing code, refactoring modules, or writing tests in parallel. Here's what goes wrong:

**Agents step on each other.** Two agents write to the same file. One overwrites the other's work. You don't find out until production.

**An agent goes rogue and you can't debug it.** It made 47 tool calls, modified 12 files, and now the codebase is broken. What did it actually do? In what order? Good luck with `git log`.

**You can't roll back a single agent.** The refactor agent broke everything. You `git reset --hard` and lose the work of the 3 other agents that were fine.

**State vanishes.** Agent crashes mid-task. Its progress, findings, intermediate files — all gone. Start over.

**You can't inspect anything.** How many tokens did each agent use? Which tool calls failed? What files did agent X touch? You're `grep`-ing through logs, if you even have logs.

## How KAOS Solves This

```python
from kaos import Kaos

db = Kaos("project.db")

# Each agent is isolated — they literally cannot see each other's files
agent_a = db.spawn("refactorer")
agent_b = db.spawn("test-writer")

db.write(agent_a, "/src/auth.py", b"# refactored auth module")
db.write(agent_b, "/src/auth.py", b"# test stubs for auth")
# Both wrote to "/src/auth.py" — no conflict. Each has their own copy.

# Checkpoint before risky operations
cp = db.checkpoint(agent_a, label="before-database-migration")
# ... agent does something dangerous ...
db.restore(agent_a, cp)  # roll back just this agent, others untouched

# What exactly did it do? Query the audit trail.
db.query("SELECT event_type, payload FROM events WHERE agent_id = ?", [agent_a])
```

**Everything lives in one `.db` file.** Copy it to back up. Send it to a teammate. Query it with any SQLite client. That's the entire runtime — files, state, tool calls, events, checkpoints.

---

## Why Not Just Use LangChain / CrewAI / AutoGen?

Those frameworks focus on **prompt chaining and agent communication**. KAOS focuses on the **runtime infrastructure** underneath — the part they all skip:

| Problem | LangChain / CrewAI / AutoGen | KAOS |
|---|---|---|
| Agent isolation | Shared filesystem | Enforced per-agent VFS (SQL-scoped) |
| Audit trail | DIY logging | Append-only event journal, every operation |
| Rollback one agent | Not possible | `db.restore(agent, checkpoint)` |
| Debug a failed agent | Read logs, hope for the best | `SELECT * FROM events WHERE agent_id = ?` |
| Portable runtime | Cloud-dependent / in-memory | Single `.db` file, works anywhere |
| State persistence | Framework-specific, often lost on crash | SQLite — survives crashes by design |
| Token/cost tracking | Varies, often manual | `SELECT SUM(token_count) FROM tool_calls` |

KAOS isn't a replacement for those frameworks — it's the **runtime layer they're missing**. You can use KAOS underneath LangChain, or use it standalone with local LLMs.

---

## Quick Start

```bash
git clone https://github.com/canivel/kaos.git && cd kaos
uv sync
```

### As a Python library (no infrastructure needed)

```python
from kaos import Kaos

db = Kaos("my-project.db")

# Spawn agents with isolated filesystems
researcher = db.spawn("researcher", config={"team": "backend"})
writer = db.spawn("doc-writer", config={"team": "docs"})

# Each agent has its own virtual filesystem
db.write(researcher, "/findings.md", b"# Bug Report\nFound SQL injection in auth.py")
db.write(writer, "/draft.md", b"# API Docs v2\n...")

# Isolation is enforced — not just a convention
db.read(researcher, "/findings.md")   # works
# db.read(writer, "/findings.md")     # FileNotFoundError — isolated!

# KV state per agent (survives crashes)
db.set_state(researcher, "progress", 75)
db.set_state(researcher, "findings", ["SQL injection in auth", "missing rate limit"])

# Checkpoint before risky work
cp1 = db.checkpoint(researcher, label="pre-refactor")
# ... agent does risky stuff ...
cp2 = db.checkpoint(researcher, label="post-refactor")

# Something went wrong? Roll back.
db.restore(researcher, cp1)  # back to safety

# Or diff two checkpoints — what exactly changed?
diff = db.diff_checkpoints(researcher, cp1, cp2)
# → files added/removed/modified, state changes, tool calls between checkpoints

# Query anything with SQL
db.query("SELECT name, status FROM agents")
db.query("SELECT SUM(token_count) FROM tool_calls WHERE agent_id = ?", [researcher])

db.close()
```

### With local LLMs (fully autonomous agents)

Point KAOS at local vLLM instances — including your own finetuned models:

```bash
# Start your models (any OpenAI-compatible endpoint)
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000
vllm serve deepseek-ai/DeepSeek-R1-70B --port 8002
```

```python
import asyncio
from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter

db = Kaos("project.db")
router = GEPARouter.from_config("kaos.yaml")
ccr = ClaudeCodeRunner(db, router)

# GEPA router auto-classifies task complexity and picks the right model:
#   trivial → 7B (fast, cheap)    complex → 70B (powerful)
results = asyncio.run(ccr.run_parallel([
    {"name": "tests",  "prompt": "Write unit tests for the payments module"},
    {"name": "impl",   "prompt": "Refactor payments to use Stripe SDK v3"},
    {"name": "docs",   "prompt": "Update the payment API documentation"},
]))

# Every agent ran in parallel, fully isolated, with auto-checkpointing.
# Query what happened:
stats = db.query("""
    SELECT a.name,
           COUNT(tc.call_id) as tool_calls,
           SUM(tc.token_count) as tokens
    FROM agents a LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
    GROUP BY a.agent_id
""")
```

### As an MCP Server (Claude Code integration)

```bash
kaos serve --transport stdio
```

Add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "kaos": {
      "command": "kaos",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

Now Claude Code can spawn agents, read/write to their filesystems, create checkpoints, and query the database — all as native tool calls.

### Via the CLI

```bash
kaos init                              # Create database
kaos run "refactor auth module" -n auth # Run a single agent
kaos parallel \
    -t tests "write tests" \
    -t impl "refactor code" \
    -t docs "update docs"              # Run agents in parallel
kaos ls                                # List agents
kaos status <agent-id>                 # Agent details
kaos checkpoint <agent-id> -l "safe"   # Snapshot agent state
kaos restore <agent-id> --checkpoint X # Roll back
kaos diff <agent-id> --from X --to Y   # What changed between checkpoints?
kaos query "SELECT * FROM events"      # SQL queries
kaos dashboard                         # Live TUI monitor
kaos export <agent-id> -o backup.db    # Export a single agent
```

---

## Key Capabilities

### Enforced Agent Isolation

Not convention-based. Every VFS operation is SQL-scoped with `WHERE agent_id = ?`. It's physically impossible for one agent to access another's files through the API. Optional FUSE tier (Linux) adds OS-level mount + namespace isolation with cgroup resource limits.

### Append-Only Audit Trail

Every operation is recorded: file reads, writes, deletes, tool calls (with timing and token counts), state changes, lifecycle events. 14 event types total. Query any agent's complete history with SQL.

```sql
-- What did this agent do in the last hour?
SELECT timestamp, event_type, payload FROM events
WHERE agent_id = 'auth-refactor'
  AND timestamp > datetime('now', '-1 hour')
ORDER BY timestamp;
```

### Checkpoint / Restore / Diff

Snapshot an agent's files + state at any point. Restore to any checkpoint. Diff two checkpoints to see exactly what changed — files added/removed/modified, state changes, and tool calls between them. Auto-checkpoints every N iterations as a safety net.

```python
cp1 = db.checkpoint(agent, label="before-migration")
# ... agent works ...
cp2 = db.checkpoint(agent, label="after-migration")

diff = db.diff_checkpoints(agent, cp1, cp2)
# diff.files.added, diff.files.modified, diff.state.changed, diff.tool_calls
```

### Content-Addressable Blob Store

Files are stored as SHA-256 blobs with zstd compression. Identical files across agents are deduplicated automatically. Reference counting with garbage collection keeps storage lean — even with hundreds of agents.

### Intelligent Model Routing (GEPA)

The **G**eneralized **E**xecution **P**lanning & **A**llocation router classifies task complexity (via LLM or heuristic fallback) and routes to the optimal model tier. Trivial formatting task? Send it to a 7B. Complex architecture decision? Route to the 70B. Works with any OpenAI-compatible endpoint.

### Single-File Portability

The entire runtime is one `.db` file. Back it up with `cp`. Send it to a colleague. Open it on another machine. Query it with DBeaver, DataGrip, or the `sqlite3` CLI. No cloud, no server, no Docker.

---

## Real-World Examples

### Code Review Swarm

Four agents review the same code from different angles — security, performance, style, and test coverage — all running in parallel with full isolation:

```python
# examples/code_review_swarm.py
results = await ccr.run_parallel([
    {"name": "security",    "prompt": f"Find security vulnerabilities:\n{code}",
     "config": {"force_model": "deepseek-r1-70b"}},
    {"name": "performance", "prompt": f"Find performance issues:\n{code}"},
    {"name": "style",       "prompt": f"Review style and best practices:\n{code}"},
    {"name": "test-gaps",   "prompt": f"What test cases are missing?\n{code}"},
])
# Each agent's findings are in its own VFS — combine, compare, or query with SQL.
```

### Self-Healing Agent

Checkpoint before risky operations, automatically restore on failure:

```python
# examples/self_healing_agent.py
cp = db.checkpoint(agent, label="pre-migration")
try:
    result = await ccr.run_agent(agent, "Migrate the database schema to v3")
except Exception:
    db.restore(agent, cp)  # roll back just this agent
    # other agents keep running, unaffected
```

### Post-Mortem Debugging

An agent broke something. Figure out exactly what happened:

```python
# examples/post_mortem.py
# What files did it touch?
db.query("SELECT path, version FROM files WHERE agent_id = ?", [agent_id])

# What tool calls failed?
db.query("""
    SELECT tool_name, error, duration_ms
    FROM tool_calls
    WHERE agent_id = ? AND status = 'error'
    ORDER BY timestamp
""", [agent_id])

# Full event timeline
db.query("""
    SELECT timestamp, event_type, payload FROM events
    WHERE agent_id = ? ORDER BY timestamp
""", [agent_id])

# How much did it cost?
db.query("SELECT SUM(token_count) FROM tool_calls WHERE agent_id = ?", [agent_id])
```

### Export & Share Agent State

```python
# examples/export_share.py
# Export a single agent's complete state to a standalone file
# kaos export <agent-id> -o agent-snapshot.db

# Send to teammate, they import it:
# kaos import agent-snapshot.db

# Or just copy the whole database:
# cp kaos.db full-backup.db
```

---

## Architecture
![alt text](image.png)


## Configuration

```yaml
# kaos.yaml
database:
  path: ./kaos.db
  wal_mode: true
  compression: zstd

models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, code_completion]
  qwen2.5-coder-32b:
    vllm_endpoint: http://localhost:8001/v1
    max_context: 131072
    use_for: [moderate, code_generation]
  deepseek-r1-70b:
    vllm_endpoint: http://localhost:8002/v1
    max_context: 131072
    use_for: [complex, critical, planning]

router:
  classifier_model: qwen2.5-coder-7b
  fallback_model: deepseek-r1-70b
  context_compression: true

ccr:
  max_iterations: 100
  checkpoint_interval: 10
  max_parallel_agents: 8
```

## Project Structure

```
kaos/
├── core.py                  # Kaos VFS engine
├── schema.py                # SQLite schema (8 tables)
├── blobs.py                 # Content-addressable blob store (SHA-256 + zstd)
├── events.py                # Append-only event journal (14 event types)
├── checkpoints.py           # Checkpoint / restore / diff
├── isolation.py             # Logical isolation + optional FUSE tier
├── ccr/
│   ├── runner.py            # Agent execution loop (plan → act → observe)
│   └── tools.py             # Tool registry (8 built-in tools)
├── router/
│   ├── gepa.py              # Intelligent model routing
│   ├── classifier.py        # LLM + heuristic complexity classifier
│   ├── context.py           # Multi-stage context compression
│   └── vllm_client.py       # Raw httpx client (no SDK dependency)
├── mcp/
│   └── server.py            # MCP server (11 tools, stdio + SSE)
└── cli/
    ├── main.py              # 15 CLI commands
    └── dashboard.py         # Live TUI dashboard (Textual)
```

## Zero Bloat

KAOS has **no AI SDK dependencies**. No `openai`. No `litellm`. No `langchain`. Just 44 packages total:

| Package | Why |
|---|---|
| `httpx` | Raw HTTP to any OpenAI-compatible endpoint |
| `click` | CLI |
| `rich` + `textual` | Terminal UI + dashboard |
| `mcp` | MCP server protocol |
| `pyyaml` | Config |
| `zstandard` | Blob compression |
| `ulid-py` | Time-sortable unique IDs |

---

## Tutorials & Docs

- **[Run a Free Local Multi-Agent System](docs/tutorial-local-agents.md)** — End-to-end guide: vLLM + KAOS + Claude Code, from zero to running parallel agents on your own GPU at zero cost.
- [MCP Server Integration](docs/mcp-integration.md) — Full reference for all 11 MCP tools.
- [Architecture](docs/architecture.md) — System design deep dive.
- [Database Schema](docs/schema.md) — All 8 tables documented.

## License

Apache 2.0

## Author

**Danilo Canivel**

---

*Built because agents deserve better infrastructure than "just use a temp directory."*
