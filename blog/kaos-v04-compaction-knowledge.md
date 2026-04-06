# KAOS v0.4: Zero-Loss Compaction, Knowledge That Compounds, and a CLI That Agents Actually Use

*Your agents were isolated, auditable, and checkpointed. Now they're also efficient, persistent, and composable. Here's what changed from v0.3 to v0.4 — and the real-world results.*

**GitHub:** [github.com/canivel/kaos](https://github.com/canivel/kaos) | **Website:** [canivel.github.io/kaos](https://canivel.github.io/kaos) | **License:** Apache 2.0 | Free and open source

---

## The Problem We Had

v0.2 gave KAOS its Meta-Harness — an AI that automatically optimizes the code wrapping your LLM. It worked. On our text_classify benchmark, the proposer took accuracy from 0% to 100% in two iterations, inventing a domain-keyword classifier from scratch.

But it was fragile. The proposer kept dying.

Here's why: each proposer iteration made 5-10 tool calls — list the archive, read 3 traces, read 2 source files, grep for patterns, submit a harness. Each tool call went through `claude --print`, which replays the *entire conversation* as input. By turn 6, the prompt was enormous. Timeout. Every time.

We tried raising the timeout from 300s to 600s. Then to 900s. The proposer still died on iteration 3+ because the conversation kept growing.

The fundamental issue wasn't the timeout — it was the architecture. We were feeding the proposer raw data and making it forage through the archive one tool call at a time. Every tool call made the next one slower.

---

## What We Built: Smart Context Compaction

Instead of letting the proposer explore the archive with tool calls, we pre-digest the entire archive and inject it into the prompt. One read instead of ten.

But "pre-digest" doesn't mean "truncate." Truncation is lossy in an uncontrolled way — you drop the tail and have no idea if the tail was the most important part. We built a **structured compactor** with three strategies:

| Data Type | Strategy | What Happens |
|---|---|---|
| Scores, metadata | **Lossless** | Kept exactly as-is. Small data, 100% signal. |
| Source code | **Lossless** (levels 0-7) | The proposer needs to read the code. |
| Per-problem results | **Structured extraction** | Raw traces → error patterns + failure samples. "3/8 wrong: science→technology (2x), timeout (1x)" is more useful than 8 verbose trace entries. |
| Traces | **Filtered** | Only error/failure entries kept. Correct-problem traces dropped — they add noise, not signal. |
| Conversation history | **Progressive summarization** | Old tool results → `[tool result: N chars]`. Recent turns kept verbatim. |

The key insight: structured extraction is *better* than raw data for the proposer. It surfaces the patterns explicitly instead of burying them in noise.

### The Results

We tested with 6 diagnostic questions — the specific facts a proposer needs to propose a good harness:

- Q1: Which harness scored best? (proposed_keyword_classifier, accuracy=1.0)
- Q2: What approach works? (keyword matching beats LLM-based)
- Q3: Why did the seeds fail? (empty prediction, scored 0%)
- Q4: Why did the LLM caller fail? (connection refused)
- Q5: What's the best cost? (8.0 context tokens)
- Q6: Is the winning source code available? (DOMAIN_KEYWORDS dict)

```
Level  0 │ 5292 chars ( 22% saved) │ quality=100% │ 6/6 answerable
Level  3 │ 3672 chars ( 46% saved) │ quality=100% │ 6/6 answerable
Level  5 │ 3672 chars ( 46% saved) │ quality=100% │ 6/6 answerable  ← default
Level  7 │ 3024 chars ( 56% saved) │ quality=100% │ 6/6 answerable
Level 10 │ 2512 chars ( 63% saved) │ quality=100% │ 6/6 answerable
```

**Zero quality loss at any compaction level.** The proposer can answer all 6 diagnostic questions whether you compress 22% or 63%. The savings come from dropping data that has no diagnostic value — correct-problem traces, verbose per-problem output, duplicate formatting.

### How to Use It

Default compaction level is 5 (46% savings). Configure in `kaos.yaml`:

```yaml
search:
  compaction_level: 5  # 0 (no compaction) to 10 (maximum)
```

Or per-search:

```python
config = SearchConfig(benchmark="text_classify", compaction_level=7)
```

Level 0 if you want the proposer to see everything. Level 10 if you're running on a model with a small context window.

---

## Knowledge That Compounds

This was the other big gap. Every `mh search` started from scratch — the proposer had zero memory of prior searches. It would discover "TF-IDF + keyword matching beats zero-shot by 100%" and then that finding would die when the search completed. The next search on the same benchmark would re-discover the same thing from scratch.

Inspired by [Karpathy's LLM Wiki pattern](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f): *"The tedious part of maintaining a knowledge base is not the reading or the thinking — it's the bookkeeping."*

### How It Works

When a search completes, KAOS files the results to a persistent "kaos-knowledge" agent:

```
/discoveries/text_classify/
    frontier.json           # Pareto-optimal harnesses
    latest_search.json      # Summary: best scores, iterations, duration
    harnesses/
        keyword_class.py    # The actual winning source code
        few_shot_v2.py      # Second-best approach
```

When a new search starts, KAOS loads prior discoveries as seeds instead of the default zero-shot/few-shot/retrieval seeds:

```
Search 1: Seeds → zero-shot (0%), few-shot (0%), retrieval (0%)
           Proposer invents keyword classifier → 100% accuracy

Search 2: Seeds → keyword_classifier (100%) ← loaded from knowledge
           Proposer starts from 100% and explores cost optimization
           Discovers: TF-IDF variant that's 30% faster

Search 3: Seeds → keyword_classifier (100%), tfidf_variant (100%, 30% faster)
           Proposer focuses on edge cases...
```

Each search builds on the last. The bookkeeping is automatic.

### CLI Commands

```bash
# View what's in the knowledge base
kaos mh knowledge

# Full-text search across all agent file contents
kaos search "TF-IDF retrieval"

# Build a navigable index for an agent's VFS
kaos index <agent-id>

# Health-check a search archive
kaos mh lint <search-agent-id>
```

---

## CLI-First Architecture (v0.3)

This was the biggest architectural shift. An [article on CLIs vs MCP for AI agents](https://medium.com/@unicodeveloper/10-must-have-clis-for-your-ai-agents-in-2026-51ba0d0881df) had a striking finding: CLI is 10-32x cheaper on tokens than MCP, with ~100% reliability vs MCP's 72%.

The reason: MCP injects the entire tool schema into every context window. CLI just runs a command and gets the output.

### `--json` on Everything

Every KAOS CLI command now supports structured JSON output:

```bash
# Structured JSON — any agent framework can parse this
kaos --json ls
kaos --json status <agent-id>
kaos --json mh status <search-id>
kaos --json search "keyword"

# Compose with jq
kaos --json ls | jq '.[] | select(.status == "running")'

# Pipe to other tools
kaos --json mh knowledge | jq '.benchmarks[].harnesses_stored'
```

Auto-enabled when stdout is piped (non-TTY). An agent calling `kaos --json ls` gets clean JSON; a human calling `kaos ls` gets a Rich table.

### Background Worker

The MCP server's `mh_search` used to run the search as an `asyncio.create_task` in the same event loop. If the MCP connection dropped, the search died. If the proposer blocked the event loop, all other MCP tools froze.

Now `mh_search` spawns a detached worker subprocess:

```bash
# CLI: runs as a background process
kaos mh search -b text_classify -n 10 --background
# → "Worker launched (PID 12345). Log: kaos-worker-1712345678.log"

# MCP: same thing — spawns a subprocess, returns immediately
# Poll with: kaos mh status <search-agent-id>
```

The worker:
- Survives parent exit, MCP disconnection, or terminal close
- Logs to `kaos-worker-*.log` (not /dev/null — that was a bug we fixed)
- Writes progress to the DB, pollable via `kaos mh status`
- On crash, the error is stored in the agent's state

### New Commands (v0.3.1)

```bash
kaos read <agent-id> <path>    # Read VFS files from CLI
kaos logs <agent-id>           # View conversation + event log
kaos mh search --dry-run       # Evaluate seeds only, report baseline
```

---

## The Self-Triage Story

We used KAOS to evaluate its own issues. Spawned a `self-triage-v030` agent, ingested all 14 GitHub issues into its VFS, scored each on impact/effort/feasibility, and implemented the top 6.

```python
afs = Kaos('kaos.db')
triage_id = afs.spawn('self-triage-v030')

for issue in github_issues:
    afs.write(triage_id, f'/issues/{issue["number"]}/issue.json', json.dumps(issue).encode())
    afs.set_state(triage_id, f'score.{issue["number"]}', {
        "impact": 9, "effort": 2, "feasibility": 10,
        "priority_score": 4.5,
    })

afs.checkpoint(triage_id, label='triage-complete')
```

Then queried with SQL:

```sql
SELECT key, json_extract(value, '$.priority_score') as score
FROM state WHERE key LIKE 'score.%'
ORDER BY score DESC
```

The top 6 by priority score got implemented in the same session. KAOS eating its own dogfood.

---

## Bug Fixes Worth Mentioning

**Windows Unicode crash (#1)** — `sys.stdout.reconfigure(encoding="utf-8")` at CLI startup. No more `UnicodeEncodeError` on non-ASCII output.

**MCP stdout corruption (#12)** — `sys.stdout = sys.stderr` in MCP stdio mode. Any library logging to stdout no longer corrupts the JSON-RPC protocol.

**Parallel spawn contention (#2)** — `spawn()` retries on WAL lock with backoff. `PRAGMA wal_autocheckpoint=100` keeps WAL small.

**Large output truncation (#7)** — Results >4KB stored in agent VFS at `/result.txt`. MCP returns a preview + pointer.

**Objectives override (#14)** — `SearchConfig.objectives` now defaults to `None` (inherit from benchmark) instead of hardcoding `["+accuracy", "-context_cost"]`.

**Evaluator bugs (#12, #13)** — `_truncate()` no longer creates invalid JSON. Error score keys stripped of `+`/`-` prefixes. Both caused all harnesses to score 0%.

---

## What's Next

The one remaining P0 issue: **Claude Code as a full execution backend** (#11). Right now, `agent_spawn` creates an isolated VFS but can't actually *run* an agent with real tools (Bash, web search, file read). The `ClaudeCodeProvider` does single-shot `claude --print` — useful for the proposer, but not for autonomous agents.

The vision: `agent_spawn` delegates to Claude Code as a subprocess. The spawned agent gets its own VFS, its own tool set, and its results flow back into KAOS. The entire research loop — propose, evaluate, score, checkpoint, iterate — runs inside KAOS autonomously.

That's v0.5.

---

## Upgrading

```bash
git pull origin main
uv sync
kaos --version  # 0.4.0
```

Existing configs and databases work unchanged. MCP server needs a restart (Claude Code does this automatically on new session).

---

## Full Changelog

### v0.4.0 (April 6, 2026)
- Cross-search memory via persistent knowledge agent
- Smart context compaction (0-10, 46-63% savings, 0% quality loss)
- Full-text search across VFS contents
- VFS auto-index, lint, persistent skills
- 157 tests (38 new compaction tests)

### v0.3.1 (April 5, 2026)
- Bug fixes: Unicode crash, WAL contention, output truncation, stdout corruption
- New: `kaos read`, `kaos logs`, `mh search --dry-run`

### v0.3.0 (April 4, 2026)
- CLI-first architecture with `--json` output
- Background worker subprocess for `mh search`
- `provider: claude_code` (no API key needed)
- Pluggable `llm()` callable for harnesses
- Fail-fast retries, proposer timeout handling

**GitHub:** [github.com/canivel/kaos](https://github.com/canivel/kaos) — 157 tests, Apache 2.0, zero AI SDK dependencies.
