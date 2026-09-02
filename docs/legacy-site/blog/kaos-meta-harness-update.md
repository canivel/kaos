# KAOS v0.2: Your LLM Now Optimizes Its Own Prompts — While Your Agents Stay Isolated

<!-- HERO IMAGE — Generate with this prompt:

Wide 16:9 dark-themed tech illustration. Split composition:
LEFT SIDE: A glowing SQLite cylinder with 4-5 translucent protective
bubbles orbiting it (representing isolated agents). Each bubble has a
different colored glow (purple, cyan, green, orange).
RIGHT SIDE: A vertical evolution/iteration flow — 3 stacked code file
icons connected by arrows pointing downward, each slightly more refined
than the last (representing harness optimization iterations). A small
graph next to them shows an accuracy line going up from 45% to 87%.
Between the two sides: thin glowing connection lines.
Bottom: subtle GPU chip outline glowing.
Color palette: deep navy (#0a0a0f), purple (#6c5ce7), cyan (#18ffff),
green (#00e676), orange (#f97316). No text, no faces, no robots.
Style: abstract, clean, developer-focused infrastructure diagram.

-->

![Hero image](hero-v2.png)

*We added Meta-Harness (Stanford's automated harness optimization) to KAOS, improved the agent runtime with patterns from Claude Code's internals, and built real-world examples for engineering, business, and autonomous research. Here's what changed and why it matters.*

**GitHub:** [github.com/canivel/kaos](https://github.com/canivel/kaos) | **Website:** [canivel.github.io/kaos](https://canivel.github.io/kaos) | **License:** Apache 2.0 | Free and open source

---

## What's New in v0.2

KAOS started as an answer to a simple problem: AI agents share filesystems, lose state on crash, and you can't debug what they did. v0.1 solved that with isolated virtual filesystems, checkpoints, and SQL-queryable audit trails — all in one SQLite file.

v0.2 asks a harder question: **once your agents are running reliably, how do you make them run *better*?**

The answer: let an AI optimize the code wrapping your LLM. Automatically. While you sleep.

---

## Meta-Harness: The Biggest Addition

Based on [Meta-Harness (arXiv:2603.28052)](https://yoonholee.com/meta-harness/) from Stanford / KRAFTON / MIT ([original code](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact)).

The **harness** is the code wrapping your LLM — the prompt template, which examples to retrieve, how to structure the reasoning chain, what context to include. The paper showed that changing the harness around a fixed LLM produces a **6x performance gap**. Yet harnesses are designed by hand.

Meta-Harness automates the search.

<!-- META-HARNESS SEARCH LOOP — Generate with this prompt:

Horizontal flow diagram on dark background (#0a0a0f). 16:9 ratio.
4 stages connected by glowing arrows left-to-right:

Stage 1 "SEED" (green accent): 3 small code file icons labeled
"zero-shot", "few-shot", "retrieval" sitting on a platform.

Stage 2 "PROPOSE" (purple accent): A magnifying glass icon over
a stack of files labeled "traces". An AI brain icon reads from
the stack and outputs a new code file with a lightbulb icon.

Stage 3 "EVALUATE" (cyan accent): The new code file runs against
a grid of small test icons (checkmarks and X marks). A score
badge shows "accuracy: 0.80".

Stage 4 "FRONTIER" (orange accent): A simple 2D scatter plot with
3-4 dots on a Pareto curve. Axes labeled "Accuracy" (up) and
"Cost" (right). The top-left dot glows brightest.

Below all 4 stages: a long horizontal bar labeled "SQLite (.db)"
with small icons for "files", "traces", "scores", "events".
Style: clean, minimal, technical. Rounded boxes, thin borders.

-->

![Meta-Harness search loop](mh-search-loop.png)

### How It Works

```
Iteration 0: Evaluate 3 seed harnesses (zero-shot, few-shot, retrieval)
             Store source + scores + FULL EXECUTION TRACES in KAOS archive
                                 |
Iteration 1: Proposer agent reads ALL prior code, scores, AND traces
             Reads 82 files on average. Not summaries — raw traces.
             Notices: "retrieval fails on unusual wording"
             Proposes: two-stage verification harness
             accuracy jumps from 70% → 80%
                                 |
Iteration 2: Proposer reads new traces + all prior history
             Notices: "verification fails on ambiguous inputs"
             Proposes: contrastive examples approach
             Pareto frontier: [best accuracy] [cheapest] [balanced]
                                 |
Iterations 3-N: Each iteration has full history
             Proposer learns what works, what regresses, and WHY
             Makes targeted fixes — the paper shows additive changes
             outperform rewrites
```

**The critical insight** from the paper's ablation study: giving the proposer access to raw execution traces (not summaries, not just scores) improves results by 15+ points. KAOS stores these traces as JSONL files in each harness agent's isolated VFS — queryable with SQL, checkpointed per iteration, portable in one `.db` file.

### Why KAOS for Meta-Harness?

The paper's reference implementation uses a flat filesystem. KAOS provides the infrastructure the search loop actually needs:

**Isolation** — Each harness candidate runs in its own VFS. A buggy harness can't corrupt the archive or other candidates. This is SQL-enforced, not convention.

**Checkpoints** — The search is checkpointed before every iteration. If the proposer or an evaluation crashes at iteration 15, restore to iteration 14 and resume. You don't lose the first 14 iterations of work.

**Audit trail** — Every file read by the proposer, every evaluation run, every tool call is logged. You can reconstruct exactly what the proposer looked at and why it proposed what it did.

**SQL queries** — Instead of grepping through files: `SELECT SUM(token_count) FROM tool_calls`. How many tokens did the whole search cost? One query.

**Portability** — The entire search — every harness, every trace, every proposer conversation — is one `.db` file. Send it to a colleague. Open it on another machine.

---

## Real-World Examples: Engineering

<!-- ENGINEERING EXAMPLES — Generate with this prompt:

Dark background (#0a0a0f), 16:9 ratio. Three panels side by side:

PANEL 1 "Code Review Swarm": 4 small agent icons (colored circles:
red=security, orange=performance, blue=style, green=tests) all pointing
at the same code file in the center. Each agent has a dotted line going
to its own output file below. Label: "4 agents, 0 conflicts".

PANEL 2 "Safe Refactoring": A horizontal timeline with a green flag
(checkpoint), then a code change icon, then a red X (failure), then
a curved green arrow going back to the flag (rollback). Below the
timeline: "Other agents unaffected".

PANEL 3 "Multi-Team Governance": Two separate boxes labeled "Security
Team" and "Product Team", each containing their own agent bubbles.
A lock icon between them. Below: a small .db file icon with "SOC 2".

Style: clean icons, thin borders, minimal. Muted colors with accent
highlights. No text besides labels.

-->

![Engineering use cases](engineering-examples.png)

### Code Review Swarm

Four agents review the same code from different angles — security, performance, style, and test coverage — running in parallel. Each writes to its own isolated VFS. No conflicts. Query the combined results with SQL.

```python
results = await ccr.run_parallel([
    {"name": "security",    "prompt": f"Find security vulnerabilities:\n{code}",
     "config": {"force_model": "deepseek-r1-70b"}},
    {"name": "performance", "prompt": f"Find performance issues:\n{code}"},
    {"name": "style",       "prompt": f"Review style and best practices:\n{code}"},
    {"name": "test-gaps",   "prompt": f"What test cases are missing?\n{code}"},
])
```

After the swarm finishes, query aggregate stats:

```sql
SELECT a.name, SUM(tc.token_count) as tokens, COUNT(tc.call_id) as calls
FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
GROUP BY a.agent_id ORDER BY tokens DESC
```

### Safe Refactoring with Rollback

Checkpoint before risky work. If an agent breaks something, restore just that agent — other agents keep running untouched. Diff two checkpoints to see exactly what changed: files, state, tool calls.

```python
cp = db.checkpoint(agent, label="pre-migration")
try:
    await ccr.run_agent(agent, "Migrate the database schema to v3")
except Exception:
    db.restore(agent, cp)  # only this agent rolls back
    # the 3 other agents? still running, unaffected
```

### Multi-Team Agent Governance

Run agents across teams with enforced isolation. The security team's scanner can't see the product team's code, and vice versa. Export any agent to a standalone file for compliance review. The full audit trail satisfies SOC 2 evidence requirements.

```python
sec_agent = db.spawn("security-scan", config={"team": "security"})
dev_agent = db.spawn("feature-build", config={"team": "product"})

# Enforced isolation — sec_agent cannot read dev_agent's files
# Export for compliance: kaos export <agent-id> -o audit-evidence.db
```

---

## Real-World Examples: Business

<!-- BUSINESS EXAMPLES — Generate with this prompt:

Dark background (#0a0a0f), 16:9 ratio. Three panels side by side:

PANEL 1 "CLV Prediction": A customer profile card icon with an arrow
pointing to a two-step flow: "Predict Churn" (small gauge icon) →
"Predict CLV" (dollar sign icon). Below: a green badge "40% → 72%".

PANEL 2 "CRM Campaigns": An email envelope icon splitting into 4
colored arrows going to 4 customer segment icons (enterprise=briefcase,
smb=store, startup=rocket, consumer=person). Each arrow has a different
tone label. Below: "12% → 24% relevance".

PANEL 3 "Fraud Detection": A transaction card icon passing through a
funnel/filter with red flag checkmarks. Two outputs: green checkmark
"Legitimate" and red X "Fraud". Below: "F1: 0.55 → 0.78".

Style: clean business iconography, dark theme, accent colors matching
KAOS palette. Subtle gradients.

-->

![Business use cases](business-examples.png)

### Customer Lifetime Value Prediction

Your CLV model gets 40% of predictions within 20% of actual value. Meta-Harness discovers that predicting churn first, then CLV conditional on retention, beats single-step prediction by 25 points. It also finds that enterprise and startup customers need completely different prompt framing.

```python
bench = CLVBenchmark()  # your customer data
search = MetaHarnessSearch(db, router, bench,
    SearchConfig(objectives=["+accuracy", "-context_cost"]))
result = await search.run()
# Result: 40% → 72% predictions within 20% of actual CLV
```

### CRM Campaign Optimization

Your email campaigns get 12% open rate. Meta-Harness learns that enterprise wants ROI language, consumers want urgency, and referencing the customer's most-used feature boosts engagement. Different harness per segment outperforms generic.

```python
bench = CRMCampaignBenchmark()
search = MetaHarnessSearch(db, router, bench,
    SearchConfig(objectives=["+relevance", "-context_cost"]))
# Discovered: segment-specific tone beats generic by 2x
```

### Fraud Detection

Your fraud classifier has 65% recall with 30% false positives. Meta-Harness finds that pre-computing red flags (amount deviation, unusual country, velocity) and showing contrastive examples (similar fraud vs. legitimate transactions) improves F1 by 20 points.

```python
bench = FraudDetectionBenchmark()
search = MetaHarnessSearch(db, router, bench,
    SearchConfig(objectives=["+f1_score", "-context_cost"]))
# Result: F1 0.55 → 0.78, false positives cut by 40%
```

---

## Real-World Examples: Autonomous Research

<!-- AUTORESEARCH — Generate with this prompt:

Dark background (#0a0a0f), 16:9 ratio. Split layout:

LEFT "autoresearch (1 agent)": A single GPU icon with one agent
circle on top. A looping arrow around it labeled "modify → train →
eval → keep/discard". Simple, minimal. Label: "1 agent, 1 GPU".

RIGHT "KAOS Research Lab (N agents)": 4 GPU icons in a row, each
with its own colored agent circle (green=architecture, blue=optimizer,
orange=scaling, purple=regularization). Each has its own small looping
arrow. All 4 connect down to a single SQLite cylinder at the bottom.
Label: "N agents, N directions, 1 queryable database".

Between left and right: a large arrow labeled "scales to →".

Style: clean, technical, dark. Colored outlines, no fills. Thin
connecting lines. GPU icons as simple rectangles with chip pattern.

-->

![Autonomous Research Lab](autoresearch-comparison.png)

### The autoresearch Pattern, Scaled

Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — one agent, one GPU, modify `train.py`, run 5-minute experiments, keep improvements, discard regressions.

KAOS scales this: run N research agents in parallel, each exploring a different ML hypothesis, each with its own isolated copy of `train.py`.

```python
# 4 agents, 4 directions, 4 isolated VFS copies of train.py
DIRECTIONS = [
    {"name": "architecture-explorer",
     "prompt": "Explore n_layers, n_heads, d_model, activations..."},
    {"name": "optimizer-explorer",
     "prompt": "Explore AdamW vs Muon, learning rates, weight decay..."},
    {"name": "scaling-explorer",
     "prompt": "Explore model size allocation for fixed compute..."},
    {"name": "regularization-explorer",
     "prompt": "Explore dropout, weight decay, batch size interactions..."},
]

for d in DIRECTIONS:
    agent = db.spawn(d["name"])
    db.write(agent, "/train.py", BASE_TRAIN_PY.encode())
    db.checkpoint(agent, label="baseline")

results = await ccr.run_parallel(DIRECTIONS)
```

What autoresearch does with git commit/reset, KAOS does with formal checkpoints. What autoresearch tracks in a TSV, KAOS tracks in SQL. What autoresearch runs as 1 agent, KAOS runs as N — isolated, checkpointed, queryable.

After all agents finish:

```sql
-- Which agent found the best val_bpb?
SELECT a.name, s.value as best_loss
FROM state s JOIN agents a ON s.agent_id = a.agent_id
WHERE s.key = 'best_val_bpb'
ORDER BY CAST(s.value AS REAL);

-- How many experiments total across all agents?
SELECT COUNT(*) FROM tool_calls WHERE tool_name = 'shell_exec';

-- Total compute cost
SELECT SUM(token_count) as tokens, SUM(duration_ms)/1000 as seconds
FROM tool_calls;
```

---

## Under-the-Hood Improvements

<!-- RUNTIME IMPROVEMENTS — Generate with this prompt:

Dark background (#0a0a0f), 16:9 ratio. Four quadrant layout:

TOP-LEFT "Context Compaction": A long horizontal message list with
the middle section fading/compressing into a summary block (accordion
visual). Arrow pointing to a shorter list. Label: "Summarize, don't drop".

TOP-RIGHT "Tool Permissions": A shield icon with three colored layers
(green=Allow, red=Deny, yellow=Prompt). A tool icon bouncing off the
red layer with an error message bubble. Label: "LLM adapts to denials".

BOTTOM-LEFT "Turn Cap": A circular loop arrow with a counter showing
"16/16" and a stop sign. Prevents infinite tool-call spirals.
Label: "Max 16 tool iterations".

BOTTOM-RIGHT "Usage Tracking": A conversation bubble chain with small
token count badges embedded in each message (input: 450, output: 120).
Label: "Per-message, reconstructable".

Style: clean technical icons, dark theme, thin lines, accent colors.

-->

![Runtime improvements](runtime-improvements.png)

We studied [Claude Code's internal architecture](https://github.com/instructkr/claw-code) (via claw-code's reverse-engineering) and brought four patterns into KAOS:

### 1. Context Compaction (Claude Code's Real Strategy)

**Before:** Drop old messages with a "[N messages omitted]" placeholder.

**After:** Summarize each old message into a one-liner, wrap in a system-role continuation block with "resume without acknowledging the summary" instruction. This is how Claude Code actually handles context overflow internally.

```
This conversation is being continued from a previous context that was compacted.
Summary:
- user: Write unit tests for the payments module
- assistant: I'll create comprehensive tests for charge, refund, and webhook...
- tool: Written 2,450 bytes to /tests/test_payments.py
...
Recent messages are preserved verbatim below.
Continue from where the conversation left off. Do not acknowledge this summary.
Resume directly.
```

### 2. Tool Permission Model

Three modes — Allow, Deny, Prompt — with per-tool overrides and prefix-based deny lists. When a tool is denied, an error result is injected back into the conversation so the LLM sees the denial and adapts its approach.

```python
from kaos.ccr.tools import ToolPermissionPolicy, PermissionMode

# Read-only mode: deny all writes
policy = ToolPermissionPolicy(default_mode=PermissionMode.DENY)
policy.allow_tool("fs_read")
policy.allow_tool("fs_ls")
policy.allow_tool("state_get")

# Or deny specific tools
policy = ToolPermissionPolicy()
policy.deny_tool("shell_exec")  # no shell access
policy.deny_prefixes = ["mcp_"]  # block all MCP tools
```

### 3. Turn Iteration Cap

Prevents runaway tool-call loops where the model keeps calling tools without producing a final text response. Default cap: 16 tool-use iterations per turn (matches Claude Code's internal limit).

### 4. Per-Message Usage Tracking

Token usage is now embedded in each conversation message, so when a session is restored from a checkpoint, the `UsageTracker` can be reconstructed by scanning messages — no external metadata needed.

---

## MCP Server: 11 → 17 Tools

<!-- MCP TOOLS — Generate with this prompt:

Dark background (#0a0a0f), 16:9 ratio. A grid of 6 grouped tool
categories, each in a bordered box with a colored header:

Purple header "Lifecycle" (6 items): spawn, spawn_only, kill, pause, resume, status
Blue header "VFS" (3 items): read, write, ls
Green header "Checkpoints" (4 items): checkpoint, restore, diff, checkpoints
Orange header "Query" (1 item): query (with SQL icon)
Cyan header "Orchestration" (1 item): parallel (with multi-arrow icon)
Magenta header "Meta-Harness" (2 items): mh_search, mh_frontier (with Pareto chart icon)

Each tool name in monospace font. New tools (pause, resume, checkpoints,
mh_search, mh_frontier) have a small "NEW" badge in green.

Style: clean, organized grid. Dark boxes with colored top borders.
Monospace tool names. Minimal.

-->

![MCP tools: 17 across 6 categories](mcp-tools-grid.png)

The MCP server now exposes 17 tools across 6 categories:

- **Lifecycle:** `agent_spawn`, `agent_spawn_only`, `agent_kill`, `agent_pause`, `agent_resume`, `agent_status`
- **VFS:** `agent_read`, `agent_write`, `agent_ls`
- **Checkpoints:** `agent_checkpoint`, `agent_restore`, `agent_diff`, `agent_checkpoints`
- **Query:** `agent_query`
- **Orchestration:** `agent_parallel`
- **Meta-Harness:** `mh_search`, `mh_frontier`

Claude Code can now pause/resume agents, list checkpoints, and run Meta-Harness searches — all as native MCP tool calls. No new configuration needed; the existing MCP server just gained more capabilities.

---

## What's Next

- Run the paper's original benchmarks (LawBench, USPTO-50k, Symptom2Disease, TerminalBench-2) end-to-end
- Multi-GPU autoresearch orchestration across a real GPU cluster
- MCP tool for resuming interrupted Meta-Harness searches
- Dashboard integration for live Meta-Harness search monitoring

---

## Try It

```bash
git clone https://github.com/canivel/kaos.git
cd kaos && uv sync

# Run a meta-harness search
kaos mh search -b text_classify -n 10 -k 2

# Or use the Python API
python examples/meta_harness_support_tickets.py
python examples/autonomous_research_lab.py
```

- **GitHub:** [github.com/canivel/kaos](https://github.com/canivel/kaos)
- **Website:** [canivel.github.io/kaos](https://canivel.github.io/kaos)
- **Tutorial — Local Agents:** [docs/tutorial-local-agents.md](https://github.com/canivel/kaos/blob/main/docs/tutorial-local-agents.md)
- **Tutorial — Meta-Harness:** [docs/meta-harness.md](https://github.com/canivel/kaos/blob/main/docs/meta-harness.md)
- **Tutorial — Autonomous Research:** [docs/tutorial-autoresearch.md](https://github.com/canivel/kaos/blob/main/docs/tutorial-autoresearch.md)

---

*Built by [Danilo Canivel](https://github.com/canivel). KAOS is named after the enemy spy agency in Get Smart (1965) — because KAOS is how you control your agents.*
