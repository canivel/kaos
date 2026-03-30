# KAOS Deployment Guide

> Prerequisites, installation, vLLM setup, configuration, and production deployment.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Installation from Source](#installation-from-source)
3. [vLLM Setup](#vllm-setup)
4. [Configuration Walkthrough](#configuration-walkthrough)
5. [Running as a Service (systemd)](#running-as-a-service-systemd)
6. [Docker Deployment](#docker-deployment)
7. [Performance Tuning](#performance-tuning)
8. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required

| Requirement | Minimum | Recommended |
|---|---|---|
| Python | 3.11 | 3.12+ |
| uv | 0.4+ | latest |
| SQLite | 3.35+ (WAL2 support) | system default |
| OS | Linux, macOS, Windows | Linux (for Tier 2 isolation) |

### Optional (for LLM agent execution)

| Requirement | Purpose |
|---|---|
| NVIDIA GPU(s) | Running local vLLM inference |
| CUDA 12.1+ | vLLM GPU backend |
| vLLM 0.4+ | Local model serving |
| fusepy | Tier 2 FUSE isolation (Linux only) |
| uvicorn + starlette | SSE transport for MCP server |

### Install uv

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Verify
uv --version
```

---

## Installation from Source

### Clone and install

```bash
git clone https://github.com/canivel/kaos.git
cd kaos
uv sync
```

This creates a `.venv` virtual environment and installs all dependencies.

### Install with development tools

```bash
uv sync --extra dev
```

This adds pytest, pytest-asyncio, pytest-cov, and ruff.

### Install with FUSE support (Linux only)

```bash
uv sync --extra fuse
```

This adds the `fusepy` package for Tier 2 FUSE-based isolation.

### Verify installation

```bash
# CLI works
uv run kaos --version

# Run tests
uv run pytest

# Quick smoke test
uv run python -c "
from kaos import Kaos
afs = Kaos(':memory:')
agent = afs.spawn('smoke-test')
afs.write(agent, '/hello.txt', b'Hello from KAOS!')
print(afs.read(agent, '/hello.txt'))
afs.close()
print('OK')
"
```

### Install as a global tool

To make the `kaos` command available system-wide:

```bash
uv tool install -e .
```

After this, `kaos` is available in your PATH without `uv run`.

---

## vLLM Setup

KAOS uses local vLLM instances for LLM inference. Each model tier runs as a separate vLLM server process.

### Model tier recommendations

| Tier | Example Model | Context | vLLM Port | Use Case |
|---|---|---|---|---|
| Small (7B) | Qwen/Qwen2.5-Coder-7B-Instruct | 32K | 8000 | Trivial tasks, classification, routing |
| Medium (32B) | Qwen/Qwen2.5-Coder-32B-Instruct | 128K | 8001 | Moderate coding, test writing |
| Large (70B) | deepseek-ai/DeepSeek-R1-70B | 128K | 8002 | Complex reasoning, architecture, planning |

### Starting vLLM instances

**Small model (7B) -- classification and trivial tasks:**

```bash
vllm serve Qwen/Qwen2.5-Coder-7B-Instruct \
  --port 8000 \
  --max-model-len 32768 \
  --gpu-memory-utilization 0.85 \
  --tensor-parallel-size 1
```

**Medium model (32B) -- moderate tasks:**

```bash
vllm serve Qwen/Qwen2.5-Coder-32B-Instruct \
  --port 8001 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 2
```

**Large model (70B) -- complex and critical tasks:**

```bash
vllm serve deepseek-ai/DeepSeek-R1-70B \
  --port 8002 \
  --max-model-len 131072 \
  --gpu-memory-utilization 0.90 \
  --tensor-parallel-size 4
```

### GPU memory guidelines

| Model Size | Minimum VRAM | Recommended | Tensor Parallel |
|---|---|---|---|
| 7B | 16 GB (1x GPU) | 24 GB | 1 |
| 32B | 48 GB (2x GPU) | 80 GB | 2 |
| 70B | 160 GB (4x GPU) | 320 GB | 4-8 |

### Verify vLLM is running

```bash
# Check each endpoint
curl http://localhost:8000/v1/models
curl http://localhost:8001/v1/models
curl http://localhost:8002/v1/models
```

Each should return a JSON response listing the served model.

### Using a single model

If you only have one GPU or one model, configure all tiers to point to the same endpoint:

```yaml
models:
  my-model:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, moderate, complex, critical]
```

### Using remote endpoints

Any OpenAI-compatible endpoint works, including remote servers:

```yaml
models:
  remote-model:
    vllm_endpoint: https://my-gpu-server.example.com/v1
    max_context: 131072
    use_for: [complex, critical]
```

---

## Configuration Walkthrough

KAOS is configured via `kaos.yaml`. Start by copying the example:

```bash
cp kaos.yaml.example kaos.yaml
```

### Full configuration reference

```yaml
# ── Database Settings ────────────────────────────────────────
database:
  path: ./kaos.db              # Path to the SQLite database file
  wal_mode: true                # Enable WAL mode (recommended for concurrency)
  busy_timeout_ms: 5000         # How long to wait on lock contention (ms)
  max_blob_size_mb: 100         # Maximum size for a single blob
  compression: zstd             # Blob compression: "zstd" or "none"
  gc_interval_minutes: 30       # How often to garbage-collect orphaned blobs

# ── Isolation Settings ───────────────────────────────────────
isolation:
  mode: logical                 # "logical" (default), "fuse", or "namespace"
  fuse_mount_base: /tmp/agentfs # Base directory for FUSE mounts (Linux only)
  cgroups:
    enabled: false              # Enable cgroups v2 resource limits
    memory_limit_mb: 4096       # Per-agent memory limit
    cpu_shares: 1024            # CPU scheduling weight

# ── Model Endpoints ──────────────────────────────────────────
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768          # Maximum context window (tokens)
    use_for:                    # Task complexity levels this model handles
      - trivial
      - code_completion

  qwen2.5-coder-32b:
    vllm_endpoint: http://localhost:8001/v1
    max_context: 131072
    use_for:
      - moderate
      - code_generation

  deepseek-r1-70b:
    vllm_endpoint: http://localhost:8002/v1
    max_context: 131072
    use_for:
      - complex
      - critical
      - planning

# ── GEPA Router Settings ────────────────────────────────────
router:
  type: gepa                    # Router implementation (currently only "gepa")
  classifier_model: qwen2.5-coder-7b   # Model used for LLM-based classification
  fallback_model: deepseek-r1-70b      # Fallback when a model is unavailable
  context_compression: true     # Enable context window compression
  max_retries: 3                # Retry count for failed model calls

# ── CCR (Execution Loop) Settings ────────────────────────────
ccr:
  max_iterations: 100           # Maximum plan-act-observe cycles per agent
  checkpoint_interval: 10       # Auto-checkpoint every N iterations
  timeout_seconds: 3600         # Agent execution timeout (1 hour)
  max_parallel_agents: 8        # Concurrency limit for parallel agent runs

# ── MCP Server Settings ─────────────────────────────────────
mcp:
  port: 3100                    # Port for SSE transport
  host: 127.0.0.1              # Bind address

# ── Logging ──────────────────────────────────────────────────
logging:
  level: INFO                   # Log level: DEBUG, INFO, WARNING, ERROR
  file: ./kaos.log             # Log file path
```

### Key configuration decisions

**Compression** (`database.compression`):
- `zstd` (default): Compresses blobs at level 3. Good compression ratio with minimal CPU overhead. Recommended for most use cases.
- `none`: Store blobs uncompressed. Use if your workload is write-heavy and CPU-constrained.

**Isolation mode** (`isolation.mode`):
- `logical` (default): SQL-scoped isolation. Zero overhead. Works on all platforms.
- `fuse`: FUSE-mounted VFS per agent. Requires Linux + fusepy. Use when agents need to run arbitrary processes that expect a real filesystem.
- `namespace`: Full Linux namespace isolation with optional cgroups. Requires Linux + root. Use for untrusted agent workloads.

**Classifier model** (`router.classifier_model`):
- Set this to your smallest/fastest model. Classification uses a short prompt with `max_tokens=10`, so even a 7B model is fast and accurate.
- If omitted, the heuristic classifier is used instead (no LLM call, pure regex scoring).

**Context compression** (`router.context_compression`):
- When enabled, long conversations are compressed before sending to the model by truncating tool outputs and dropping old messages. This prevents context overflow errors.
- Targets 85% of the model's `max_context` to leave room for the response.

---

## Running as a Service (systemd)

### MCP server service

Create `/etc/systemd/system/kaos-mcp.service`:

```ini
[Unit]
Description=KAOS MCP Server
After=network.target

[Service]
Type=simple
User=kaos
Group=kaos
WorkingDirectory=/opt/kaos
ExecStart=/opt/kaos/.venv/bin/kaos serve --transport sse --host 127.0.0.1 --port 3100 --db /var/lib/kaos/kaos.db --config-file /etc/kaos/kaos.yaml
Restart=on-failure
RestartSec=5
Environment=KAOS_DB=/var/lib/kaos/kaos.db
Environment=KAOS_CONFIG=/etc/kaos/kaos.yaml

# Security hardening
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/var/lib/kaos
ProtectHome=true

[Install]
WantedBy=multi-user.target
```

### vLLM model services

Create a service for each model tier. Example for the 7B model (`/etc/systemd/system/vllm-7b.service`):

```ini
[Unit]
Description=vLLM 7B Model Server
After=network.target

[Service]
Type=simple
User=vllm
Group=vllm
ExecStart=/opt/vllm/.venv/bin/vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000 --max-model-len 32768 --gpu-memory-utilization 0.85
Restart=on-failure
RestartSec=10
Environment=CUDA_VISIBLE_DEVICES=0

[Install]
WantedBy=multi-user.target
```

Repeat for 32B (port 8001, `CUDA_VISIBLE_DEVICES=1,2`) and 70B (port 8002, `CUDA_VISIBLE_DEVICES=3,4,5,6`).

### Enable and start

```bash
# Create user and directories
sudo useradd -r -s /bin/false kaos
sudo mkdir -p /var/lib/kaos /etc/kaos
sudo chown kaos:kaos /var/lib/kaos

# Copy config
sudo cp kaos.yaml /etc/kaos/kaos.yaml

# Enable services
sudo systemctl daemon-reload
sudo systemctl enable --now vllm-7b vllm-32b vllm-70b
sudo systemctl enable --now kaos-mcp

# Check status
sudo systemctl status kaos-mcp
sudo journalctl -u kaos-mcp -f
```

---

## Docker Deployment

### Dockerfile

```dockerfile
FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy project files
COPY pyproject.toml uv.lock ./
COPY kaos/ kaos/

# Install dependencies
RUN uv sync --frozen --no-dev

# Create data directory
RUN mkdir -p /data

# Default command: MCP server in SSE mode
CMD ["uv", "run", "kaos", "serve", "--transport", "sse", "--host", "0.0.0.0", "--port", "3100", "--db", "/data/kaos.db", "--config-file", "/app/kaos.yaml"]

EXPOSE 3100

VOLUME ["/data"]
```

### docker-compose.yml

```yaml
services:
  kaos:
    build: .
    ports:
      - "3100:3100"
    volumes:
      - kaos-data:/data
      - ./kaos.yaml:/app/kaos.yaml:ro
    depends_on:
      - vllm-7b
    restart: unless-stopped

  vllm-7b:
    image: vllm/vllm-openai:latest
    command: >
      --model Qwen/Qwen2.5-Coder-7B-Instruct
      --port 8000
      --max-model-len 32768
      --gpu-memory-utilization 0.85
    ports:
      - "8000:8000"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

volumes:
  kaos-data:
```

### Build and run

```bash
docker compose up -d

# Check logs
docker compose logs -f kaos

# Run CLI commands inside the container
docker compose exec kaos uv run kaos ls --db /data/kaos.db
```

### Configuration for Docker networking

Update `kaos.yaml` model endpoints to use Docker service names:

```yaml
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://vllm-7b:8000/v1
    max_context: 32768
    use_for: [trivial, moderate, complex, critical]
```

---

## Performance Tuning

### SQLite tuning

The default SQLite PRAGMAs are set in `Kaos.__init__()`:

```python
conn.execute("PRAGMA journal_mode=WAL")     # Concurrent reads
conn.execute("PRAGMA foreign_keys=ON")       # Referential integrity
conn.execute("PRAGMA busy_timeout=5000")     # 5s lock retry
```

For high-concurrency workloads, consider adding to the connection setup (via a custom `Kaos` subclass or configuration):

```sql
PRAGMA synchronous=NORMAL;       -- Faster writes (slight durability risk)
PRAGMA cache_size=-64000;        -- 64MB page cache (default is 2MB)
PRAGMA mmap_size=268435456;      -- 256MB memory-mapped I/O
PRAGMA temp_store=MEMORY;        -- In-memory temp tables
```

### Database file placement

- Use a **local SSD** for the `.db` file. Network filesystems (NFS, SMB) do not support SQLite WAL mode correctly.
- Avoid placing the database on a tmpfs/ramfs unless you accept data loss on reboot.
- If using Docker, mount a named volume or bind-mount to a local SSD path.

### Blob compression trade-offs

| Setting | Write Speed | Read Speed | Storage | When to Use |
|---|---|---|---|---|
| `zstd` | Slightly slower | Slightly slower | 40-70% smaller | Default, most workloads |
| `none` | Fastest | Fastest | Largest | CPU-constrained, small files |

### Concurrency settings

- `ccr.max_parallel_agents`: Controls the asyncio semaphore. Set this based on available GPU memory and vLLM throughput. Each concurrent agent maintains its own conversation in memory.
- `database.busy_timeout_ms`: Increase if you see `database is locked` errors under heavy write contention. Values of 10000-30000 are safe.
- vLLM `--max-num-seqs`: Controls how many requests vLLM processes concurrently. Align with `max_parallel_agents`.

### Garbage collection

Orphaned blobs accumulate when files are overwritten or deleted. Run garbage collection periodically:

```python
from kaos import Kaos

afs = Kaos("kaos.db")
removed = afs.blobs.gc()
print(f"Removed {removed} orphaned blobs")
afs.close()
```

Or via SQL:

```bash
kaos query "SELECT COUNT(*) as orphaned FROM blobs WHERE ref_count <= 0"
```

The `gc_interval_minutes` configuration controls automatic GC scheduling (planned for future implementation).

---

## Troubleshooting

### "database is locked"

**Cause:** Multiple writers competing for the write lock, and the busy timeout was exceeded.

**Solutions:**
1. Increase `busy_timeout_ms` in `kaos.yaml` (e.g., 15000 or 30000).
2. Verify WAL mode is active: `kaos query "PRAGMA journal_mode"` should return `wal`.
3. Ensure the `.db` file is on a local filesystem, not NFS/SMB.
4. Reduce `max_parallel_agents` to lower write contention.

### "Agent not found: <id>"

**Cause:** The agent ID does not exist in the database.

**Solutions:**
1. List available agents: `kaos ls`
2. Check for typos -- agent IDs are ULIDs (26 characters).
3. The agent may have been exported or the database file may have changed.

### vLLM connection refused

**Cause:** The vLLM server is not running or not listening on the expected port.

**Solutions:**
1. Verify vLLM is running: `curl http://localhost:8000/v1/models`
2. Check the port matches `kaos.yaml` configuration.
3. If using Docker, ensure service names resolve correctly (use `http://vllm-7b:8000/v1` not `localhost`).
4. Check vLLM logs for GPU memory errors or model loading failures.

### FUSE mount fails

**Cause:** FUSE isolation requires Linux and the fusepy package.

**Solutions:**
1. Verify you are on Linux: `uname -s`
2. Install fusepy: `uv sync --extra fuse`
3. Ensure FUSE kernel module is loaded: `lsmod | grep fuse`
4. Check mount permissions -- may require `user_allow_other` in `/etc/fuse.conf`.
5. On non-Linux platforms, use `isolation.mode: logical`.

### "Only SELECT queries are allowed via query()"

**Cause:** The `query()` method and `agent_query` MCP tool only allow read-only SQL.

**Solution:** This is by design. Use the Python API directly for write operations. The query interface is for debugging, monitoring, and auditing.

### Out of context window errors

**Cause:** The conversation history exceeds the model's context window.

**Solutions:**
1. Enable context compression: `router.context_compression: true`
2. Reduce `ccr.max_iterations` to prevent very long conversations.
3. Increase `ccr.checkpoint_interval` to reduce auto-checkpoint overhead in the conversation.
4. Use a model with a larger context window for complex tasks.

### High memory usage

**Cause:** Many concurrent agents or large blob store.

**Solutions:**
1. Reduce `ccr.max_parallel_agents`.
2. Run blob garbage collection: `afs.blobs.gc()`
3. Export completed agents to separate databases: `kaos export <agent_id> -o archive.db`
4. Increase SQLite page cache with `PRAGMA cache_size` for read performance, but this increases memory.

### Checking database health

```bash
# Schema version
kaos query "SELECT * FROM schema_version"

# Database size breakdown
kaos query "
SELECT 'agents' as tbl, COUNT(*) as rows FROM agents
UNION ALL SELECT 'files', COUNT(*) FROM files
UNION ALL SELECT 'blobs', COUNT(*) FROM blobs
UNION ALL SELECT 'tool_calls', COUNT(*) FROM tool_calls
UNION ALL SELECT 'state', COUNT(*) FROM state
UNION ALL SELECT 'events', COUNT(*) FROM events
UNION ALL SELECT 'checkpoints', COUNT(*) FROM checkpoints
"

# WAL mode check
kaos query "PRAGMA journal_mode"

# Integrity check
kaos query "PRAGMA integrity_check"
```
