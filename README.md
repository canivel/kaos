# KAOS

**Kernel for Agent Orchestration & Sandboxing**

> *Every agent gets an isolated, auditable, portable virtual filesystem — a single `.db` file that contains its files, state, tool calls, memory, and full execution history.*

Named after the enemy spy agency in *Get Smart* (1965). Ironic, because KAOS is how you **control** your agents.

[![Tests](https://img.shields.io/badge/tests-84%20passed-brightgreen)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue)]()
[![License](https://img.shields.io/badge/license-Apache%202.0-orange)]()
[![No litellm](https://img.shields.io/badge/litellm-none-red)]()

---

## Why KAOS?

Git worktrees give you directory-level separation for parallel agents, but offer **no true isolation**, **no audit trail**, **no snapshots**, and **no portability**. KAOS fixes all of that.

| Capability | Worktrees | KAOS |
|---|---|---|
| Agent isolation | Convention-based | Enforced (SQL-scoped + optional FUSE) |
| Audit trail | None | Full append-only event journal |
| Snapshot/restore | Manual tar + hope | `cp kaos.db snapshot.db` |
| Portability | Machine-bound | Single file, anywhere |
| Queryable history | `grep` | `SELECT * FROM ...` |
| Concurrent agents | Fragile | MVCC-isolated |

## Quick Start

```bash
# Install
git clone https://github.com/canivel/kaos.git
cd kaos
uv sync

# Use as a library
python -c "
from kaos import Kaos
afs = Kaos('demo.db')
agent = afs.spawn('hello-agent')
afs.write(agent, '/hello.txt', b'Hello from KAOS!')
print(afs.read(agent, '/hello.txt'))
print(afs.query('SELECT * FROM events'))
afs.close()
"

# Or use the CLI
kaos init
kaos run "refactor the auth module" --name auth-refactor --config-file kaos.yaml
kaos ls
kaos dashboard
```

## Three Ways to Use KAOS

### 1. Python Library (no infrastructure needed)

```python
from kaos import Kaos

afs = Kaos("project.db")

# Spawn isolated agents
agent_a = afs.spawn("researcher", config={"team": "backend"})
agent_b = afs.spawn("writer", config={"team": "docs"})

# Each agent has its own virtual filesystem
afs.write(agent_a, "/notes.md", b"# Research Notes\n- Found the bug")
afs.write(agent_b, "/draft.md", b"# API Documentation")

# They can't see each other's files
afs.read(agent_a, "/notes.md")   # works
# afs.read(agent_b, "/notes.md") # FileNotFoundError — isolated!

# KV state per agent
afs.set_state(agent_a, "progress", 75)
afs.set_state(agent_a, "findings", ["bug in line 42", "missing test"])

# Checkpoint before risky operations
cp = afs.checkpoint(agent_a, label="before-refactor")

# ... do risky stuff ...
# Roll back if it went wrong
afs.restore(agent_a, cp)

# Query anything with SQL
afs.query("""
    SELECT agent_id, name, status FROM agents
""")

# Diff two checkpoints
diff = afs.diff_checkpoints(agent_a, cp1, cp2)
# → {files: {added, removed, modified}, state: {added, removed, modified}, tool_calls: [...]}
```

### 2. With Local vLLM (full autonomous agents)

Point KAOS at your local vLLM instances — including your own finetuned models:

```bash
# Start your models (any OpenAI-compatible endpoint works)
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct --port 8001
vllm serve deepseek-ai/DeepSeek-R1-70B --port 8002

# Configure
cp kaos.yaml.example kaos.yaml
# Edit endpoints to match your setup

# Run agents
kaos init
kaos run "write unit tests for payments" --name test-writer
kaos parallel \
    -t tests "write unit tests" \
    -t impl "refactor to Stripe v3" \
    -t docs "update API docs"

# Monitor & debug
kaos dashboard
kaos query "SELECT * FROM tool_calls WHERE status = 'error'"
kaos diff <agent-id> --from <cp1> --to <cp2>
```

```python
import asyncio
from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter

afs = Kaos("project.db")
router = GEPARouter.from_config("kaos.yaml")
ccr = ClaudeCodeRunner(afs, router)

# Router auto-classifies complexity:
#   trivial → 7B    moderate → 32B    complex/critical → 70B
results = asyncio.run(ccr.run_parallel([
    {"name": "tests", "prompt": "Write tests for payments"},
    {"name": "impl",  "prompt": "Refactor payments to Stripe v3"},
    {"name": "docs",  "prompt": "Update payment API docs"},
]))
```

### 3. As an MCP Server (Claude Code integration)

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

Now Claude Code can call `agent_spawn`, `agent_read`, `agent_query`, `agent_checkpoint` natively.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    ORCHESTRATION LAYER                   │
│                                                         │
│   Claude Code ←──→ KAOS MCP Server                      │
│        │                                                │
│        ▼                                                │
│   ┌─────────┐    ┌──────────────┐    ┌───────────────┐  │
│   │   CCR   │───▶│    GEPA      │───▶│    vLLM       │  │
│   │ (Runner)│    │   Router     │    │  Local LLM    │  │
│   └─────────┘    └──────────────┘    └───────────────┘  │
└──────────┬──────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────┐
│                      KAOS CORE                          │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌────────────┐            │
│  │  FUSE    │  │  Python  │  │   MCP      │            │
│  │  Mount   │  │  SDK     │  │   Server   │            │
│  └────┬─────┘  └────┬─────┘  └─────┬──────┘            │
│       │              │              │                   │
│       ▼              ▼              ▼                   │
│  ┌──────────────────────────────────────────────┐       │
│  │              KAOS VFS Engine                  │       │
│  │                                              │       │
│  │  ┌────────────┐ ┌──────────┐ ┌────────────┐  │       │
│  │  │ Namespace  │ │ TX       │ │ Event      │  │       │
│  │  │ Isolation  │ │ Manager  │ │ Journal    │  │       │
│  │  └────────────┘ └──────────┘ └────────────┘  │       │
│  └──────────────────────┬───────────────────────┘       │
│                         │                               │
│                         ▼                               │
│  ┌──────────────────────────────────────────────┐       │
│  │              SQLite (.db file)                │       │
│  │                                              │       │
│  │  files │ blobs │ tool_calls │ state │ events  │       │
│  └──────────────────────────────────────────────┘       │
└─────────────────────────────────────────────────────────┘
```

## Core Concepts

### Single-File Runtime
Everything lives in one `.db` file. `cp kaos.db backup.db` is a full snapshot. Send it to a colleague. Open it on another machine. Query it with any SQLite client.

### Content-Addressable Blob Store
Identical files across agents share the same blob (SHA-256 deduped, zstd compressed). Storage stays lean even with hundreds of agents.

### Append-Only Event Journal
Every file read, write, delete, tool call, state change, and lifecycle event is logged. You can reconstruct exactly what any agent did, when, and why.

### Checkpoint / Restore
Snapshot an agent's complete state (files + KV store) at any point. Restore to any checkpoint. Diff two checkpoints to see exactly what changed.

### Isolation Tiers
- **Tier 1 — Logical** (default): SQL-scoped. Every query is `WHERE agent_id = ?`. Zero overhead.
- **Tier 2 — FUSE + Namespace** (opt-in, Linux): Mount each agent's VFS via FUSE. Process isolation via Linux namespaces. cgroups for resource limits.

### GEPA Router
**G**eneralized **E**xecution **P**lanning & **A**llocation. Classifies task complexity (LLM-based or heuristic) and routes to the right model tier:
- Trivial tasks → small model (fast, cheap)
- Complex tasks → large model (powerful)
- Supports any OpenAI-compatible endpoint — including your finetuned models

## CLI Reference

```bash
kaos init                              # Initialize database
kaos run TASK -n NAME [-m MODEL]       # Run a single agent
kaos parallel -t NAME PROMPT ...       # Run agents in parallel
kaos ls [-s STATUS]                    # List agents
kaos status AGENT_ID                   # Agent details
kaos kill AGENT_ID                     # Kill an agent
kaos query "SELECT ..."               # SQL query
kaos checkpoint AGENT_ID [-l LABEL]    # Create checkpoint
kaos checkpoints AGENT_ID             # List checkpoints
kaos restore AGENT_ID --checkpoint ID  # Restore checkpoint
kaos diff AGENT_ID --from CP --to CP  # Diff checkpoints
kaos export AGENT_ID -o FILE          # Export agent to file
kaos import FILE                       # Import agent from file
kaos serve [--transport stdio|sse]     # Start MCP server
kaos dashboard                         # TUI monitoring dashboard
```

## Example Queries

```sql
-- What did a rogue agent do?
SELECT timestamp, event_type, payload FROM events
WHERE agent_id = 'refactor-gone-wrong' ORDER BY timestamp;

-- Which agents consumed the most tokens?
SELECT agent_id, SUM(token_count) as tokens, COUNT(*) as calls
FROM tool_calls WHERE status = 'success'
GROUP BY agent_id ORDER BY tokens DESC;

-- What files did an agent modify?
SELECT path, version, modified_at FROM files
WHERE agent_id = 'feature-builder' ORDER BY modified_at;

-- Trace a tool call chain
WITH RECURSIVE chain AS (
    SELECT call_id, tool_name, parent_call_id, 0 as depth
    FROM tool_calls WHERE call_id = 'target-id'
    UNION ALL
    SELECT tc.call_id, tc.tool_name, tc.parent_call_id, c.depth + 1
    FROM tool_calls tc JOIN chain c ON tc.parent_call_id = c.call_id
)
SELECT * FROM chain ORDER BY depth;
```

## Project Structure

```
kaos/
├── kaos/
│   ├── __init__.py              # Package entry point
│   ├── core.py                  # Kaos VFS engine
│   ├── schema.py                # SQLite schema + migrations
│   ├── blobs.py                 # Content-addressable blob store
│   ├── events.py                # Append-only event journal
│   ├── checkpoints.py           # Checkpoint/restore system
│   ├── isolation.py             # FUSE + namespace isolation
│   ├── ccr/                     # Claude Code Runner
│   │   ├── runner.py            # Agent execution loop
│   │   ├── tools.py             # Tool registry + execution
│   │   └── prompts.py           # System prompts
│   ├── router/                  # GEPA Router
│   │   ├── gepa.py              # Intelligent model routing
│   │   ├── classifier.py        # LLM + heuristic classifiers
│   │   ├── context.py           # Context compression
│   │   └── vllm_client.py       # Raw httpx vLLM client
│   ├── mcp/                     # MCP Server
│   │   └── server.py            # MCP tool definitions
│   └── cli/                     # CLI
│       ├── main.py              # Click commands
│       ├── dashboard.py         # Textual TUI dashboard
│       └── diff.py              # Checkpoint diff rendering
├── tests/                       # 84 tests
├── examples/                    # Usage examples
├── docs/                        # Detailed documentation
├── kaos.yaml.example            # Configuration template
└── pyproject.toml
```

## Zero Bloat Dependencies

KAOS has **no AI SDK dependencies**. No `openai`. No `litellm`. No `dspy`. Just:

| Package | Why |
|---|---|
| `httpx` | Raw HTTP to vLLM endpoints |
| `click` | CLI framework |
| `rich` + `textual` | Terminal UI |
| `mcp` | MCP server protocol |
| `pyyaml` | Config parsing |
| `zstandard` | Blob compression |
| `ulid-py` | Time-sortable IDs |

**44 total packages** in the dependency tree.

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

## License

Apache 2.0

## Author

**Danilo Canivel**

---

*Built with spite toward convention-based isolation and love for SQLite.*
