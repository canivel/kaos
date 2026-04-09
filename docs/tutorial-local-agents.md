# Tutorial: Run a Free, Local Multi-Agent System with Claude Code + vLLM

> **What you'll build:** A fully local multi-agent system where Claude Code orchestrates autonomous agents running on your own GPU — with isolated filesystems, checkpoints, audit trails, and zero API costs.

**Time:** ~30 minutes
**Cost:** $0 (everything runs locally)
**Requirements:** A machine with a GPU (16GB+ VRAM for 7B models, 48GB+ for 70B)

![KAOS Getting Started — spawn agents, write files, query VFS](../docs/demos/kaos_01_getting_started.gif)

---

## Table of Contents

1. [What Are We Building?](#1-what-are-we-building)
2. [Install KAOS](#2-install-kaos)
3. [Set Up vLLM (Your Local LLM Server)](#3-set-up-vllm-your-local-llm-server)
4. [Configure KAOS](#4-configure-kaos)
5. [Connect KAOS to Claude Code](#5-connect-kaos-to-claude-code)
6. [Your First Agent](#6-your-first-agent)
7. [Parallel Agents — The Real Power](#7-parallel-agents--the-real-power)
8. [Checkpoint, Restore, and Debug](#8-checkpoint-restore-and-debug)
9. [Post-Mortem: When Things Go Wrong](#9-post-mortem-when-things-go-wrong)
10. [The Dashboard](#10-the-dashboard)
11. [What You Got For Free](#11-what-you-got-for-free)
12. [Configuration Reference](#12-configuration-reference)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What Are We Building?

Here's the architecture:

```
┌──────────────────────────────┐
│        Claude Code           │  ← You talk to this
│  (your terminal / IDE)       │
└─────────┬────────────────────┘
          │ MCP protocol (stdio)
          ▼
┌──────────────────────────────┐
│       KAOS MCP Server        │  ← Orchestration layer
│  18 tools: spawn, read,      │
│  write, checkpoint, query,   │
│  pause, resume, mh_search... │
└─────────┬────────────────────┘
          │
          ▼
┌──────────────────────────────┐
│       KAOS Core + CCR        │  ← Isolated VFS + agent runner
│  SQLite DB, event journal,   │
│  blob store, checkpoints     │
└─────────┬────────────────────┘
          │ GEPA Router (raw httpx)
          ▼
┌──────────────────────────────┐
│         vLLM                 │  ← Your local GPU(s)
│  Qwen, DeepSeek, Llama,     │
│  or any model you want       │
└──────────────────────────────┘
```

**The flow:**
1. You ask Claude Code to do something involving agents (e.g., "review this code from 4 angles")
2. Claude Code calls KAOS tools via MCP (`agent_spawn`, `agent_parallel`, etc.)
3. KAOS spawns isolated agents, each with their own virtual filesystem
4. The GEPA router classifies task complexity and picks the right local model
5. Agents run on your local vLLM, writing results to their isolated VFS
6. Everything is logged, checkpointed, and queryable with SQL

**What makes this different from just calling an LLM API:**
- Each agent gets a sandboxed filesystem — no conflicts
- Every operation is recorded — full audit trail
- You can checkpoint and restore any agent independently
- You can run post-mortem SQL queries on what any agent did
- It all runs on your hardware — no API costs, no data leaving your machine

---

## 2. Install KAOS

```bash
git clone https://github.com/canivel/kaos.git
cd kaos
uv sync
```

Verify it works:

```bash
uv run kaos --version
# kaos, version 0.1.0
```

Initialize the database (or use `kaos setup` to run the interactive wizard that generates `kaos.yaml` and initializes the database in one step):

```bash
uv run kaos setup   # interactive wizard — picks a preset, generates kaos.yaml, inits DB
# OR manually:
uv run kaos init
# Initialized KAOS database: ./kaos.db
```

That's it. KAOS has no heavy dependencies — just `httpx`, `click`, `rich`, `textual`, `mcp`, `pyyaml`, `zstandard`, and `ulid-py`. 44 packages total.

---

## 3. Set Up vLLM (Your Local LLM Server)

vLLM serves LLMs with an OpenAI-compatible API. KAOS talks to it using raw `httpx` — no openai SDK, no litellm.

### Install vLLM

```bash
# In a separate terminal / virtualenv
pip install vllm
```

### Start a model

**Option A: Single model (simplest — start here)**

If you have 16GB+ VRAM:

```bash
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000
```

This gives you a single model for all tasks. Good enough to get started.

**Option B: Multiple models (recommended for real work)**

If you have 48GB+ VRAM (or multiple GPUs):

```bash
# Terminal 1 — Small model for simple tasks + routing classification
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000

# Terminal 2 — Medium model for moderate tasks
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct --port 8001

# Terminal 3 — Large model for complex tasks
vllm serve deepseek-ai/DeepSeek-R1-70B --port 8002
```

**Option C: Single GPU, one model at a time**

If you're GPU-constrained, just run one model. KAOS will route everything to it:

```bash
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000
```

You can swap to a bigger model when you need it — just restart vLLM.

### Verify vLLM is running

```bash
curl http://localhost:8000/v1/models
# Should return a JSON list of available models
```

### Alternative: Any OpenAI-compatible server

KAOS doesn't care what's behind the endpoint. Anything that serves `/v1/chat/completions` works:

- **vLLM** (recommended) — fastest for batched inference
- **llama.cpp** / **ollama** — lighter weight, works on consumer hardware
- **text-generation-webui** — if you already have it running
- **LocalAI** — drop-in OpenAI replacement

Just point the `vllm_endpoint` in `kaos.yaml` to whatever you're running.

---

## 4. Configure KAOS

> **Quick alternative:** Run `kaos setup` and pick the `local` or `local-multi` preset. It asks 3 questions and generates `kaos.yaml` for you — skip straight to [Step 5](#5-connect-kaos-to-claude-code).
>
> ```bash
> uv run kaos setup
> # Pick "local" for single-model or "local-multi" for multi-model
> ```

### Single-model setup (Option A above)

```bash
cp kaos.yaml.example kaos.yaml
```

Edit `kaos.yaml`:

```yaml
database:
  path: ./kaos.db
  wal_mode: true
  compression: zstd

models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, moderate, complex, critical]

router:
  fallback_model: qwen2.5-coder-7b
  context_compression: true

ccr:
  max_iterations: 50
  checkpoint_interval: 10
  max_parallel_agents: 4
```

### Multi-model setup (Option B above)

```yaml
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
  classifier_model: qwen2.5-coder-7b   # small model classifies task complexity
  fallback_model: deepseek-r1-70b       # big model as fallback
  context_compression: true

ccr:
  max_iterations: 100
  checkpoint_interval: 10
  max_parallel_agents: 8
```

**How GEPA routing works:**
1. When a task comes in, KAOS asks the `classifier_model` (the 7B): "Is this trivial, moderate, complex, or critical?"
2. Based on the answer, it routes to the right model
3. If the classifier fails, it falls back to a heuristic (pattern matching on keywords like "refactor", "security", "format")
4. If the selected model fails, it falls back to `fallback_model`

This means simple tasks like "rename this variable" go to the fast 7B, while "redesign the authentication architecture" goes to the 70B. You save GPU time and get faster responses on easy tasks.

### Or Use Cloud Models

KAOS also supports cloud providers via raw httpx (no AI SDKs). You can use Anthropic, OpenAI, or mix local + cloud in a hybrid configuration. API keys are read from environment variables.

**Anthropic-only:**

```yaml
models:
  claude-sonnet:
    provider: anthropic
    model_id: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
    max_context: 200000
    use_for: [trivial, moderate, complex, critical]

router:
  fallback_model: claude-sonnet
```

**OpenAI-only:**

```yaml
models:
  gpt-4o:
    provider: openai
    model_id: gpt-4o
    api_key_env: OPENAI_API_KEY
    max_context: 128000
    use_for: [trivial, moderate, complex, critical]

router:
  fallback_model: gpt-4o
```

**Hybrid (local + cloud):**

Route trivial tasks to your local GPU for free, and complex tasks to a cloud model for quality:

```yaml
models:
  claude-sonnet:
    provider: anthropic
    model_id: claude-sonnet-4-20250514
    api_key_env: ANTHROPIC_API_KEY
    max_context: 200000
    use_for: [complex, critical]
  gpt-4o:
    provider: openai
    model_id: gpt-4o
    api_key_env: OPENAI_API_KEY
    max_context: 128000
    use_for: [moderate]
  local-qwen:
    provider: local
    endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial]

router:
  classifier_model: local-qwen
  fallback_model: claude-sonnet
  context_compression: true
```

Set your API keys:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

Or run `kaos setup` and pick the `anthropic`, `openai`, or `hybrid` preset.

### Verify the config

```bash
# Quick test — run a single agent via CLI
uv run kaos run "Say hello and list the tools available to you" \
  --name test-agent \
  --config-file kaos.yaml
```

You should see the agent spawn, run on your local vLLM, and produce output. If this works, your vLLM + KAOS setup is correct.

---

## 5. Connect KAOS to Claude Code

This is where it gets powerful. We'll register KAOS as an MCP server so Claude Code can use all 18 KAOS tools natively.

### Add to Claude Code settings

Add to `~/.claude/settings.json` (create if it doesn't exist):

```json
{
  "mcpServers": {
    "kaos": {
      "command": "uv",
      "args": [
        "run",
        "--project", "/path/to/your/kaos",
        "kaos", "serve", "--transport", "stdio",
        "--config-file", "/path/to/your/kaos/kaos.yaml"
      ]
    }
  }
}
```

Replace `/path/to/your/kaos` with the actual path where you cloned KAOS.

**Or**, if you installed KAOS globally (`uv tool install .`):

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

### Verify the connection

Restart Claude Code, then ask:

> "What KAOS tools are available?"

Claude Code should list all 18 KAOS tools: `agent_spawn`, `agent_spawn_only`, `agent_read`, `agent_write`, `agent_ls`, `agent_status`, `agent_kill`, `agent_pause`, `agent_resume`, `agent_checkpoint`, `agent_restore`, `agent_diff`, `agent_checkpoints`, `agent_query`, `agent_parallel`, `mh_search`, `mh_frontier`, `mh_resume`.

If you see them, you're connected.

---

## 6. Your First Agent

Now try it. In Claude Code, say:

> "Use KAOS to spawn an agent called 'hello-world' that writes a Python hello world program to /src/main.py"

**What happens behind the scenes:**
1. Claude Code calls `agent_spawn` with name="hello-world" and the task
2. KAOS creates an agent with a fresh, isolated virtual filesystem
3. The GEPA router classifies this as "trivial" and sends it to the 7B
4. The agent runs a plan-act-observe loop:
   - **Plan:** Decide what to do
   - **Act:** Call `fs_write` to create `/src/main.py`
   - **Observe:** Check the result
   - **Done:** Return the final output
5. Everything is logged to the events table

### Read back what the agent wrote

> "Read the file /src/main.py from the hello-world agent"

Claude Code calls `agent_read` and shows you the content.

### See what happened

> "Show me the event timeline for the hello-world agent"

Claude Code calls `agent_query`:
```sql
SELECT timestamp, event_type, payload FROM events
WHERE agent_id = '...' ORDER BY event_id
```

You'll see every action: `agent_spawn`, `file_write`, `tool_call_start`, `tool_call_end`, `agent_complete`.

---

## 7. Parallel Agents — The Real Power

![Parallel Agents & GEPA Router — 3 agents running concurrently](../docs/demos/kaos_03_parallel_agents.gif)

This is where KAOS shines. Ask Claude Code:

> "Use KAOS to run 3 agents in parallel:
> 1. 'test-writer' — write unit tests for a REST payments endpoint
> 2. 'implementer' — implement the REST payments endpoint
> 3. 'doc-writer' — write API documentation for the payments endpoint"

**What happens:**
1. Claude Code calls `agent_parallel` with 3 tasks
2. KAOS spawns 3 agents, each with their own isolated VFS
3. GEPA routes each to the appropriate model based on complexity
4. All 3 run concurrently (controlled by the semaphore, default 8 max)
5. Auto-checkpoints are created every 10 iterations
6. Results come back when all agents are done

### See aggregate stats

> "How many tokens did each agent use?"

Claude Code runs:
```sql
SELECT a.name, SUM(tc.token_count) as tokens, COUNT(tc.call_id) as calls
FROM agents a LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
GROUP BY a.agent_id ORDER BY tokens DESC
```

### See what files each agent created

> "Show me the files each agent created"

Claude Code runs:
```sql
SELECT a.name, f.path FROM files f
JOIN agents a ON f.agent_id = a.agent_id
WHERE f.deleted = 0 ORDER BY a.name, f.path
```

The key insight: **each agent wrote to `/src/payments.py` or `/tests/test_payments.py` — but there's no conflict** because each has its own namespace. This is enforced at the SQL level, not by convention.

---

## 8. Checkpoint, Restore, and Debug

![Checkpoints & Rollback — checkpoint before risky operations, restore on failure](../docs/demos/kaos_02_checkpoints.gif)

### Scenario: Safe refactoring with rollback

Tell Claude Code:

> "Use KAOS to:
> 1. Spawn an agent called 'refactorer'
> 2. Write this code to its /src/auth.py: [paste your code]
> 3. Checkpoint it with label 'original'
> 4. Then have it refactor the code to add error handling"

After the agent runs:

> "The refactor doesn't look right. Restore the refactorer agent to the 'original' checkpoint."

Claude Code calls `agent_restore`. The agent's VFS rolls back to exactly the state it was in before the refactor. No other agents are affected.

### Diff two checkpoints

> "Show me what changed between the 'original' checkpoint and the current state"

Claude Code calls `agent_diff`, which returns:
- **Files added/removed/modified** (by content hash)
- **State changes** (KV pairs added/removed/modified, with before/after values)
- **Tool calls** made between the two checkpoints

This is time-travel debugging. You can see exactly what the agent did, step by step, and undo it if needed.

---

## 9. Post-Mortem: When Things Go Wrong

![Post-Mortem Debugging — SQL audit trail, log search, checkpoint diff](../docs/demos/kaos_uc03_post_mortem_debug.gif)

An agent failed or produced bad output. Here's how to investigate.

> "Show me all failed tool calls across all agents"

```sql
SELECT a.name, tc.tool_name, tc.error, tc.timestamp
FROM tool_calls tc JOIN agents a ON tc.agent_id = a.agent_id
WHERE tc.status = 'error'
ORDER BY tc.timestamp DESC
```

> "Show me the full event timeline for the failed agent"

```sql
SELECT timestamp, event_type, payload FROM events
WHERE agent_id = '...' ORDER BY event_id
```

> "Which agent used the most tokens?"

```sql
SELECT a.name, SUM(tc.token_count) as tokens
FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
GROUP BY a.agent_id ORDER BY tokens DESC LIMIT 5
```

> "What files did the rogue agent modify?"

```sql
SELECT path, version, modified_at FROM files
WHERE agent_id = '...' AND deleted = 0
ORDER BY modified_at
```

You can also use the CLI directly:

```bash
uv run kaos query "SELECT name, status FROM agents"
uv run kaos query "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
```

Or open `kaos.db` in any SQLite client (DBeaver, DataGrip, `sqlite3` CLI) and explore directly.

---

## 10. The Dashboard

KAOS includes a live TUI dashboard for monitoring agents in real time:

```bash
uv run kaos dashboard
```

This launches a Textual-based terminal app showing:
- Agent list with status (running, completed, failed, killed)
- Live updates
- Event stream

Useful when running parallel agents and you want to watch progress.

---

## 11. What You Got For Free

Let's recap what this setup gives you — all running locally, at zero cost:

| Capability | How |
|---|---|
| **Multi-agent orchestration** | Claude Code + KAOS MCP tools |
| **Agent isolation** | Per-agent VFS, SQL-enforced |
| **Intelligent routing** | GEPA classifies tasks → right model |
| **Parallel execution** | Up to 8 concurrent agents (configurable) |
| **Checkpoint/restore** | Snapshot + rollback any agent |
| **Full audit trail** | Append-only event journal, 14 event types |
| **SQL-queryable everything** | Token usage, errors, files, events |
| **Content deduplication** | SHA-256 blobs, zstd compressed |
| **Single-file runtime** | `cp kaos.db backup.db` = full backup |
| **Zero API costs** | Everything on your GPU |
| **Data stays local** | Nothing leaves your machine |

---

## 12. Configuration Reference

### kaos.yaml — full options

```yaml
database:
  path: ./kaos.db              # Database file path
  wal_mode: true               # WAL mode for concurrent reads (recommended)
  busy_timeout_ms: 5000        # SQLite busy timeout
  max_blob_size_mb: 100        # Max file size in blob store
  compression: zstd            # Blob compression: zstd | none
  gc_interval_minutes: 30      # Blob garbage collection interval

isolation:
  mode: logical                # logical (default) | fuse (Linux only)
  fuse_mount_base: /tmp/kaos   # FUSE mount point base (Linux only)
  cgroups:
    enabled: false             # cgroup resource limits (Linux only)
    memory_limit_mb: 4096
    cpu_shares: 1024

models:
  <model-name>:
    provider: local | openai | anthropic       # Provider type (default: local)
    vllm_endpoint: http://localhost:8000/v1    # For local provider (legacy format)
    endpoint: http://localhost:8000/v1         # For local provider (new format)
    model_id: gpt-4o                           # For openai/anthropic providers
    api_key_env: OPENAI_API_KEY                # Env var containing the API key
    max_context: 32768                         # Max context window (tokens)
    use_for: [trivial, moderate, ...]          # Complexity levels to route here

router:
  type: gepa                    # Router type (only gepa for now)
  classifier_model: <name>      # Model used to classify task complexity
  fallback_model: <name>        # Fallback when selected model fails
  context_compression: true     # Enable multi-stage context compression
  max_retries: 3                # Retry count before giving up

ccr:
  max_iterations: 100           # Max agent loop iterations
  checkpoint_interval: 10       # Auto-checkpoint every N iterations
  timeout_seconds: 3600         # Agent timeout (1 hour)
  max_parallel_agents: 8        # Max concurrent agents

mcp:
  port: 3100                    # SSE transport port
  host: 127.0.0.1              # SSE transport host

logging:
  level: INFO
  file: ./kaos.log
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `KAOS_DB` | `./kaos.db` | Database file path |
| `KAOS_CONFIG` | `./kaos.yaml` | Config file path |
| `ANTHROPIC_API_KEY` | — | API key for `provider: anthropic` models |
| `OPENAI_API_KEY` | — | API key for `provider: openai` models |

### Claude Code settings.json

```json
{
  "mcpServers": {
    "kaos": {
      "command": "uv",
      "args": [
        "run", "--project", "/path/to/kaos",
        "kaos", "serve", "--transport", "stdio",
        "--db", "/path/to/kaos/kaos.db",
        "--config-file", "/path/to/kaos/kaos.yaml"
      ]
    }
  }
}
```

---

## 13. Troubleshooting

### "Connection refused" when calling vLLM

```bash
# Check vLLM is running
curl http://localhost:8000/v1/models

# If not running, start it
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000
```

### Claude Code doesn't see KAOS tools

1. Check `~/.claude/settings.json` syntax is valid JSON
2. Make sure the path to KAOS is correct
3. Restart Claude Code after changing settings
4. Test manually: `uv run --project /path/to/kaos kaos serve --transport stdio`

### Agent stuck / not completing

```bash
# Check agent status
uv run kaos ls

# Kill a stuck agent
uv run kaos kill <agent-id>

# Check for errors
uv run kaos query "SELECT tool_name, error FROM tool_calls WHERE status = 'error'"
```

### Out of GPU memory

- Use a smaller model (7B instead of 70B)
- Reduce `max_parallel_agents` in kaos.yaml
- Use `--gpu-memory-utilization 0.8` flag with vLLM
- Use quantized models (e.g., GPTQ, AWQ variants)

### "Model not found" errors

The model name in `kaos.yaml` must match what vLLM reports:

```bash
curl http://localhost:8000/v1/models | python -m json.tool
```

Use the model name from that output in your config.

### Database locked

This usually means multiple processes are accessing the database without WAL mode. Make sure `wal_mode: true` is set in kaos.yaml. KAOS uses thread-local connections and WAL mode to handle concurrency.

### Context too long

If agents fail with context length errors:
- Enable `context_compression: true` in the router config (default)
- Reduce task prompt length
- Increase `max_context` for the model (match what vLLM was started with)

---

## Next Steps

- **Explore the examples:** `examples/code_review_swarm.py`, `examples/parallel_refactor.py`, `examples/self_healing_agent.py`
- **Try the post-mortem tool:** `python examples/post_mortem.py kaos.db <agent-id>`
- **Add custom tools:** Register your own tools via `ccr.register_tool()` — agents can call them during execution
- **Export and share:** `kaos export <agent-id> -o snapshot.db` to share an agent's complete state
- **Query the database directly:** `sqlite3 kaos.db` to explore tables, write custom queries, build dashboards
