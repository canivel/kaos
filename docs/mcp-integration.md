# KAOS MCP Server Integration

> How to expose KAOS as an MCP server for Claude Code and other MCP-compatible clients.

> **v0.4.2 notes:**
> - **CLI-first architecture** — `--json` output on all commands. Agents can shell out to `kaos --json ls` instead of using MCP (10-32x cheaper on tokens).
> - **Large output handling** — Agent results >4KB are stored in VFS at `/result.txt`. MCP returns a preview + pointer to use `agent_read` for the full output.
> - **stdout protection** — MCP stdio transport redirects `sys.stdout` to `sys.stderr` at startup, preventing library logging from corrupting the JSON-RPC protocol.
> - **Worker processes** — `mh_search` and `mh_resume` spawn detached workers that survive MCP disconnection. Worker logs written to `kaos-worker-*.log`.
> - **New CLI commands** — `kaos read`, `kaos logs`, `kaos mh search --dry-run`.

---

## Table of Contents

1. [Overview](#overview)
2. [CLI Alternative (v0.4.2)](#cli-alternative)
3. [Starting the MCP Server](#starting-the-mcp-server)
4. [Claude Code Integration](#claude-code-integration)
5. [Available Tools](#available-tools)
6. [Example Conversation Flows](#example-conversation-flows)

---

## Overview

KAOS implements the [Model Context Protocol](https://modelcontextprotocol.io/) (MCP), allowing Claude Code and other MCP clients to spawn agents, read/write files, create checkpoints, run SQL queries, and orchestrate parallel agent execution through natural language.

The MCP server is implemented in `kaos/mcp/server.py` using the `mcp` Python package. It wraps the `Kaos` and `ClaudeCodeRunner` instances, exposing 18 tools across 6 categories: Lifecycle, VFS, Checkpoints, Query, Orchestration, and Meta-Harness.

---

## CLI Alternative

As of v0.4.2, every CLI command supports `--json` output, making KAOS composable with any agent via shell commands:

```bash
# Structured JSON output — any agent can parse this
kaos --json ls
kaos --json status <agent-id>
kaos --json query "SELECT * FROM agents WHERE status='running'"
kaos --json mh status <search-agent-id>

# Background worker — survives parent exit
kaos mh search -b text_classify -n 10 --background
```

This is the recommended approach when:
- You want minimal token overhead (no MCP schema injection)
- You need the search to survive process restarts
- You're integrating with non-MCP agent frameworks

**Transport modes:**
- **stdio** -- Process-based transport for direct Claude Code integration. The MCP client spawns `kaos serve` as a child process and communicates via stdin/stdout.
- **SSE** -- HTTP-based transport using Server-Sent Events. Runs a Starlette/uvicorn HTTP server for network-accessible MCP integration.

---

## Starting the MCP Server

### stdio mode (recommended for Claude Code)

```bash
kaos serve --transport stdio
```

This is the default transport. The server reads MCP messages from stdin and writes responses to stdout. Claude Code manages the process lifecycle.

**Options:**
```bash
kaos serve \
  --transport stdio \
  --db ./kaos.db \
  --config-file ./kaos.yaml
```

### SSE mode (network access)

```bash
kaos serve --transport sse --host 127.0.0.1 --port 3100
```

This starts an HTTP server with two endpoints:
- `GET /sse` -- SSE connection endpoint for MCP clients.
- `POST /messages` -- Message posting endpoint for MCP clients.

**Options:**
```bash
kaos serve \
  --transport sse \
  --host 0.0.0.0 \
  --port 3100 \
  --db ./kaos.db \
  --config-file ./kaos.yaml
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `KAOS_DB` | `./kaos.db` | Database file path (overridden by `--db`). |
| `KAOS_CONFIG` | `./kaos.yaml` | Configuration file path (overridden by `--config-file`). |

### Without a config file

If `kaos.yaml` is not found, the server starts with a single default model endpoint at `http://localhost:8000/v1`. This allows using the MCP server for non-LLM operations (file management, checkpoints, queries) without any vLLM setup.

---

## Claude Code Integration

### settings.json configuration

Add the KAOS MCP server to your Claude Code settings file (`~/.claude/settings.json`):

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

### With custom database and config paths

```json
{
  "mcpServers": {
    "kaos": {
      "command": "kaos",
      "args": [
        "serve",
        "--transport", "stdio",
        "--db", "/path/to/project/kaos.db",
        "--config-file", "/path/to/project/kaos.yaml"
      ]
    }
  }
}
```

### Using uv to run from source

If KAOS is not installed globally, you can use `uv run`:

```json
{
  "mcpServers": {
    "kaos": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/kaos",
        "kaos", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

### Verifying the integration

After adding the configuration and restarting Claude Code, you should see the KAOS tools available. You can verify by asking Claude Code:

> "What KAOS tools are available?"

Claude Code should list all 18 KAOS tools.

---

## Available Tools

### agent_spawn

Spawn a new agent with an isolated virtual filesystem and immediately run a task.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Name for the agent. |
| `task` | string | yes | Task description for the agent to execute. |
| `config` | object | no | Agent configuration (model, temperature, etc.). Default: `{}`. |

**Returns:** JSON with `agent_id` and `result`.

**Example:**
```json
{
  "name": "test-writer",
  "task": "Write unit tests for the authentication module",
  "config": {"force_model": "deepseek-r1-70b"}
}
```

**Response:**
```json
{
  "agent_id": "01HXY...",
  "result": "I've written 12 unit tests covering..."
}
```

---

### agent_spawn_only

Spawn a new agent without running it. Useful for pre-populating the VFS before execution.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Name for the agent. |
| `config` | object | no | Agent configuration. Default: `{}`. |

**Returns:** JSON with `agent_id` and `status`.

**Example:**
```json
{
  "name": "code-analyzer"
}
```

**Response:**
```json
{
  "agent_id": "01HXY...",
  "status": "initialized"
}
```

---

### agent_read

Read a file from an agent's virtual filesystem.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `path` | string | yes | File path to read. |

**Returns:** File content as UTF-8 text.

**Example:**
```json
{
  "agent_id": "01HXY...",
  "path": "/src/auth.py"
}
```

---

### agent_write

Write a file to an agent's virtual filesystem.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `path` | string | yes | File path. |
| `content` | string | yes | File content. |

**Returns:** Confirmation with byte count.

**Example:**
```json
{
  "agent_id": "01HXY...",
  "path": "/src/auth.py",
  "content": "def authenticate(user, password):\n    ..."
}
```

**Response:**
```
Written 142 bytes to 01HXY...:/src/auth.py
```

---

### agent_ls

List files in an agent's virtual filesystem.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `path` | string | no | Directory path. Default: `/`. |

**Returns:** JSON array of file entries with path, name, is_dir, size, modified_at, and version.

**Example:**
```json
{
  "agent_id": "01HXY...",
  "path": "/src"
}
```

**Response:**
```json
[
  {"path": "/src/auth.py", "name": "auth.py", "is_dir": false, "size": 1234, "modified_at": "2026-03-30T10:00:00.000", "version": 2},
  {"path": "/src/utils", "name": "utils", "is_dir": true, "size": 0, "modified_at": "2026-03-30T09:55:00.000", "version": 1}
]
```

---

### agent_status

Get status of one agent or list all agents.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | no | Agent ID. Omit to list all agents. |
| `status_filter` | string | no | Filter by status (`running`, `completed`, `failed`, etc.). |

**Returns:** JSON object (single agent) or JSON array (all agents).

**Example (single agent):**
```json
{
  "agent_id": "01HXY..."
}
```

**Response:**
```json
{
  "agent_id": "01HXY...",
  "name": "test-writer",
  "parent_id": null,
  "created_at": "2026-03-30T10:00:00.000",
  "status": "completed",
  "config": {"force_model": "deepseek-r1-70b"},
  "metadata": {},
  "pid": 12345,
  "last_heartbeat": "2026-03-30T10:05:00.000"
}
```

**Example (list all running):**
```json
{
  "status_filter": "running"
}
```

---

### agent_checkpoint

Create a snapshot of an agent's current state (files + KV store).

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `label` | string | no | Optional label for the checkpoint. |

**Returns:** Confirmation with checkpoint ID.

**Example:**
```json
{
  "agent_id": "01HXY...",
  "label": "pre-refactor"
}
```

**Response:**
```
Checkpoint 01HABC... created for agent 01HXY...
```

---

### agent_restore

Restore an agent to a previous checkpoint.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `checkpoint_id` | string | yes | Checkpoint ID to restore. |

**Returns:** Confirmation.

**Example:**
```json
{
  "agent_id": "01HXY...",
  "checkpoint_id": "01HABC..."
}
```

**Response:**
```
Agent 01HXY... restored to checkpoint 01HABC...
```

---

### agent_diff

Compare two checkpoints of an agent, showing file and state differences.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |
| `from_checkpoint` | string | yes | Source checkpoint ID. |
| `to_checkpoint` | string | yes | Target checkpoint ID. |

**Returns:** JSON object with file changes, state changes, and tool calls between checkpoints.

**Example:**
```json
{
  "agent_id": "01HXY...",
  "from_checkpoint": "01HABC...",
  "to_checkpoint": "01HDEF..."
}
```

**Response:**
```json
{
  "files": {
    "added": ["/src/new_module.py"],
    "removed": [],
    "modified": ["/src/auth.py"]
  },
  "state": {
    "added": {"new_key": "value"},
    "removed": {},
    "modified": {"iteration": {"from": 5, "to": 15}}
  },
  "tool_calls": [
    {"call_id": "...", "tool_name": "fs_write", "status": "success", "duration_ms": 12, "token_count": 500}
  ]
}
```

---

### agent_query

Run a read-only SQL query against the KAOS database.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `sql` | string | yes | SQL SELECT query. |

**Returns:** JSON array of result rows.

**Example:**
```json
{
  "sql": "SELECT name, status, created_at FROM agents ORDER BY created_at DESC LIMIT 5"
}
```

**Response:**
```json
[
  {"name": "test-writer", "status": "completed", "created_at": "2026-03-30T10:00:00.000"},
  {"name": "refactorer", "status": "running", "created_at": "2026-03-30T09:55:00.000"}
]
```

**Note:** Only SELECT queries are allowed. INSERT, UPDATE, DELETE, DROP, ALTER, and CREATE are rejected with a `PermissionError`.

---

### agent_kill

Kill a running agent.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID to kill. |

**Returns:** Confirmation.

**Example:**
```json
{
  "agent_id": "01HXY..."
}
```

**Response:**
```
Agent 01HXY... killed
```

---

### agent_parallel

Spawn and run multiple agents in parallel.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `tasks` | array | yes | Array of task objects, each with `name` (string, required), `prompt` (string, required), and `config` (object, optional). |

**Returns:** JSON array of results with index.

**Example:**
```json
{
  "tasks": [
    {"name": "test-writer", "prompt": "Write unit tests for payments"},
    {"name": "doc-writer", "prompt": "Update payment API documentation"},
    {"name": "refactorer", "prompt": "Refactor payments to use Stripe v3", "config": {"force_model": "deepseek-r1-70b"}}
  ]
}
```

**Response:**
```json
[
  {"index": 0, "result": "I've written 8 test cases covering..."},
  {"index": 1, "result": "Updated the API docs with..."},
  {"index": 2, "result": "Refactored the payments module to..."}
]
```

---

### agent_pause

Pause a running agent. The agent can be resumed later with `agent_resume`.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID to pause. |

**Returns:** Confirmation.

---

### agent_resume

Resume a paused agent.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID to resume. |

**Returns:** Confirmation.

---

### agent_checkpoints

List all checkpoints for an agent.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string | yes | Agent ID. |

**Returns:** JSON array of checkpoints with `checkpoint_id`, `label`, `created_at`, and `event_id`.

**Example:**
```json
{"agent_id": "01HXY..."}
```

**Response:**
```json
[
  {"checkpoint_id": "01HABC...", "label": "pre-refactor", "created_at": "2026-03-31T10:00:00.000", "event_id": 42},
  {"checkpoint_id": "01HDEF...", "label": "post-refactor", "created_at": "2026-03-31T10:15:00.000", "event_id": 87}
]
```

---

### mh_search

Run a Meta-Harness search to automatically optimize a harness for a benchmark. The search evaluates seed harnesses, then iteratively proposes and evaluates improvements using full execution traces.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `benchmark` | string | yes | Benchmark name: `text_classify`, `math_rag`, `agentic_coding`, `lawbench`, `symptom2disease`, `uspto_50k`, or a custom registered benchmark. |
| `max_iterations` | integer | no | Number of search iterations. Default: 10. |
| `candidates_per_iteration` | integer | no | Candidates proposed per iteration. Default: 2. |
| `config` | object | no | Additional SearchConfig overrides. |

**Returns:** JSON with `search_agent_id`, `summary`, `frontier`, `total_harnesses`, and `duration_seconds`.

**Example:**
```json
{"benchmark": "text_classify", "max_iterations": 10, "candidates_per_iteration": 2}
```

---

### mh_frontier

Get the Pareto frontier of a completed Meta-Harness search.

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `search_agent_id` | string | yes | Search agent ID returned by `mh_search`. |

**Returns:** JSON with the Pareto frontier (harness IDs, scores, iterations).

---

### mh_resume

Resume an interrupted Meta-Harness search from its last completed iteration. All prior harness evaluations, traces, and Pareto frontier state are preserved. The search continues with the same configuration (benchmark, candidates per iteration, objectives).

**Parameters:**

| Name | Type | Required | Description |
|---|---|---|---|
| `search_agent_id` | string | yes | Search agent ID of the interrupted search. |

**Returns:** JSON with `search_agent_id`, `summary`, `frontier`, `total_harnesses`, `resumed_from_iteration`, and `duration_seconds`.

**Example:**
```json
{
  "search_agent_id": "01HXY..."
}
```

**Response:**
```json
{
  "search_agent_id": "01HXY...",
  "resumed_from_iteration": 4,
  "summary": "Resumed search from iteration 4, completed 10 total iterations",
  "frontier": [...],
  "total_harnesses": 23,
  "duration_seconds": 512.7
}
```

---

## Example Conversation Flows

### Flow 1: Spawn an agent to write tests

**User:** "Use KAOS to spawn an agent that writes unit tests for my auth module."

**Claude Code calls:** `agent_spawn`
```json
{"name": "auth-tester", "task": "Write comprehensive unit tests for the authentication module covering login, logout, token refresh, and edge cases."}
```

**Claude Code receives result and responds:**
"I spawned agent `auth-tester` (ID: 01HXY...) which wrote 15 unit tests. Here's a summary of what it covered..."

---

### Flow 2: Pre-populate files, then run

**User:** "Create an agent with some existing code, then have it refactor."

**Claude Code calls:** `agent_spawn_only`
```json
{"name": "refactorer"}
```

**Claude Code calls:** `agent_write`
```json
{"agent_id": "01HXY...", "path": "/src/payments.py", "content": "def charge(amount): ..."}
```

**Claude Code calls:** `agent_write`
```json
{"agent_id": "01HXY...", "path": "/tests/test_payments.py", "content": "def test_charge(): ..."}
```

**Claude Code calls:** `agent_checkpoint`
```json
{"agent_id": "01HXY...", "label": "before-refactor"}
```

**User:** "Now run the agent to refactor."

**Claude Code calls:** `agent_spawn` (with a new task referencing the existing files).

---

### Flow 3: Investigate what an agent did

**User:** "What did the refactorer agent do? Show me its file changes."

**Claude Code calls:** `agent_query`
```json
{"sql": "SELECT event_type, payload, timestamp FROM events WHERE agent_id = '01HXY...' ORDER BY event_id"}
```

**Claude Code calls:** `agent_ls`
```json
{"agent_id": "01HXY...", "path": "/"}
```

**Claude Code calls:** `agent_read`
```json
{"agent_id": "01HXY...", "path": "/src/payments.py"}
```

**Claude Code responds with a summary of the agent's actions and the final file contents.**

---

### Flow 4: Parallel code review swarm

**User:** "Review this code from 4 angles: security, performance, style, and test coverage."

**Claude Code calls:** `agent_parallel`
```json
{
  "tasks": [
    {"name": "security-reviewer", "prompt": "Review this code for security vulnerabilities: ...", "config": {"force_model": "deepseek-r1-70b"}},
    {"name": "performance-reviewer", "prompt": "Review this code for performance issues: ..."},
    {"name": "style-reviewer", "prompt": "Review this code for style and best practices: ..."},
    {"name": "test-reviewer", "prompt": "Suggest test cases needed for this code: ..."}
  ]
}
```

**Claude Code aggregates the 4 results and presents a unified review.**

---

### Flow 5: Checkpoint and rollback

**User:** "The refactor broke things. Roll back to the checkpoint we made earlier."

**Claude Code calls:** `agent_query`
```json
{"sql": "SELECT checkpoint_id, label, created_at FROM checkpoints WHERE agent_id = '01HXY...' ORDER BY created_at"}
```

**Claude Code identifies the checkpoint labeled "before-refactor".**

**Claude Code calls:** `agent_restore`
```json
{"agent_id": "01HXY...", "checkpoint_id": "01HABC..."}
```

**Claude Code calls:** `agent_diff`
```json
{"agent_id": "01HXY...", "from_checkpoint": "01HABC...", "to_checkpoint": "01HDEF..."}
```

**Claude Code responds:** "Rolled back to the pre-refactor state. Here's what was undone: 3 files modified, 1 file added (now removed)."

---

### Flow 6: Monitor and debug

**User:** "Show me which agents are running and how many tokens they've used."

**Claude Code calls:** `agent_status`
```json
{"status_filter": "running"}
```

**Claude Code calls:** `agent_query`
```json
{"sql": "SELECT a.name, SUM(tc.token_count) as tokens, COUNT(tc.call_id) as calls FROM agents a LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id WHERE a.status = 'running' GROUP BY a.agent_id"}
```

**Claude Code presents a summary table of running agents with their token consumption.**

---

### Flow 7: Pause and resume an agent

**User:** "Pause the refactorer agent, I want to review what it's done so far."

**Claude Code calls:** `agent_pause`
```json
{"agent_id": "01HXY..."}
```

**User:** "OK, looks good. Resume it."

**Claude Code calls:** `agent_resume`
```json
{"agent_id": "01HXY..."}
```

---

### Flow 8: Run a Meta-Harness search

**User:** "Use Meta-Harness to optimize my text classification harness."

**Claude Code calls:** `mh_search`
```json
{"benchmark": "text_classify", "max_iterations": 10, "candidates_per_iteration": 2}
```

**Claude Code receives the Pareto frontier and presents:**
"Meta-Harness evaluated 23 harnesses over 10 iterations. Best accuracy: 87% (harness 01HXY1F...). Best cost efficiency: 45 tokens/prediction (harness 01HXY1G...)."

**User:** "Show me the full frontier."

**Claude Code calls:** `mh_frontier`
```json
{"search_agent_id": "01HXY..."}
```

---

### Flow 9: Resume an interrupted Meta-Harness search

**User:** "My Meta-Harness search crashed at iteration 4. Can you resume it?"

**Claude Code calls:** `mh_resume`
```json
{"search_agent_id": "01HXY..."}
```

**Claude Code receives the result and responds:**
"Resumed the search from iteration 4. It completed 10 total iterations and evaluated 23 harnesses. Best accuracy: 87% (harness 01HXY1F...). The full frontier has 4 Pareto-optimal harnesses."
