# Changelog

All notable changes to KAOS are documented here.

## [0.5.0] - 2026-04-06

### Collaborative Meta-Harness — Claude Code IS the proposer

Three new MCP tools that let Claude Code drive the search loop directly. No subprocess, no API key, no extra cost — inference happens in your current session.

- **`mh_start_search`** — evaluates seeds, returns archive digest. YOU read it and write a better harness.
- **`mh_submit_candidate`** — submit your harness code for evaluation.
- **`mh_next_iteration`** — evaluates pending candidates, updates frontier, returns updated digest.

The loop: `mh_start_search` → read digest → write harness → `mh_submit_candidate` → `mh_next_iteration` → read updated digest → repeat.

Why this works: the CLI subprocess bottleneck (354s for 60K chars) is eliminated entirely. Claude Code already has an active API connection — no subprocess, no process startup, no stdin/stdout serialization. The digest goes into the conversation context and the response comes back as part of the normal tool flow.

## [0.4.2] - 2026-04-06

### New Provider: Claude Agent SDK

- **`provider: agent_sdk`** -- 5th provider type. Uses `claude_agent_sdk.query()` instead of `claude --print` subprocess. No rate limit competition with active Claude Code sessions. Seeds scored 90.6% accuracy vs 0% with `claude_code` provider in the same session.
- **Single-shot proposer** -- proposer makes one LLM call instead of 5-10 multi-turn tool calls. Completes in ~18s vs timing out at 120s+.
- **Empty response = error** -- `claude --print` returning empty stdout now retries 3x with backoff then raises with actionable message instead of silently producing garbage.
- Default timeout 600s → 300s across all providers (120s was too short for complex benchmarks).
- `max_prior_seeds=5` — caps knowledge compounding to top 5 discoveries instead of loading all.

### Provider Comparison

- `agent_sdk` -- shares session auth, no subprocess, works during active sessions
- `claude_code` -- `claude --print` subprocess, only works when session is idle
- `anthropic` -- direct API via httpx, needs ANTHROPIC_API_KEY, independent quota
- `openai` -- any OpenAI-compatible endpoint, needs API key
- `local` -- vLLM/ollama/llama.cpp, zero cost, needs GPU

## [0.4.1] - 2026-04-06

### Bug Fixes

- **#27 Proposer text extraction fallback** -- `claude --print` doesn't support tool-use, so the proposer couldn't call `mh_submit_harness`. Now extracts ```python blocks from plain text responses as a fallback. Works with any provider.

### Compaction Eval

- Expanded to 5 domains: classification (52% saved), code generation (31%), research/RAG (28%), tool calling (30%), ML training (28%)
- 100% quality retained at default level across all domains
- Aggregate: 34% savings at default, 88% quality at max

## [0.4.0] - 2026-04-06

### Knowledge Compounding (Karpathy LLM Wiki pattern)

- **#22 Cross-search memory** -- Persistent "kaos-knowledge" agent stores winning harnesses and frontiers. New searches automatically load prior discoveries as seeds instead of starting from scratch. Knowledge compounds across searches.
- **#23 VFS auto-index** -- `kaos index <agent-id>` builds `/index.md` with categorized file listing. `Kaos.build_index()` API.
- **#24 Lint operation** -- `kaos mh lint <search-agent-id>` health-checks for empty scores, failed harnesses, iteration errors, missing frontiers.
- **#26 Persistent skills** -- Winning harnesses auto-filed to knowledge agent. `kaos mh knowledge` shows discoveries by benchmark. Future searches use prior winners as seeds.

### Smart Context Compaction (#11 partial fix)

- **Compactor class** -- Tunable compaction (level 0-10) with three strategies: lossless (scores, source), structured extraction (traces → error patterns + samples), progressive summarization (conversation → sliding window).
- **Archive digest** -- Proposer gets a pre-built digest of all harnesses instead of doing 5-10 tool calls. Reduces proposer turns from ~10 to 1-2, fixing the main cause of `claude --print` timeouts.
- **Conversation compaction** -- CCR auto-compacts conversations >20 messages. Old tool results compressed to `[tool result: N chars]`. Recent messages kept verbatim.
- **compaction_level config** -- `SearchConfig.compaction_level` (0-10), configurable in `kaos.yaml`. Level 0 = raw data, 5 = balanced (default), 10 = maximum.
- **38 compaction tests** -- Monotonic compression verified across all levels. Retention score measured (scores + source always preserved). Digest quality validated at 7 levels.

### Full-Text Search (Hermes Agent pattern)

- **#25 VFS search** -- `kaos search "query"` searches across all file contents. `--agent` scopes to one agent. `Kaos.search()` API. Returns agent_id, path, line number, matching content.

### New CLI Commands

- `kaos search <query>` -- full-text search across all agent VFS contents
- `kaos index <agent-id>` -- build /index.md for an agent's VFS
- `kaos mh lint <search-id>` -- health-check a search archive
- `kaos mh knowledge` -- view persistent knowledge base / discoveries

### New Core API

- `Kaos.get_or_create_singleton(name)` -- get or create a persistent named agent
- `Kaos.build_index(agent_id)` -- build /index.md for an agent
- `Kaos.search(query, agent_id=None)` -- full-text search across file contents

## [0.3.1] - 2026-04-05

### Bug Fixes

- **#1 CLI Unicode crash on Windows** -- `sys.stdout.reconfigure(encoding="utf-8")` at CLI startup prevents `UnicodeEncodeError` with cp1252 console encoding.
- **#2 MCP parallel spawn WAL contention** -- `spawn()` retries up to 3 times on `OperationalError: database locked` with backoff. `PRAGMA wal_autocheckpoint=100` keeps WAL file small.
- **#7 MCP result truncation for large outputs** -- Results >4KB are written to agent VFS at `/result.txt`. MCP returns a preview + pointer to full result via `agent_read`.
- **#16 Background search write lock** -- `wal_autocheckpoint=100` ensures frequent WAL checkpointing, reducing lock hold time for concurrent access.

### New CLI Commands

- **`kaos read <agent_id> <path>`** (#4) -- Read files from an agent's virtual filesystem directly from the CLI. Supports `--json`.
- **`kaos logs <agent_id>`** (#6) -- View an agent's conversation history and event log. `--tail N` for last N events. Supports `--json`.

### Other

- **#3 Agent timeout** -- Already fixed in v0.3.0 (600s default, configurable via `kaos.yaml`). Closed.

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
kaos --version  # should show 0.3.1
```

If you have the MCP server running, restart it so it picks up the new code. Claude Code restarts the MCP server automatically when you start a new session. Any running background workers will continue on the old version until they finish.

If upgrading from v0.1.0/v0.2.0:
- Existing `kaos.yaml` configs and `kaos.db` databases work unchanged across versions.
- New `provider: claude_code` option available -- run `kaos setup` to reconfigure.
- CLI commands now output JSON when piped. Use `--json` flag explicitly in scripts.
- `kaos mh search --background` is the recommended way to run searches.
- New commands: `kaos read`, `kaos logs`, `kaos mh search --dry-run`.

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
