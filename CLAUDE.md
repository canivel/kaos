# KAOS — Kernel for Agent Orchestration & Sandboxing

## Project Overview
KAOS is a local-first multi-agent orchestration framework. Every agent gets an isolated, auditable virtual filesystem backed by a single SQLite `.db` file.

## Package & CLI
- Package: `kaos` (import with `from kaos import Kaos`)
- CLI command: `kaos`
- Main class: `Kaos` (not AgentFS)
- Config file: `kaos.yaml`
- Database: `kaos.db`

## Running
```bash
uv sync                    # install deps
uv run kaos init           # create database
uv run kaos ls             # list agents
uv run kaos dashboard      # TUI monitor
uv run python -m pytest    # run tests
```

## Architecture
```
kaos/core.py          → Kaos VFS engine (main class)
kaos/schema.py        → SQLite schema
kaos/blobs.py         → Content-addressable blob store
kaos/events.py        → Append-only event journal
kaos/checkpoints.py   → Checkpoint/restore
kaos/isolation.py     → Isolation tiers (logical + FUSE)
kaos/ccr/runner.py    → Agent execution loop
kaos/ccr/tools.py     → Tool registry
kaos/router/gepa.py   → GEPA model router
kaos/router/classifier.py → LLM + heuristic classifier
kaos/router/vllm_client.py → Raw httpx vLLM client
kaos/mcp/server.py    → MCP server (11 tools)
kaos/cli/main.py      → CLI (15 commands)
```

## Rules
- NEVER use litellm — it is banned
- NEVER use the openai SDK — we use raw httpx for vLLM
- Always use `uv` for Python package management
- Tests: `uv run python -m pytest tests/ -v`
