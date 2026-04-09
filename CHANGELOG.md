# Changelog

All notable changes to KAOS are documented here.

## [0.6.0] - 2026-04-09

### CORAL: Autonomous Multi-Agent Evolution (inspired by arXiv:2604.01658)

Three tiers of CORAL-inspired improvements to the Meta-Harness.

**Tier 1 — Stagnation Detection + Pivot Prompts**
- `SearchConfig.stagnation_threshold` (default 3): after N consecutive non-improving iterations, inject a `PIVOT REQUIRED` section into the proposer digest requiring a structurally different approach
- `SearchConfig.consolidation_interval` (default 5): skills heartbeat fires every K iterations
- `stagnant_iterations` and `delta` returned in `mh_next_iteration` response so Claude Code can observe the stagnation signal
- Both automated (`search.py`) and collaborative (`mh_next_iteration`) paths track stagnation

**Tier 2 — Three-Tier Memory (attempts / notes / skills)**
- Search archive gains `/attempts/`, `/notes/`, `/skills/` directories (CORAL filesystem model)
- Every evaluated harness writes a compact summary to `/attempts/{id}.json` — fast scanning without reading full source
- `mh_submit_candidate` accepts optional `notes` param — observations written to `/notes/iter_N.md`
- New MCP tool `mh_write_skill(search_agent_id, name, description, code_template)` — write reusable patterns discovered during search; persisted to knowledge agent across searches
- Skills loaded into every proposer prompt and `mh_next_iteration` digest (max 10, MRU)
- Consolidation heartbeat in digest asks proposer to extract skills every `consolidation_interval` iterations
- Skills survive across searches: `_file_to_knowledge` now archives `/skills/` alongside harnesses

**Tier 3 — Concurrent Multi-Agent Co-Evolution**
- New MCP tool `mh_spawn_coevolution(benchmark, n_agents, ...)` — spawns N independent search agents + 1 hub agent
- New MCP tool `mh_hub_sync(search_agent_id)` — push current best harnesses+skills to hub, pull other agents' discoveries into local archive
- Auto-sync: `mh_next_iteration` calls `_do_hub_sync` automatically every `hub_sync_interval` iterations (default 2)
- Hub structure: `/best_per_agent/agent_N/`, `/shared_skills/`, `/shared_attempts/`
- Cross-agent harnesses appear in next digest and Pareto frontier

## [0.5.3] - 2026-04-07

### ARC-AGI-3 Benchmark + Search Hang Fix

- **ARC-AGI-3 benchmark** (`kaos/metaharness/benchmarks/arc_agi3.py`) — new interactive game benchmark. Scoring via RHAE (Relative Human Action Efficiency). Harnesses define `run(problem)` + `choose_action(grid, available_actions, state)`. 4 seed strategies: random, systematic, productive-first, click-objects.
- **Fix: search hanging** — root cause: `asyncio.wait_for` cannot cancel `run_in_executor` threads. With old defaults (10 games × 120s × 4 seeds = 80 min) the process appeared frozen. Fixed: `time_per_game=25s`, `max_actions=800`, `n_search_games=6`. Seed eval now takes ~1.5 min (eval_subset=1) or ~3 min (eval_subset=2).
- **MCP stdio guard** — `arc_agi.Arcade()` adds a `logging.StreamHandler(sys.stdout)` on init, which corrupts the MCP transport. Monkeypatches `StreamHandler.__init__` to redirect any stdout handler to stderr before import.
- **`SearchConfig.harness_timeout_seconds` 300 → 60** — per-problem cap; arc-agi-3 games run at most 25s, all other benchmarks complete in seconds.

## [0.5.2] - 2026-04-07

### AAAK Compact Notation + Tiered Loading (inspired by MemPalace)

- **AAAK-style compact notation** -- replaces verbose markdown with dense shorthand: `H:keyword|i2|acc=1.0|cost=8.0|8/8✓`. All LLMs read it without decoders. 57% savings at default level (was 34%).
- **Tiered loading** -- L0 (verbose), L1 (AAAK+source), L2 (AAAK+top-3 source), L3 (ultra-compact scores only). Maps to compaction levels 0-10.
- **100% quality at default** across all 5 domains (classification, code gen, research, tool calling, ML) with 49-72% savings per domain.
- **L3 ultra** achieves 95% savings for severely context-limited scenarios.

### Comparison: Old vs AAAK

```
Before (structured extraction):  34% saved, 100% quality at default
After  (AAAK + tiered loading):  57% saved, 100% quality at default  ← +68% more savings
```

## [0.5.1] - 2026-04-07

### Surrogate Verifier (EvoSkills paper, arXiv:2604.01687)

- **#31 Surrogate Verifier** -- After evaluating a harness, a separate verifier analyzes the results and produces structured failure diagnostics: per-problem root-cause analysis, failure pattern grouping, and actionable revision suggestions.
- Informationally isolated: verifier reads outputs, NOT harness source code (prevents confirmation bias).
- Integrated into evaluator: every `EvaluationResult` now carries a `diagnosis` with failure patterns, root causes, and suggestions.
- Integrated into compactor: digest includes verifier suggestions and root causes alongside scores/traces.
- Integrated into `mh_next_iteration`: response includes verifier diagnosis text so the proposer (Claude Code) sees structured "why it failed" + "how to fix it" alongside the archive digest.
- MCP stdio fix: `sys.stdout = sys.stderr` was eating MCP protocol responses. Now preserves original stdout for the MCP transport.

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
