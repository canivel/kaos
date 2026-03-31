# KAOS Architecture

> Kernel for Agent Orchestration & Sandboxing

This document describes the internal architecture of KAOS: its design philosophy, subsystem boundaries, data flow, and integration points.

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Design Philosophy](#design-philosophy)
3. [VFS Engine](#vfs-engine)
4. [Isolation Model](#isolation-model)
5. [CCR Execution Loop](#ccr-execution-loop)
6. [GEPA Router](#gepa-router)
7. [MCP Server Integration](#mcp-server-integration)
8. [Data Flow](#data-flow)

---

## System Overview

KAOS is a runtime framework for managing autonomous AI agents. Each agent receives an isolated, auditable virtual filesystem backed by a single SQLite database file. The system is composed of five major subsystems:

```
                     External Clients
                    (Claude Code, CLI)
                           |
                           v
        +------------------------------------------+
        |           MCP Server / CLI               |
        |          (kaos.mcp / kaos.cli)            |
        +-----+------------------+-----------------+
              |                  |
              v                  v
     +----------------+  +----------------+
     |      CCR       |  |     GEPA       |
     | Execution Loop |->|    Router      |---> vLLM Instances
     | (kaos.ccr)     |  | (kaos.router)  |     (httpx)
     +-------+--------+  +----------------+
             |
             v
     +------------------------------------------+
     |            KAOS Core (Kaos)            |
     |              (kaos.core)                  |
     |                                           |
     |  +----------+ +--------+ +-------------+ |
     |  | BlobStore| | Event  | | Checkpoint  | |
     |  | (blobs)  | | Journal| | Manager     | |
     |  +----------+ +--------+ +-------------+ |
     |               |                           |
     |               v                           |
     |      +------------------+                 |
     |      |   SQLite (.db)   |                 |
     |      |   WAL mode       |                 |
     |      +------------------+                 |
     +------------------------------------------+
```

**Package:** `kaos`
**CLI entry point:** `kaos` (defined in `kaos.cli.main:cli`)
**Configuration file:** `kaos.yaml`

---

## Design Philosophy

### Single-file portability

Everything an agent produces -- files, state, tool call logs, event history, checkpoints -- lives in one `.db` file. Copying, backing up, or transferring an agent runtime is `cp kaos.db backup.db`. Any SQLite client can query the database.

### Zero AI SDK dependencies

KAOS uses no `openai`, no `litellm`, no `dspy`. All communication with vLLM inference endpoints is done through raw `httpx` HTTP calls to the OpenAI-compatible `/v1/chat/completions` API. This eliminates SDK version conflicts, reduces the dependency tree, and keeps the attack surface minimal.

### Isolation by default

Agent isolation is not a convention; it is enforced at the query level. Every VFS operation requires an `agent_id` parameter, and every SQL query is scoped by `WHERE agent_id = ?`. There is no API surface that allows cross-agent data access.

### Append-only auditability

The event journal is append-only. Every file read, write, delete, state change, tool call, and lifecycle transition is recorded with a timestamp. This produces a complete, tamper-evident audit trail for every agent.

### Composition over inheritance

KAOS subsystems are composed rather than subclassed. `Kaos` owns a `BlobStore`, an `EventJournal`, and a `CheckpointManager`. The `ClaudeCodeRunner` delegates inference to the `GEPARouter`. The MCP server delegates to both. Each subsystem can be tested, replaced, or extended independently.

---

## VFS Engine

The VFS Engine is the core of KAOS, implemented in `kaos/core.py` as the `Kaos` class. It provides a virtual filesystem, state management, tool call tracking, and checkpoint/restore -- all backed by SQLite.

### SQLite Configuration

```python
conn.execute("PRAGMA journal_mode=WAL")    # Write-Ahead Logging
conn.execute("PRAGMA foreign_keys=ON")      # Referential integrity
conn.execute("PRAGMA busy_timeout=5000")    # 5s retry on lock contention
```

**WAL mode** enables concurrent readers with a single writer, which is critical for multi-agent workloads. Multiple agents can read from the database simultaneously while one agent writes, without blocking.

### Thread Safety

`Kaos` uses `threading.local()` to maintain one SQLite connection per thread. This avoids the SQLite threading pitfalls while allowing true parallel agent execution in threaded environments.

```python
class Kaos:
    def __init__(self, db_path: str = "agents.db", compression: str = "zstd"):
        self._local = threading.local()
        # Each thread gets its own connection via _get_conn()
```

### Content-Addressable Blob Store

Files are stored as content-addressable blobs in the `blobs` table (`kaos/blobs.py`). The blob store provides:

- **SHA-256 deduplication**: Identical file content across any number of agents shares a single blob. The content hash is the primary key.
- **Reference counting**: Each blob tracks how many files reference it. When the count reaches zero, the blob is eligible for garbage collection.
- **zstd compression**: Blobs are compressed with zstandard at level 3 by default. This is transparent to callers -- `store()` compresses, `retrieve()` decompresses.
- **Garbage collection**: `gc()` removes blobs with `ref_count <= 0`.

```
File Write Flow:

  content bytes
       |
       v
  SHA-256 hash -----> exists in blobs table?
       |                    |            |
       |                   YES           NO
       |                    |            |
       |              ref_count += 1   compress (zstd)
       |                    |            |
       |                    |        INSERT blob
       |                    |            |
       +--------------------+------------+
       |
       v
  INSERT into files table
  (agent_id, path, content_hash, size, version)
```

### Versioned File System

Files in the VFS are versioned. Writing to an existing path creates a new version; the old version is soft-deleted (`deleted = 1`) but retained in the database. This enables:

- **File history**: `file_history(agent_id, path)` returns all versions of a file.
- **Checkpoint restore**: Deleted versions can be un-deleted when restoring a checkpoint.
- **Audit trail**: The event journal records every write with the new version number.

Paths are normalized to canonical POSIX form via `PurePosixPath`. Parent directories are created automatically when writing to a nested path.

### Event Journal

The event journal (`kaos/events.py`) is an append-only log of every significant action in the system. It records:

| Event Type | Trigger |
|---|---|
| `agent_spawn` | Agent created |
| `agent_pause` / `agent_resume` | Lifecycle transitions |
| `agent_kill` / `agent_complete` / `agent_fail` | Terminal states |
| `file_read` / `file_write` / `file_delete` | Filesystem operations |
| `state_change` | KV state modifications |
| `tool_call_start` / `tool_call_end` | Tool execution boundaries |
| `checkpoint_create` / `checkpoint_restore` | Checkpoint operations |
| `error` / `warning` | Runtime diagnostics |

Each event stores:
- `event_id` (auto-incrementing, globally ordered)
- `agent_id` (scoped to the acting agent)
- `event_type` (one of the constants above)
- `payload` (JSON object with event-specific data)
- `timestamp` (ISO 8601 with millisecond precision)

The journal supports filtered queries: by agent, by event type, by time range, and with limit/offset pagination.

### Checkpoint / Restore

The checkpoint system (`kaos/checkpoints.py`) captures point-in-time snapshots of an agent's complete state:

**Creating a checkpoint** captures:
1. **File manifest**: Every non-deleted file's `(path, content_hash, version)`.
2. **State snapshot**: All KV pairs from the `state` table for that agent.
3. **Event watermark**: The `event_id` at the time of the checkpoint, enabling event range queries between checkpoints.

**Restoring a checkpoint**:
1. Soft-deletes all current files for the agent.
2. Un-deletes or re-creates files from the manifest.
3. Replaces all state keys with the snapshot values.

**Diffing checkpoints** compares two snapshots and returns:
- Files added, removed, and modified (by `content_hash` comparison).
- State keys added, removed, and modified (with before/after values).
- Tool calls that occurred between the two checkpoint event watermarks.

---

## Isolation Model

KAOS provides two tiers of agent isolation, implemented in `kaos/isolation.py`.

### Tier 1 -- Logical Isolation (Default)

Every VFS operation is scoped by `agent_id`. The `LogicalIsolation` class wraps `Kaos` methods, binding a specific `agent_id` so the caller cannot accidentally (or intentionally) access another agent's data.

```python
class LogicalIsolation:
    def read(self, path: str) -> bytes:
        return self.afs.read(self.agent_id, path)  # always scoped
```

**Properties:**
- Zero performance overhead (just parameter binding).
- Works on all platforms (Windows, macOS, Linux).
- Isolation is enforced at the SQL level: every query includes `WHERE agent_id = ?`.

### Tier 2 -- FUSE + Namespace Isolation (Linux Only)

For environments requiring OS-level process isolation, KAOS can mount each agent's VFS as a FUSE filesystem. The `IsolatedAgentProcess` class provides:

1. **FUSE mount**: The agent's virtual filesystem is mounted at `/tmp/kaos/<agent_id>`. The agent process sees a standard filesystem -- it has no knowledge that reads and writes are backed by SQLite.
2. **Mount namespace**: Each agent runs in its own Linux mount namespace (via `unshare`), preventing cross-agent filesystem access at the kernel level.
3. **cgroups v2 resource limits**: Optional memory and CPU limits via cgroups:
   - `memory.max` caps the agent's memory usage.
   - `cpu.weight` controls CPU scheduling priority.

```
Tier 2 Isolation Stack:

  +-------------------+
  | Agent Process      |
  +-------------------+
  | Mount Namespace    |  <-- unshare(CLONE_NEWNS)
  +-------------------+
  | FUSE Mount         |  <-- /tmp/kaos/<agent_id>
  +-------------------+
  | Kaos VFS Engine |
  +-------------------+
  | SQLite WAL         |
  +-------------------+
  | cgroups v2         |  <-- memory.max, cpu.weight
  +-------------------+
```

**Requirements:**
- Linux only (`platform.system() == "Linux"`).
- `fusepy` package (`uv pip install kaos[fuse]`).
- Root or appropriate capabilities for namespace/cgroup operations.

### Isolation Factory

The `create_isolation()` factory function selects the appropriate isolation tier based on configuration:

```python
isolation = create_isolation(afs, agent_id, config)
# Returns LogicalIsolation or IsolatedAgentProcess
```

---

## CCR Execution Loop

The **Claude Code Runner** (CCR), implemented in `kaos/ccr/runner.py`, orchestrates the agent execution loop. It implements a **plan-act-observe** cycle.

### Loop Architecture

```
                  +------------------+
                  |   Task (prompt)  |
                  +--------+---------+
                           |
                           v
              +------------------------+
              |  Build System Prompt   |
              |  (agent context +      |
              |   tool descriptions)   |
              +----------+-------------+
                         |
            +============+============+
            |     MAIN CCR LOOP       |
            |  (up to max_iterations) |
            |                         |
            |  +-------------------+  |
            |  |  1. PLAN          |  |
            |  |  Route via GEPA   |  |
            |  |  Get model resp.  |  |
            |  +---------+---------+  |
            |            |            |
            |            v            |
            |  +-------------------+  |
            |  |  2. ACT           |  |
            |  |  Execute tool     |  |
            |  |  calls (if any)   |  |
            |  +---------+---------+  |
            |            |            |
            |            v            |
            |  +-------------------+  |
            |  |  3. OBSERVE       |  |
            |  |  Append results   |  |
            |  |  to conversation  |  |
            |  |  Check for done   |  |
            |  +---------+---------+  |
            |            |            |
            |   [not done? loop]      |
            +============+============+
                         |
                         v
                  +--------------+
                  |   Result     |
                  +--------------+
```

### Step-by-Step

1. **Initialization**: The agent's status is set to `running`. A system prompt is built from the agent's identity, available tools, and the task description. The conversation is initialized in the agent's KV state.

2. **Plan** (model inference): The conversation is sent to the GEPA router, which classifies the task complexity and routes to the appropriate vLLM model. The model returns text content and/or tool calls.

3. **Act** (tool execution): If the model requested tool calls, each tool is executed via the `ToolRegistry`. Tool calls are logged to the `tool_calls` table with status tracking (`pending` -> `running` -> `success`/`error`). Results are appended to the conversation as `tool` role messages.

4. **Observe** (state update): The conversation, iteration count, and heartbeat are persisted to the agent's state. If the model returned `end_turn` with no tool calls, the loop terminates.

5. **Auto-checkpoint**: Every `checkpoint_interval` iterations (default 10), a checkpoint is automatically created, enabling rollback to any interval boundary.

### Termination Conditions

- **Completion**: Model returns `end_turn` with no tool calls.
- **Timeout**: Elapsed wall-clock time exceeds `timeout_seconds`.
- **Max iterations**: Loop count exceeds `max_iterations`.
- **Kill signal**: Agent status changes to `killed` (checked each iteration).
- **Pause/resume**: Agent status `paused` causes the loop to sleep until resumed.

### Parallel Execution

`ClaudeCodeRunner.run_parallel()` spawns multiple agents concurrently using `asyncio.gather()` with a semaphore (`max_parallel_agents`, default 8) to bound concurrency. Each agent runs its own independent CCR loop.

### Tool Registry

The `ToolRegistry` (`kaos/ccr/tools.py`) manages built-in and custom tools:

**Built-in tools:**

| Tool | Description |
|---|---|
| `fs_read` | Read a file from the agent's VFS |
| `fs_write` | Write content to a file |
| `fs_ls` | List directory contents |
| `fs_delete` | Delete a file |
| `fs_mkdir` | Create a directory |
| `state_get` | Read a KV state value |
| `state_set` | Write a KV state value |
| `shell_exec` | Execute a shell command (with timeout) |

Tools with names prefixed by `fs_` or `state_` automatically have `agent_id` injected, ensuring they operate on the correct agent's namespace.

Custom tools can be registered via `ccr.register_tool(ToolDefinition(...))`.

---

## GEPA Router

The **Generalized Execution Planning & Allocation** (GEPA) router (`kaos/router/gepa.py`) routes inference requests to the optimal model based on task complexity.

### Architecture

```
  Incoming Request
  (messages, tools)
        |
        v
  +-------------------+
  |    Classify Task   |
  |                    |
  |  +--------------+  |
  |  | LLM-based    |  |  (preferred, uses classifier_model)
  |  | Classifier   |  |
  |  +------+-------+  |
  |         |          |
  |    [on failure]    |
  |         |          |
  |  +------v-------+  |
  |  | Heuristic    |  |  (fallback, regex + scoring)
  |  | Classifier   |  |
  |  +--------------+  |
  +--------+-----------+
           |
           v
  Classification Result
  (trivial | moderate | complex | critical)
           |
           v
  +-------------------+
  | Routing Table      |
  | trivial   -> 7B    |
  | moderate  -> 32B   |
  | complex   -> 70B   |
  | critical  -> 70B   |
  +--------+----------+
           |
           v
  +-------------------+
  | Context Compressor |
  | (if enabled)       |
  +--------+----------+
           |
           v
  +-------------------+
  |   VLLMClient      |
  |   (raw httpx)     |
  |   POST /v1/chat/  |
  |   completions     |
  +-------------------+
```

### Task Classification

**LLM Classifier** (`kaos/router/classifier.py: LLMClassifier`):
- Sends a classification prompt to a small, fast model (e.g., `qwen2.5-coder-7b`).
- The prompt asks the model to respond with a single word: `trivial`, `moderate`, `complex`, or `critical`.
- Parses the response, tolerating verbose or uppercase answers.
- Falls back to the heuristic classifier on any error (network failure, parse failure, etc.).
- Confidence: fixed at 0.85 for LLM classifications.

**Heuristic Classifier** (`kaos/router/classifier.py: HeuristicClassifier`):
- Pattern matching against the task description using three pattern sets:
  - `COMPLEX_PATTERNS`: refactor, architect, security, migration, distributed, etc. (+3.0 score each)
  - `MODERATE_PATTERNS`: implement, create function, write test, fix bug, etc. (+1.5 each)
  - `TRIVIAL_PATTERNS`: format, rename, comment, typo, import, etc. (-1.0 each)
- Context length and tool count adjustments:
  - Context > 50K chars: +2.0
  - Context > 20K chars: +1.0
  - 10+ tools: +1.0
  - Task description > 500 chars: +1.0
- Final score thresholds: >= 5.0 critical, >= 3.0 complex, >= 1.0 moderate, else trivial.
- Confidence: `min(0.9, 0.5 + |score| * 0.1)`.

### Routing Table

The routing table maps complexity levels to model names. It is built automatically from each model's `use_for` annotations in `kaos.yaml`:

```yaml
models:
  qwen2.5-coder-7b:
    use_for: [trivial, code_completion]
  qwen2.5-coder-32b:
    use_for: [moderate, code_generation]
  deepseek-r1-70b:
    use_for: [complex, critical, planning]
```

Any complexity level not covered by a model's `use_for` list falls back to `fallback_model`.

Agents can override routing by setting `force_model` in their config, bypassing the classifier entirely.

### Context Compression

The `ContextCompressor` (`kaos/router/context.py`) manages conversation history to fit within model context windows. It uses a multi-stage strategy:

1. **Estimate tokens**: Rough heuristic of 4 characters per token.
2. **Truncate long tool results**: Tool outputs exceeding 2000 characters are truncated to the first 1000 + last 500 characters with a `[truncated]` marker.
3. **Drop middle messages**: If still over limit, keep the system message, first user message, and the last 8 messages. A summary message replaces the dropped middle section.
4. **Aggressive trimming**: If still over limit, progressively remove messages from the middle until the target is met.

The compressor targets 85% of the model's `max_context` to leave room for the model's response.

### vLLM Client

The `VLLMClient` (`kaos/router/vllm_client.py`) is a lightweight async HTTP client that speaks the OpenAI-compatible chat completions API:

- **Transport**: `httpx.AsyncClient` with configurable timeout (default 120s).
- **Endpoint**: `POST {base_url}/chat/completions`
- **Payload**: Standard OpenAI chat completions format with `model`, `messages`, `temperature`, `max_tokens`, `tools`, and `tool_choice`.
- **Response parsing**: Raw JSON is parsed into typed dataclasses (`ChatCompletion`, `ChatChoice`, `ChatMessage`, `Usage`) -- no SDK dependency.
- **Connection management**: Lazy client initialization, explicit `close()` for cleanup.

### Retry and Fallback

The router retries failed model calls up to `max_retries` (default 3). On failure, if the failing model is not the fallback model, the router automatically switches to the fallback model for subsequent attempts. This provides graceful degradation when a specific vLLM instance is temporarily unavailable.

---

## MCP Server Integration

KAOS exposes its full functionality as an MCP (Model Context Protocol) server, enabling integration with Claude Code and other MCP-compatible clients.

The MCP server (`kaos/mcp/server.py`) is implemented using the `mcp` Python package and supports two transport modes:

- **stdio**: For direct process integration (used by Claude Code).
- **SSE**: For HTTP-based integration via Server-Sent Events (uses Starlette + uvicorn).

The server exposes 17 tools across 6 categories (Lifecycle, VFS, Checkpoints, Query, Orchestration, Meta-Harness) that map directly to `Kaos`, `ClaudeCodeRunner`, and `MetaHarnessSearch` operations. See [mcp-integration.md](mcp-integration.md) for the complete tool reference.

### Server Initialization

```python
from kaos.mcp.server import init_server

mcp_server = init_server(afs, ccr)
# afs: Kaos instance
# ccr: ClaudeCodeRunner instance
```

The server holds module-level references to `Kaos` and `ClaudeCodeRunner`, which are set during initialization and used by all tool handlers.

---

## Data Flow

### Complete Request Flow (MCP Client to Model)

```
Claude Code                KAOS MCP Server              KAOS Core
    |                           |                           |
    |-- agent_spawn(task) ----->|                           |
    |                           |-- afs.spawn() ----------->|
    |                           |<-- agent_id --------------|
    |                           |                           |
    |                           |-- ccr.run_agent() ------->|
    |                           |                           |
    |                           |   +-- CCR Loop ----------+|
    |                           |   |                       |
    |                           |   |  Build system prompt  |
    |                           |   |  Set state            |
    |                           |   |       |               |
    |                           |   |       v               |
    |                           |   |  GEPA Router          |
    |                           |   |   |                   |
    |                           |   |   | classify()        |
    |                           |   |   | select model      |
    |                           |   |   | compress context  |
    |                           |   |   |       |           |
    |                           |   |   |       v           |
    |                           |   |   |  VLLMClient       |
    |                           |   |   |  POST /v1/chat/   |
    |                           |   |   |  completions      |
    |                           |   |   |       |           |
    |                           |   |   |       v           |
    |                           |   |   |  vLLM Instance    |
    |                           |   |   |  (local GPU)      |
    |                           |   |   |       |           |
    |                           |   |   |<------+           |
    |                           |   |   |                   |
    |                           |   |  Parse response       |
    |                           |   |  Execute tool calls   |
    |                           |   |  Log to tool_calls    |
    |                           |   |  Log to events        |
    |                           |   |  Update state         |
    |                           |   |  Auto-checkpoint      |
    |                           |   |       |               |
    |                           |   |  [loop or done]       |
    |                           |   +-- End Loop -----------+
    |                           |                           |
    |                           |<-- result ----------------|
    |<-- {agent_id, result} ----|                           |
    |                           |                           |
```

### Data at Rest (SQLite Schema)

```
+------------------+      +------------------+
|     agents       |      |      blobs       |
|------------------|      |------------------|
| agent_id (PK)    |      | content_hash (PK)|
| name             |      | content (BLOB)   |
| parent_id (FK)   |      | compressed       |
| status           |      | ref_count        |
| config (JSON)    |      +--------+---------+
| metadata (JSON)  |               ^
| pid              |               | content_hash
| last_heartbeat   |               |
+--------+---------+      +--------+---------+
         |                |      files       |
         | agent_id       |------------------|
         |                | file_id (PK)     |
         +--------------->| agent_id (FK)    |
         |                | path             |
         |                | content_hash (FK)|---+
         |                | version          |   |
         |                | deleted          |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|   tool_calls     |   |
         |                |------------------|   |
         |                | call_id (PK)     |   |
         |                | agent_id (FK)    |   |
         |                | tool_name        |   |
         |                | input (JSON)     |   |
         |                | output (JSON)    |   |
         |                | status           |   |
         |                | duration_ms      |   |
         |                | token_count      |   |
         |                | parent_call_id   |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|     state        |   |
         |                |------------------|   |
         |                | agent_id (FK,PK) |   |
         |                | key (PK)         |   |
         |                | value (JSON)     |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|    events        |   |
         |                |------------------|   |
         |                | event_id (PK)    |   |
         |                | agent_id (FK)    |   |
         |                | event_type       |   |
         |                | payload (JSON)   |   |
         |                | timestamp        |   |
         |                +------------------+   |
         |                                       |
         |                +------------------+   |
         +--------------->|  checkpoints     |   |
                          |------------------|   |
                          | checkpoint_id(PK)|   |
                          | agent_id (FK)    |   |
                          | label            |   |
                          | event_id (FK)    |   |
                          | file_manifest    |---+
                          | state_snapshot   |
                          +------------------+
```

### Concurrency Model

```
Thread 1 (Agent A)         Thread 2 (Agent B)        Thread 3 (Agent C)
       |                          |                          |
       v                          v                          v
  thread-local conn          thread-local conn          thread-local conn
       |                          |                          |
       +----------- SQLite WAL mode (concurrent reads) -----+
       |                          |                          |
       v                          v                          v
  Write (serialized)        Read (concurrent)        Read (concurrent)
```

SQLite WAL mode allows concurrent reads while writes are serialized. Each thread maintains its own connection via `threading.local()`. The `busy_timeout` of 5000ms prevents immediate lock failures during write contention -- the thread retries for up to 5 seconds before raising an error.

The async CCR loop uses `asyncio` for cooperative concurrency within each agent, and the semaphore (`max_parallel_agents`) bounds the total number of concurrent agent loops to prevent resource exhaustion.
