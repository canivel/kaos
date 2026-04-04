# Changelog

All notable changes to KAOS are documented here.

## [0.3.0] - 2026-04-04

### CLI-First Architecture

- **`--json` flag on all CLI commands** -- Global `--json` flag (auto-enabled when piped) adds structured JSON output to every command: `ls`, `status`, `query`, `kill`, `checkpoint`, `checkpoints`, `mh search`, `mh frontier`, `mh status`. Errors output as `{"error": "..."}`. Makes KAOS composable with any agent framework via shell -- no MCP required.

- **Worker subprocess for `mh search`** -- New `kaos/metaharness/worker.py` runs the Meta-Harness search as a detached background process. If the parent CLI or MCP server dies, the search continues. Launch with `kaos mh search --background` or via the MCP `mh_search` tool (which now always spawns a worker).

- **`provider: claude_code`** -- New provider type that shells out to `claude --print` using Claude Code's subscription auth. No API key needed. Handles Windows `.CMD` wrapper parsing, `CLAUDECODE` env var stripping, nvm path resolution, and thread-executor subprocess for MCP compatibility.

### Reliability Fixes

- **Fail-fast retries** -- `max_retries` default changed from 3 to 1. With `ClaudeCodeProvider`, each retry is a 600s subprocess -- retries are now handled at the search loop level, not the provider level.

- **Proposer timeout + error handling** -- `proposer.propose()` wrapped with `asyncio.wait_for(timeout=900s)` and try/except. Failed iterations are logged to `/iterations/{N}/error.json` and skipped instead of crashing the search.

- **SQLite DB locking fix** -- `busy_timeout` raised from 5s to 30s. `kill()` falls back to `_force_kill()` with a fresh connection on `OperationalError: database is locked`. Prevents stuck agents when multiple processes share `kaos.db`.

- **Evaluator bug fixes** -- `_truncate()` no longer creates invalid JSON on large results. Error/timeout score keys stripped of `+`/`-` prefixes to match success score keys.

- **Usage field mismatch fix** -- `GEPARouter._parse_response()` handles both `VLLMClient` (`prompt_tokens`/`completion_tokens`) and `LLMProvider` (`input_tokens`/`output_tokens`) field names.

### Configuration

- **`ModelConfig.timeout`** -- Per-model timeout (default 600s), configurable in `kaos.yaml` and wired through `GEPARouter` to `ClaudeCodeProvider`.
- **`SearchConfig.proposer_timeout_seconds`** -- Per-iteration proposer timeout (default 900s).
- **MCP `mh_frontier` enriched** -- Now returns agent status, current iteration, and harnesses evaluated count alongside the frontier data.

### Upgrade Guide

```bash
git pull origin main
uv sync
kaos --version  # should show 0.3.0
```

If upgrading from v0.1.0/v0.2.0:
- Existing `kaos.yaml` configs continue to work unchanged.
- New `provider: claude_code` option available -- run `kaos setup` to reconfigure.
- CLI commands now output JSON when piped. Use `--json` flag explicitly in scripts.
- `kaos mh search --background` is the recommended way to run searches.

## [0.2.0] - 2026-04-02

### Meta-Harness & Multi-Provider

- Paper-aligned Meta-Harness implementation (arXiv:2603.28052)
- Multi-provider support: `local`, `openai`, `anthropic` (all raw httpx)
- `kaos setup` interactive wizard with 6 presets
- 18 MCP tools (added `agent_pause`, `agent_resume`, `agent_checkpoints`, `mh_search`, `mh_frontier`, `mh_resume`)
- Resume interrupted Meta-Harness searches
- Dashboard Meta-Harness panel
- Paper benchmark loaders (LawBench, Symptom2Disease, USPTO-50k)

## [0.1.0] - 2026-03-30

### Initial Release

- KAOS VFS engine with SQLite WAL mode
- Agent lifecycle: spawn, kill, pause, resume, complete, fail
- Virtual filesystem with content-addressable blob store (SHA-256 + zstd)
- Append-only event journal (14 event types)
- Checkpoint / restore / diff
- KV state management per agent
- Tool call tracking with timing and token counts
- GEPA model router with heuristic classifier
- CCR agent execution loop
- CLI with 15 commands
- MCP server (stdio + SSE)
- TUI dashboard
- Logical + FUSE isolation tiers
