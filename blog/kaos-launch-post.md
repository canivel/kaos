# Resilient AI Agents That Run Locally, Roll Back on Failure, and Cost You Nothing

<!-- HERO IMAGE — Generate with this prompt:

Dark, minimal tech illustration. Wide 16:9 ratio, suitable for blog hero/cover.

Center: a glowing SQLite database cylinder radiating soft light.
Around it: 5-6 AI agents represented as simple geometric orbs, each
enclosed in its own translucent protective bubble (representing isolation).
Thin glowing lines connect each bubble to the central database.

One agent's bubble shows a green checkpoint icon (a small flag or save symbol).
Another bubble shows a rewind/rollback arrow — the agent is restoring to
a previous state. A third bubble shows a small timeline of events flowing
into the database (audit trail).

Below the database, a subtle GPU chip outline glows — representing local
execution.

Color palette: deep navy background (#0a0a0f), purple accents (#6c5ce7),
cyan highlights (#18ffff), green for checkpoints (#00e676).

Style: abstract, clean, developer-focused. No robots, no faces, no text
overlay. Think: infrastructure diagram meets sci-fi UI.

-->

![Hero image](hero.png)

*Every agent gets its own isolated filesystem, auto-checkpoints, and a full audit trail — all inside one SQLite file, running on your own GPU. No API keys, no cloud, no bills.*

---

## Every Multi-Agent Framework Has the Same Blind Spot

We've gotten really good at orchestrating AI agents. Route tasks, chain prompts, manage conversations — LangChain, CrewAI, AutoGen, you name it.

But underneath all of that, your agents share a filesystem. And nobody talks about what that actually means.

**It means your refactoring agent and your test-writing agent both write to `auth.py` — and one silently overwrites the other.** You find out when CI breaks.

**It means when an agent goes rogue** — 47 tool calls, 12 files modified, codebase broken — you have no audit trail. You `grep` through logs. Maybe you have logs.

**It means you can't roll back one agent.** The refactorer broke everything? `git reset --hard`. The test-writer's work, the doc-writer's work, the security reviewer's findings — all gone.

**It means state vanishes on crash.** Agent dies mid-task. Progress, findings, intermediate files — start over.

This isn't a model problem. The models are great. **This is an infrastructure problem.** And no agent framework solves it because they all treat the runtime as someone else's job.

So I built the runtime.

---

## KAOS: A Kernel for Your Agents

**KAOS** (Kernel for Agent Orchestration & Sandboxing) is the runtime layer that agent frameworks are missing. Every agent gets an isolated virtual filesystem inside a single SQLite `.db` file — with checkpoint/restore, a full audit trail, and SQL-queryable history of everything.

```python
from kaos import Kaos

db = Kaos("project.db")

# Each agent is isolated — they cannot see each other's files
agent_a = db.spawn("refactorer")
agent_b = db.spawn("test-writer")

db.write(agent_a, "/src/auth.py", b"# refactored auth")
db.write(agent_b, "/src/auth.py", b"# test stubs")
# Both wrote to "/src/auth.py" — no conflict.

# Checkpoint before risky work
cp = db.checkpoint(agent_a, label="before-migration")
# ... agent does something dangerous ...
db.restore(agent_a, cp)  # roll back JUST this agent

# What exactly did it do?
db.query("SELECT event_type, payload FROM events WHERE agent_id = ?", [agent_a])
```

**Everything lives in one `.db` file.** Copy it to back up. Send it to a teammate. Query with any SQLite client. That's the entire runtime — files, state, tool calls, events, checkpoints.

---

## What LangChain, CrewAI, and AutoGen Don't Give You

Those frameworks are great at **prompt chaining and agent communication**. KAOS isn't competing with them — it's solving the problem underneath that none of them address:

**Agent isolation?** They share a filesystem. KAOS enforces per-agent VFS — every query is scoped by `WHERE agent_id = ?`.

**Audit trail?** DIY logging, if you remember. KAOS records every operation in an append-only event journal — 14 event types, queryable with SQL.

**Roll back one agent?** Not possible. In KAOS: `db.restore(agent, checkpoint)`. Other agents are untouched.

**Debug a failed agent?** Read logs, hope for the best. In KAOS: `SELECT * FROM events WHERE agent_id = ?`

**Portable runtime?** Cloud-dependent or in-memory. KAOS is a single `.db` file — copy it, send it, query it anywhere.

**State persistence?** Framework-specific, often lost on crash. KAOS uses SQLite — crash-safe by design.

**Token tracking?** Manual. KAOS: `SELECT SUM(token_count) FROM tool_calls`

**KAOS isn't a replacement** — it's the runtime layer they're missing. Use it underneath LangChain, or standalone with local LLMs.

---

## The Architecture

<!-- PROMPT FOR IMAGE: Generate a dark-themed architecture diagram showing 4 layers stacked vertically:
Top layer "INTERFACES" with 3 boxes: "CLI" (terminal icon), "MCP Server" (plug icon), "Python API" (code icon)
Second layer "ORCHESTRATION" with 3 boxes: "Claude Code Runner" → "GEPA Router" → "Local LLMs (vLLM)"
Third layer "KAOS CORE / VFS ENGINE" with 6 boxes in 2 rows: "Blob Store", "Event Journal", "Checkpoint Manager" / "Namespace Isolation", "State KV Store", "Tool Registry"
Bottom layer "STORAGE — SINGLE FILE" with one wide box: "SQLite (.db)" containing "agents | files | blobs | tool_calls | state | events | checkpoints"
Use dark background (#0a0a0f), colored borders (purple for interfaces, cyan for orchestration, green for core, orange for storage), monospace font. -->

![KAOS Architecture](image.png)

The key insight: **everything flows into one SQLite database**. Every file write, every tool call, every state change, every lifecycle event — all queryable with SQL, all portable in a single file.

---

## What You Get That No Other Framework Provides

### 1. Enforced Agent Isolation

Not "please don't touch other agents' files." Enforced. Every database query includes `WHERE agent_id = ?`. It's physically impossible for one agent to access another's filesystem through the API.

Optional second tier on Linux: FUSE mounts + namespace isolation + cgroup resource limits. Each agent sees a real filesystem, has no idea it's backed by SQLite.

### 2. Checkpoint / Restore / Diff

Snapshot an agent's files + state at any point. Roll back to any checkpoint. Diff two checkpoints to see exactly what changed.

```python
cp1 = db.checkpoint(agent, label="before-migration")
# ... agent works ...
cp2 = db.checkpoint(agent, label="after-migration")

diff = db.diff_checkpoints(agent, cp1, cp2)
# → files added/removed/modified, state changes, tool calls between them
```

This is time-travel debugging for AI agents. When something goes wrong, you can step back through the history and find exactly when and why.

### 3. Append-Only Audit Trail

14 event types cover every operation:
- **Lifecycle:** spawn, pause, resume, kill, complete, fail
- **File ops:** read, write, delete
- **Execution:** tool_call_start, tool_call_end
- **State:** state_change
- **Checkpoints:** checkpoint_create, checkpoint_restore

```sql
-- What did this agent do in the last hour?
SELECT timestamp, event_type, payload FROM events
WHERE agent_id = 'auth-refactor'
ORDER BY timestamp;
```

### 4. Intelligent Model Routing (GEPA)

The GEPA (**G**eneralized **E**xecution **P**lanning & **A**llocation) router classifies task complexity and routes to the optimal model:

- **Trivial** (rename, format, docstring) → 7B model (fast)
- **Moderate** (implement function, write tests) → 32B model
- **Complex** (refactor, system design) → 70B model (powerful)

Classification can be LLM-based (ask the small model) or heuristic (pattern matching). Falls back gracefully on failure.

### 5. Content-Addressable Blob Store

Files stored as SHA-256 blobs with zstd compression. Identical files across agents share a single blob. Reference counting with automatic garbage collection. Storage stays lean even with hundreds of agents.

### 6. Single-File Portability

The entire runtime — all agents, all files, all events, all checkpoints — is one `.db` file.

- `cp kaos.db backup.db` = full backup
- Send it to a teammate over Slack
- Open it with DBeaver, DataGrip, or `sqlite3`
- No cloud, no Docker, no server

---

## Set It Up in 5 Steps (Free, Local, No API Keys)

Here's the full setup — Claude Code orchestrating agents on your own GPU, with everything running locally at zero cost. Your code never leaves your machine.

### Step 1: Install KAOS

```bash
git clone https://github.com/canivel/kaos.git
cd kaos
uv sync
```

44 packages total. No `openai` SDK. No `litellm`. No `langchain`. Just `httpx` for raw HTTP to your local models.

### Step 2: Start vLLM

```bash
# Single model (16GB+ VRAM)
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000

# Or multi-model (48GB+ VRAM / multi-GPU)
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000    # trivial
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct --port 8001   # moderate
vllm serve deepseek-ai/DeepSeek-R1-70B --port 8002        # complex
```

KAOS works with **any OpenAI-compatible endpoint** — vLLM, llama.cpp, ollama, LocalAI.

### Step 3: Configure

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

### Step 4: Connect to Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "kaos": {
      "command": "uv",
      "args": [
        "run", "--project", "/path/to/kaos",
        "kaos", "serve", "--transport", "stdio"
      ]
    }
  }
}
```

Restart Claude Code. Now it has 11 new tools: `agent_spawn`, `agent_read`, `agent_write`, `agent_checkpoint`, `agent_restore`, `agent_diff`, `agent_query`, `agent_kill`, `agent_parallel`, and more.

### Step 5: Use It

In Claude Code, say:

> "Use KAOS to run 4 agents in parallel to review this code from security, performance, style, and test coverage angles"

KAOS spawns 4 isolated agents, routes each to the right model, runs them on your local GPU, and collects results — all with full audit trails, auto-checkpoints, and SQL-queryable history.

> "How many tokens did each agent use?"

```sql
SELECT a.name, SUM(tc.token_count) as tokens
FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
GROUP BY a.agent_id ORDER BY tokens DESC
```

> "The security reviewer found issues. Checkpoint the refactorer before it tries to fix them."

> "The fix broke things. Roll back the refactorer to the checkpoint."

---

## The Dashboard

Run `kaos dashboard` for a live TUI that shows agent status, aggregate stats, and event streams in real time.

![KAOS Dashboard — real-time agent monitoring with status, token counts, and event log](image-1.png)

The top bar shows aggregate stats at a glance — running/completed/failed counts, total tool calls and tokens, storage usage. The table shows every agent with its status (color-coded), file count, tool calls, and token consumption. The bottom panel streams events in real time — tool calls, state changes, checkpoints, errors.

```bash
kaos dashboard --db kaos.db
```

---

## Post-Mortem: When an Agent Fails

An agent broke something. Here's how to investigate — no log files needed:

```sql
-- What files did it touch?
SELECT path, version, modified_at FROM files
WHERE agent_id = 'legacy-parser' ORDER BY modified_at;

-- Which tool calls failed?
SELECT tool_name, error, duration_ms FROM tool_calls
WHERE agent_id = 'legacy-parser' AND status = 'error';

-- Full event timeline
SELECT timestamp, event_type, payload FROM events
WHERE agent_id = 'legacy-parser' ORDER BY event_id;

-- How many tokens did it burn?
SELECT SUM(token_count) FROM tool_calls
WHERE agent_id = 'legacy-parser';
```

<!-- PROMPT FOR IMAGE: Terminal screenshot showing the output of SQL queries against KAOS database:
- A "kaos query" command showing a rich-formatted table with columns: path, version, modified_at — showing files like /src/main.py, /review.md, /tests/test_payments.py
- A second query showing failed tool calls table with columns: tool_name, error, duration_ms
- Dark terminal background, colored table borders (Rich library style) -->

Or use the post-mortem script: `python examples/post_mortem.py kaos.db <agent-id>`

---

## What You Get For Free

- **Multi-agent orchestration** — Claude Code + KAOS MCP (11 tools)
- **Agent isolation** — Per-agent VFS, enforced at the SQL level
- **Intelligent routing** — GEPA classifies task complexity → picks the right model
- **Parallel execution** — Up to 8 concurrent agents with semaphore control
- **Checkpoint / restore** — Snapshot and rollback any agent independently
- **Full audit trail** — 14 event types, append-only, SQL-queryable
- **SQL-queryable everything** — Token usage, errors, files touched, event timeline
- **Content deduplication** — SHA-256 blobs with zstd compression
- **Single-file runtime** — `cp kaos.db backup.db` is a full backup
- **Zero API costs** — Everything runs on your GPU
- **Data stays local** — Nothing leaves your machine

---

## Try It

```bash
git clone https://github.com/canivel/kaos.git
cd kaos
uv sync
kaos init
```

- **GitHub:** [github.com/canivel/kaos](https://github.com/canivel/kaos)
- **Website:** [canivel.github.io/kaos](https://canivel.github.io/kaos)
- **Full Tutorial:** [Run a Free Local Multi-Agent System](https://github.com/canivel/kaos/blob/main/docs/tutorial-local-agents.md)
- **License:** Apache 2.0

---

*KAOS is named after the enemy spy agency in Get Smart (1965). Because KAOS is how you control your agents.*

*Built by [Danilo Canivel](https://github.com/canivel).*

---

## Image Prompts for Illustrations

Use these prompts with an image generation tool (Midjourney, DALL-E, Figma, or a diagramming tool like Excalidraw/Mermaid) to create the visuals for the blog post:

### 1. Hero / Cover Image

> Dark-themed tech illustration. A central glowing SQLite database icon (cylinder shape) with 6 autonomous AI agents orbiting around it, each enclosed in their own translucent colored bubble (isolation). Thin lines connect each agent to the database. The agents are abstract geometric shapes — not robots. Background is dark navy (#0a0a0f) with subtle purple (#6c5ce7) gradient accents. Style: minimal, modern, developer-focused. No text overlay.

### 2. Architecture Diagram

> *(Already created — use `image.png` from the repo)*

### 3. The Problem — Before KAOS

> Split panel illustration, dark theme. LEFT SIDE (labeled "Without KAOS"): 4 agents (colored shapes) all reaching into the same file folder, tangled lines between them, red warning icons, a broken file icon. Messy, chaotic. RIGHT SIDE (labeled "With KAOS"): 4 agents each inside their own clean box/bubble with their own mini-filesystem, connected to a single glowing SQLite cylinder at the bottom. Clean, organized. Style: technical diagram, minimal, dark background.

### 4. Checkpoint/Restore Flow

> Horizontal timeline diagram on dark background. 5 labeled points on the timeline: "Spawn" → "Checkpoint A" (green flag) → "Agent works..." → "Something breaks" (red X) → "Restore to A" (green arrow curving back). Below the timeline, show file icons appearing and disappearing. Below that, a small code snippet: `db.restore(agent, checkpoint_a)`. Style: clean, minimal, developer-focused.

### 5. GEPA Routing Diagram

> Flow diagram on dark background. Left: incoming task bubble labeled "Classify task". Middle: a diamond/router shape labeled "GEPA" with 3 outgoing arrows. Right: 3 model boxes of different sizes: small box "7B — trivial" (green), medium box "32B — moderate" (blue), large box "70B — complex" (purple). Each has a GPU icon next to it. Arrow labels: "rename var" → 7B, "implement feature" → 32B, "redesign architecture" → 70B. Style: technical, minimal, dark.

### 6. Dashboard Screenshot

> *(Take actual screenshot of `kaos dashboard --db demo.db` running in terminal)*

### 7. SQL Query Results Screenshot

> *(Take actual screenshot of `kaos query "SELECT ..." --db demo.db` output in terminal)*

### 8. Code Review Swarm

> Top-down diagram on dark background. Center: a code file icon. 4 agents around it in colored boxes: "Security" (red border), "Performance" (orange border), "Style" (blue border), "Test Coverage" (green border). Each agent has a dotted line to the code file (reading) and a dotted line to their own results file (writing). Below all 4: a single SQLite cylinder collecting everything. Label at bottom: "4 agents, 4 isolated VFS, 1 queryable database". Style: clean, technical, dark.
