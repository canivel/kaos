# KAOS

**Runtime infrastructure for multi-agent AI.** Every agent gets its own isolated filesystem, automatic checkpointing, a full audit trail, and a live dashboard — all in a single SQLite file.

[![Version](https://img.shields.io/badge/version-0.6.0-blueviolet)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-orange)]()

![KAOS — parallel agents, Gantt dashboard, live events](docs/demos/kaos_03_parallel_agents.gif)

---

## Install

```bash
git clone https://github.com/canivel/kaos.git && cd kaos
uv sync
kaos setup
```

> Need `uv`? → `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Try the demo instantly (no API keys needed):**

```bash
kaos demo
```

Opens a live dashboard with 3 example execution waves so you can see what KAOS looks like before writing any code.

---

## Use with Claude Code / Cursor / any AI coding tool

After `kaos setup`, KAOS registers itself as an MCP server. Then just ask your AI assistant:

```
with kaos, review my payments module — run a security agent and a test-writing agent in parallel
```

```
with kaos, refactor auth.py — three agents in parallel: implement, test, and document
```

```
with kaos, why did the last run fail? show me the agent that errored and its tool calls
```

KAOS handles isolation, checkpointing, and the dashboard automatically.

---

## What it does

| Problem | Without KAOS | With KAOS |
|---|---|---|
| Two agents write the same file | One overwrites the other | Each has its own copy — enforced at the SQL level |
| Agent crashes mid-task | Progress lost | Auto-checkpointed, resume from last snapshot |
| Agent breaks everything | `git reset --hard`, lose all other work | `db.restore(agent, checkpoint)` — only that agent rolls back |
| What did it actually do? | Read logs, if you have them | `SELECT * FROM events WHERE agent_id = ?` |
| Cost tracking | Manual | `SELECT SUM(token_count) FROM tool_calls` |

---

## Run agents

**CLI:**
```bash
kaos run "refactor auth.py" -n auth-agent        # single agent
kaos parallel \
  -t security "find vulnerabilities" \
  -t tests    "write unit tests" \
  -t docs     "update API docs"                   # parallel agents
```

**Python:**
```python
from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter

db     = Kaos("project.db")
ccr    = ClaudeCodeRunner(db, GEPARouter.from_config("kaos.yaml"))

results = asyncio.run(ccr.run_parallel([
    {"name": "security", "prompt": "Find vulnerabilities in auth.py"},
    {"name": "tests",    "prompt": "Write unit tests for auth.py"},
]))
```

---

## Inspect & debug

```bash
kaos ls                            # list all agents + status
kaos logs <id>                     # conversation + event log
kaos read <id> /path/to/file       # read a file from the agent's VFS
kaos checkpoint <id> -l "safe"     # snapshot agent state
kaos restore <id> --checkpoint X   # roll back to that snapshot
kaos diff <id> --from X --to Y     # what changed between checkpoints?
kaos query "SELECT * FROM events"  # raw SQL on everything
kaos ui                            # open the web dashboard
```

---

## Dashboard

```bash
kaos ui        # web dashboard — Gantt timeline, live events, agent inspector
kaos dashboard # terminal TUI
kaos demo      # demo data + open dashboard
```

The web dashboard shows each execution wave as a **Gantt timeline**: one horizontal bar per agent, colored by status (green = done, purple = running, red = failed). Click any bar to inspect tool calls, files, checkpoints, and events.

---

## Python library

```python
from kaos import Kaos

db = Kaos("project.db")

# Each agent has its own isolated filesystem
a = db.spawn("refactorer")
b = db.spawn("test-writer")
db.write(a, "/src/auth.py", b"# refactored")
db.write(b, "/src/auth.py", b"# tests")  # no conflict — separate VFS

# Checkpoint / restore
cp = db.checkpoint(a, label="before-migration")
# ... agent does work ...
db.restore(a, cp)  # roll back just this agent

# Query everything with SQL
db.query("SELECT name, status FROM agents")
db.query("SELECT SUM(token_count) FROM tool_calls WHERE agent_id = ?", [a])
```

---

## Documentation

| | |
|---|---|
| [Dashboard](docs/dashboard.md) | Gantt timeline, agent inspector, live events |
| [Use Cases](docs/use-cases.md) | Code review swarm, parallel refactor, incident response, ML research, and more |
| [Checkpoints](docs/checkpoints.md) | Snapshot, restore, diff — with examples |
| [CLI Reference](docs/cli-reference.md) | Every command and flag |
| [MCP Integration](docs/mcp-integration.md) | Claude Code / Cursor setup, all 18 tools |
| [Meta-Harness](docs/meta-harness.md) | Automated prompt/strategy optimization |
| [Architecture](docs/architecture.md) | Internals, subsystem design |
| [Schema](docs/schema.md) | All 8 SQLite tables |
| [Deployment](docs/deployment.md) | vLLM, production config |

Full docs index → [`docs/`](docs/)

---

## Examples

See [`examples/`](examples/) for:
- `code_review_swarm.py` — 4 agents review code in parallel
- `parallel_refactor.py` — implement + test + document simultaneously
- `self_healing_agent.py` — auto-restore on failure
- `autonomous_research_lab.py` — N hypothesis agents, SQL result comparison
- `meta_harness_*.py` — automated prompt/strategy optimization

---

## How agents are isolated

Each agent's files, state, tool calls, and events are stored in separate rows scoped by `agent_id`. There is no shared filesystem — it's enforced at the query level, not by convention. The entire runtime is one `.db` file you can copy, share, or open in any SQLite client.
