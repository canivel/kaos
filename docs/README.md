# KAOS Documentation

**Kernel for Agent Orchestration & Sandboxing** — runtime infrastructure for multi-agent AI.

Every agent gets an isolated filesystem, automatic checkpointing, a full audit trail, and a live dashboard — all in a single SQLite file.

---

## Get started

```bash
git clone https://github.com/canivel/kaos.git && cd kaos
uv sync
kaos setup       # configure models, init database, install MCP server
kaos demo        # see it in action — no API keys needed
```

---

## Philosophy

| | |
|---|---|
| [Design Philosophy](philosophy.md) | Why KAOS integrates research rather than inventing solutions, integration criteria, what's next |

---

## Guides

| Guide | What it covers |
|---|---|
| [Dashboard](dashboard.md) | Gantt timeline, agent inspector, live events, multi-project |
| [Checkpoints](checkpoints.md) | Snapshot, restore, diff, auto-checkpointing, storage |
| [Use Cases](use-cases.md) | Code review swarm, parallel refactor, self-healing, post-mortem, incident response, ML research |
| [MCP Integration](mcp-integration.md) | Claude Code / Cursor setup, all 25 MCP tools |
| [Meta-Harness](meta-harness.md) | Automated prompt/strategy optimization search |
| [CLI Reference](cli-reference.md) | Every command, every flag |
| [Cross-Agent Memory](memory.md) | FTS5 searchable memory across agents and sessions |
| [Shared Log](shared-log.md) | LogAct intent/vote/decide coordination protocol |

---

## Reference

| Reference | What it covers |
|---|---|
| [Schema](schema.md) | All 10 SQLite tables, columns, indexes |
| [Architecture](architecture.md) | Internal subsystems, data flow, design decisions |
| [Deployment](deployment.md) | vLLM setup, production config, Docker |

---

## Tutorials

| Tutorial | What it covers |
|---|---|
| [Local Agents](tutorial-local-agents.md) | Running fully autonomous agents with local vLLM |
| [Autoresearch](tutorial-autoresearch.md) | N parallel hypothesis agents, SQL result comparison |

---

## Use with AI coding tools

After `kaos setup`, KAOS is available as an MCP tool in Claude Code, Cursor, and other compatible clients. Just describe what you want:

```
with kaos, review my payments module — security agent and test-writing agent in parallel
```

```
with kaos, refactor auth.py — implement, test, and document in parallel
```

```
with kaos, show me all agents that failed in the last run and what errors they hit
```

See [MCP Integration](mcp-integration.md) for setup details.

---

## Key concepts

**Virtual filesystem (VFS)** — each agent has its own isolated filesystem inside the SQLite database. Agents cannot access each other's files. Operations are enforced at the SQL level (`WHERE agent_id = ?`), not by convention.

**Checkpoint** — a snapshot of an agent's files and KV state at a point in time. Restore to any checkpoint in milliseconds. Diff two checkpoints to see exactly what changed. See [Checkpoints](checkpoints.md).

**Audit trail** — every file read, write, tool call, state change, and lifecycle event is recorded as an append-only row in the `events` table. Query with SQL. See [Schema](schema.md).

**GEPA router** — the Generalized Execution Planning & Allocation router classifies task complexity and routes to the right model tier. Trivial → local 7B. Complex → 70B or Claude. See [Architecture](architecture.md).

**Single `.db` file** — the entire runtime is one SQLite file. Copy it to back up. Open it in any SQLite client. Send it to a teammate. No cloud, no server.

---

## Examples

See [`examples/`](../examples/) in the repository root:

- `library_basics.py` — VFS operations without LLMs
- `code_review_swarm.py` — 4 parallel review agents
- `parallel_refactor.py` — implement + test + document simultaneously
- `self_healing_agent.py` — checkpoint + auto-restore on failure
- `autonomous_research_lab.py` — N hypothesis agents with SQL result comparison
- `meta_harness_*.py` — automated prompt/strategy optimization
