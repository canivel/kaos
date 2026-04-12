# KAOS CLI Reference

All commands support `--json` for structured output (composable with `jq` and agent frameworks).

```bash
kaos --json <command>
```

---

## Setup & Init

### `kaos setup`
Interactive wizard. Picks a model preset, generates `kaos.yaml`, initializes the database, and auto-installs the MCP server into Claude Code.

```bash
kaos setup
```

Presets: Claude (Sonnet/Opus), OpenAI (GPT-4o), local vLLM (7B/70B), or custom endpoint.

### `kaos init`
Initialize a new database at the default path (`./kaos.db`) or a custom path.

```bash
kaos init
kaos init --db ./my-project.db
```

### `kaos demo`
Seed a demo database with realistic agent data and open the web dashboard. No API keys needed.

```bash
kaos demo
kaos demo --port 9000
kaos demo --no-browser
```

Creates `demo.db` with 3 execution waves: code review swarm, parallel refactor, prod triage.

---

## Running Agents

### `kaos run`
Spawn and run a single agent.

```bash
kaos run "Refactor auth.py to use JWT tokens" --name auth-agent
kaos run "Find security vulnerabilities" --name security --db ./project.db
```

Options:
- `--name`, `-n` — agent name (auto-generated if omitted)
- `--db` — database path (default: `./kaos.db`)

### `kaos parallel`
Run multiple agents simultaneously. Each `-t name "prompt"` pair is one agent.

```bash
kaos parallel \
  -t security  "Find vulnerabilities in auth.py" \
  -t tests     "Write unit tests for auth.py" \
  -t docs      "Update API documentation"
```

Options:
- `-t name prompt` — define an agent (repeatable)
- `--db` — database path

---

## Inspecting Agents

### `kaos ls`
List all agents with status, file count, and tool call count.

```bash
kaos ls
kaos ls --db ./project.db
kaos --json ls | jq '.[] | select(.status == "failed")'
```

### `kaos status`
Detailed status for one agent.

```bash
kaos status <agent-id>
kaos --json status <agent-id>
```

### `kaos logs`
Full conversation log and event timeline for an agent.

```bash
kaos logs <agent-id>
kaos logs <agent-id> --tail 20    # last 20 events
```

### `kaos read`
Read a file from an agent's virtual filesystem.

```bash
kaos read <agent-id> /path/to/file
kaos read <agent-id> /src/auth.py
```

---

## Checkpoints

### `kaos checkpoint`
Create a named snapshot of an agent's files and state.

```bash
kaos checkpoint <agent-id> --label "before-migration"
kaos checkpoint <agent-id> -l "pre-refactor"
```

### `kaos checkpoints`
List all checkpoints for an agent.

```bash
kaos checkpoints <agent-id>
kaos --json checkpoints <agent-id>
```

### `kaos restore`
Roll back an agent to a previous checkpoint. Other agents are unaffected.

```bash
kaos restore <agent-id> --checkpoint <checkpoint-id>
```

Get checkpoint IDs from `kaos checkpoints <agent-id>`.

### `kaos diff`
Show what changed between two checkpoints: files added/removed/modified, state changes.

```bash
kaos diff <agent-id> --from <checkpoint-id-A> --to <checkpoint-id-B>
```

---

## Querying

### `kaos query`
Run arbitrary SQL against the database.

```bash
kaos query "SELECT name, status FROM agents"
kaos query "SELECT SUM(token_count) FROM tool_calls"
kaos query "SELECT * FROM events WHERE agent_id = 'abc123' ORDER BY timestamp"
```

See [schema reference](schema.md) for all tables.

### `kaos search`
Full-text search across all agent files and state.

```bash
kaos search "SQL injection"
kaos search "ConnectionError" --db ./project.db
kaos --json search "keyword" | jq '.results'
```

### `kaos index`
Build a `/index.md` file in an agent's VFS summarizing all its files (for faster search).

```bash
kaos index <agent-id>
```

---

## Agent Lifecycle

### `kaos kill`
Terminate a running agent.

```bash
kaos kill <agent-id>
```

### `kaos export`
Export a single agent's complete state to a standalone database file.

```bash
kaos export <agent-id> --output agent-snapshot.db
```

### `kaos import`
Import an agent from an exported database file.

```bash
kaos import agent-snapshot.db
```

---

## Dashboard & Monitoring

### `kaos ui`
Launch the web dashboard. Opens a browser tab with the Gantt timeline, live event feed, and agent inspector.

```bash
kaos ui
kaos ui --port 9000
kaos ui --db ./project.db --no-browser
```

See [Dashboard guide](dashboard.md) for details.

### `kaos dashboard`
Launch the terminal TUI monitor.

```bash
kaos dashboard
kaos dashboard --db ./project.db
```

---

## MCP Server

### `kaos serve`
Start the MCP server (18 tools) for Claude Code and other MCP-compatible clients.

```bash
kaos serve --transport stdio       # for Claude Code / most clients
kaos serve --transport sse         # HTTP/SSE transport
kaos serve --port 8765             # custom port (SSE only)
```

See [MCP integration guide](mcp-integration.md) for setup.

---

## Meta-Harness

Commands for running automated prompt/strategy optimization searches.

```bash
kaos mh search -b <benchmark> -n <iterations>   # start a search
kaos mh search -b text_classify -n 10 -k 2      # 10 iterations, 2 candidates each
kaos mh search -b lawbench -n 20 --background   # run detached
kaos mh status <search-id>                       # poll progress
kaos mh frontier <search-id>                     # view best harnesses
kaos mh knowledge                                # view persistent knowledge base
kaos mh resume <search-id>                       # resume interrupted search
```

See [Meta-Harness guide](meta-harness.md) for details.

---

## Global Options

| Flag | Description |
|---|---|
| `--json` | Output structured JSON (auto-enabled when stdout is piped) |
| `--db PATH` | Database file (default: `$KAOS_DB` or `./kaos.db`) |
| `--version` | Print version |
| `--help` | Help for any command |

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `KAOS_DB` | `./kaos.db` | Default database path |
| `KAOS_CONFIG` | `./kaos.yaml` | Config file path |
