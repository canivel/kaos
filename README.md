# KAOS

**The living synthesis of agentic AI research.** Eight research breakthroughs — neuroplasticity that rewires the library automatically, skills that compound across projects, memory that learns, coordination that requires consensus, context that compresses without loss, agents that co-evolve, failures diagnosed automatically, strategies optimized continuously — unified in one framework. Safe, reliable, and production-grade by default. Self-improving by design.

[![Version](https://img.shields.io/badge/version-0.8.0-blueviolet)]()
[![Python](https://img.shields.io/badge/python-3.11+-blue)]()
[![License](https://img.shields.io/badge/license-MIT-blue)]()
[![Research](https://img.shields.io/badge/research%20integrations-8-brightgreen)]()

> KAOS doesn't build from scratch — it identifies the best solution to each hard problem in agentic AI and integrates it faithfully. Every capability traces back to a proven paper or open-source project. We add new integrations as we find synergy and reason to include them.

![KAOS — parallel agents, Gantt dashboard, live events](docs/demos/kaos_03_parallel_agents.gif)

---

## Install

```bash
git clone https://github.com/canivel/kaos.git && cd kaos
uv sync
kaos setup
```

> Need `uv`? → `curl -LsSf https://astral.sh/uv/install.sh | sh`

**Try the demo instantly (no API keys needed):**

```bash
kaos demo
```

Opens a live dashboard with 3 example execution waves so you can see what KAOS looks like before writing any code.

---

## Use with Claude Code / Cursor / any AI coding tool

After `kaos setup`, KAOS registers itself as an MCP server. Then just ask your AI assistant:

```
with kaos, review my payments module — run a security agent and a test-writing agent in parallel
```

```
with kaos, refactor auth.py — three agents in parallel: implement, test, and document
```

```
with kaos, why did the last run fail? show me the agent that errored and its tool calls
```

KAOS handles isolation, checkpointing, and the dashboard automatically.

---

## What it does

Each capability in KAOS comes from a proven source. Nothing is invented that doesn't need to be.

| Problem | Best-in-class solution | Source | Since |
|---|---|---|---|
| Library stays static as it's used | Neuroplasticity: Hebbian associations, weighted search, failure fingerprints, automatic consolidation — fires inline on every skill use, memory hit, and agent completion | KAOS core | **v0.8.0 🆕** |
| Agents start on under-specified tasks | Dynamic intake — LLM-analyzed clarifying questions (0 or more, no fixed count) | KAOS core | v0.7.1 |
| Agents reinvent solutions | Cross-agent skill library — parameterized templates, usage tracking | [arXiv:2604.08224](https://arxiv.org/abs/2604.08224) | v0.7.0 |
| Agents repeat past mistakes | FTS5 cross-agent memory with BM25 search | [claude-mem](https://github.com/thedotmack/claude-mem) | v0.6.0 |
| Agents act without consensus | SharedLog: intent → vote → decide | [LogAct arXiv:2604.07988](https://arxiv.org/abs/2604.07988) | v0.6.0 |
| Agents co-evolve poorly | Stagnation detection + skill sharing | [CORAL arXiv:2604.01658](https://arxiv.org/abs/2604.01658) | v0.6.0 |
| Failures are opaque | Surrogate Verifier — isolated failure diagnostics | [EvoSkills arXiv:2604.01687](https://arxiv.org/abs/2604.01687) | v0.5.1 |
| Context explodes, quality drops | AAAK compact notation, 57% savings at default | [MemPalace](https://github.com/milla-jovovich/mempalace) | v0.5.2 |
| Strategies don't improve | Evolutionary proposer reads execution traces | [Meta-Harness arXiv:2603.28052](https://arxiv.org/abs/2603.28052) | v0.2.0 |
| Agent isolation is convention | Enforced per-agent VFS + audit trail | KAOS core | v0.1.0 |
| Agent crashes lose progress | Checkpoint / restore / diff | KAOS core | v0.1.0 |

---

## Run agents

**CLI:**
```bash
kaos run "refactor auth.py" -n auth-agent         # single agent
kaos run "..." -n engine --ask                    # intake step first: analyze
                                                  # the task, ask only the
                                                  # clarifying questions the
                                                  # builder genuinely needs
                                                  # (0 or more — dynamic)
kaos run "..." -n engine --ask --intake-only      # preview questions as JSON
kaos parallel \
  -t security "find vulnerabilities" \
  -t tests    "write unit tests" \
  -t docs     "update API docs"                   # parallel agents
```

`--ask` routes the task through the intake agent before any build agent is spawned. A fully-specified task returns `[]` (no questions, agent starts immediately); an under-specified one returns as many clarifying questions as the task actually warrants — there is no fixed count.

**Python:**
```python
from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter

db     = Kaos("project.db")
ccr    = ClaudeCodeRunner(db, GEPARouter.from_config("kaos.yaml"))

results = asyncio.run(ccr.run_parallel([
    {"name": "security", "prompt": "Find vulnerabilities in auth.py"},
    {"name": "tests",    "prompt": "Write unit tests for auth.py"},
]))
```

---

## Inspect & debug

```bash
kaos ls                            # list all agents + status
kaos status <id>                   # detailed agent status (pid, heartbeat, config)
kaos logs <id>                     # conversation + event log
kaos read <id> /path/to/file       # read a file from the agent's VFS
kaos search "TODO"                 # full-text search across every agent's VFS
kaos index <id>                    # build /index.md of the agent's VFS
kaos checkpoint <id> -l "safe"     # snapshot files + KV state
kaos checkpoints <id>              # list all checkpoints
kaos restore <id> --checkpoint X   # roll back to that snapshot
kaos diff <id> --from X --to Y     # what changed between checkpoints?
kaos kill <id>                     # terminate a running agent
kaos query "SELECT * FROM events"  # raw SQL on everything
kaos export <id> --output a.db     # export one agent to a standalone .db
kaos import a.db --merge           # import agents back from a standalone .db
kaos ui                            # open the web dashboard
```

---

## Dashboard

```bash
kaos ui        # web dashboard — Gantt timeline, live events, agent inspector
kaos dashboard # terminal TUI
kaos demo      # demo data + open dashboard
```

The web dashboard shows each execution wave as a **Gantt timeline**: one horizontal bar per agent, colored by status (green = done, purple = running, red = failed). Click any bar to inspect tool calls, files, checkpoints, and events.

---

## Model providers

KAOS routes every inference call through the GEPA router, which supports **5 providers** (raw `httpx` under the hood — no OpenAI SDK, no LiteLLM, no vendor lock-in):

| Provider | How it's called | API key | Typical use |
|---|---|---|---|
| `claude_code` | Claude Code CLI subprocess (uses your existing CLI login) | none | default when you already have Claude Code installed |
| `agent_sdk` | Claude Agent SDK in-process (no subprocess, no rate-limit contention) | none | recommended when you run alongside an active Claude Code session |
| `anthropic` | Anthropic `/v1/messages` via httpx | `ANTHROPIC_API_KEY` | production, explicit billing |
| `openai` | OpenAI / Azure / any OpenAI-compatible endpoint | `OPENAI_API_KEY` | GPT, local vLLM served as OpenAI-compatible |
| `local` | vLLM / ollama / llama.cpp `/v1/chat/completions` | none | fully local, zero cost per call |

Any mix of providers can coexist in a single `kaos.yaml` — route trivial/moderate work to a local model and send critical/complex tasks to a frontier model. `kaos setup` walks you through configuration.

---

## Cross-agent knowledge — Skills, Memory, Shared Log

Three independent stores that agents use to talk to each other across sessions, projects, and databases. All three are FTS5-indexed and queryable with plain CLI:

```bash
# Skill Library — reusable parameterized templates
kaos skills save --name fastapi-gateway \
  --description "FastAPI + idempotent payments + webhook DLQ" \
  --template "Build a FastAPI gateway for {project} with ..."
kaos skills search "payments fastapi"
kaos skills apply 1 --param project=checkout

# Cross-Agent Memory — searchable results, insights, errors
kaos memory write <agent_id> "Feast cold-start: inject p50 risk as prior" \
  --type result --key feast-cold-start-fix
kaos memory search "cold start"

# Shared Log — LogAct intent / vote / decide coordination
kaos log tail --n 20             # last 20 entries
kaos log ls                      # counts by type (intent/vote/decide/commit/…)
```

All three are exposed as MCP tools too (see below).

---

## Neuroplasticity — the library self-organizes as it's used

Every skill application, memory retrieval, and agent completion fires a
small plasticity hook that updates the library **inline** — like synaptic
plasticity. Every N completions (default 25), a lightweight consolidation
pass runs in-process — like sleep consolidation.

No daemon to start. No command to remember. It just happens.

```bash
kaos dream run [--dry-run|--apply]                  # manual full cycle (7 phases)
kaos dream runs                                      # list past dream runs
kaos dream show <run_id>                             # re-print a past digest
kaos dream related <skill|memory> <name>             # Hebbian: what co-fires with this?
kaos dream consolidate [--dry-run|--apply]           # promote/prune/merge proposals
kaos dream failures [--min-count N]                  # recurring fingerprints + category
kaos dream diagnose <fp_id>                          # show diagnosis
kaos dream diagnose <fp_id> --category infra \
  --root-cause "..." --action "..."                  # manual override
kaos dream fix-outcome <fp_id> --succeeded           # record whether a fix worked
kaos dream systemic [--ack N|--resolve N] [--by X]   # systemic alerts lifecycle
```

What gets learned automatically:

| Event | What plasticity does |
|---|---|
| `SkillStore.record_outcome(...)` | Hebbian association: this skill co-fires with every skill the same agent has already used. Success = weight +1.0, failure = +0.3. |
| `MemoryStore.search(..., record_hits=True)` | Co-retrieved memories get associated; cross-modal skill↔memory edges form if the agent has used skills. |
| `Kaos.complete/fail/kill(agent_id)` | Episode signals written inline. On failure: normalised error fingerprint captured automatically. Threshold crossed → consolidation runs in-process. |

What consolidation does (in `--apply` mode):

- **Promote**: memory retrieved 5+ times → becomes a skill template
- **Prune**: skills with <40% success after 6+ uses → soft-deprecate (recoverable)
- **Merge**: near-duplicate skills (Jaccard ≥ 0.65 on descriptions) → proposal only; merges are never auto-applied
- **Policies**: shared-log intents approved ≥ 90% across 3+ cycles → promoted to the `policies` table

What agents see at runtime:

```python
# Weighted search — bm25 × Wilson(success) × recency decay
skills.search("payments fastapi", rank="weighted")
memory.search("retry", rank="weighted", record_hits=True,
              requesting_agent_id=agent_id)

# Known-failure shortcut — skip the LLM on a recurring error
from kaos.dream.phases.failures import lookup
prior = lookup(conn, "http_get", error_msg)
if prior and prior["fix_summary"]:
    apply_known_fix(prior)
```

Escape hatches: `KAOS_DREAM_AUTO=0` disables inline hooks entirely,
`KAOS_DREAM_THRESHOLD=<N>` tunes consolidation cadence.

### Measured gain — scenario-conditional

Plasticity pays off when your workload has **disambiguation signal** —
multiple plausible skills per query, and outcome feedback over time
that distinguishes them. Our
[`demo_neuroplasticity_bench/`](demo_neuroplasticity_bench/) measures
this precisely: 10 ambiguous twin-pair queries, 20 skills, 80 training
episodes, epsilon-greedy pick (ε=0.25, seed=42), zero planted outcomes:

| | bm25 baseline | weighted (plasticity) | gain |
|---|---:|---:|---:|
| **Top-1 accuracy on ambiguous retrieval** | 80.0% | 90.0% | **+10.0 pp (+12.5%)** |

**Gains are workload-specific.** On a single-session, no-feedback
workload (agent spawns, runs once, no `record_outcome` calls) the gain
is zero — plasticity needs signal to learn from. Multi-session
engagements with consistent outcome feedback will see compounding gains.

Run it yourself: `uv run python demo_neuroplasticity_bench/run.py`.
Raw numbers: [`results.json`](demo_neuroplasticity_bench/results.json).

### Measured overhead

Real benchmark in [`demo_plasticity_overhead_bench/`](demo_plasticity_overhead_bench/)
measures the per-op cost of the inline hooks. The fast-path redesign
(v0.8.1) moved association building from per-event to batched-at-agent-
completion, dropping the hot-path cost to near-zero. See the
[results](demo_plasticity_overhead_bench/results.md) — the measured
overhead is dominated by SQLite's intrinsic `COMMIT` fsync latency
(~30 ms on Windows), not the plasticity writes themselves. On Linux
with faster fsync or on an in-memory DB the absolute numbers are much
lower.

Set `KAOS_DREAM_AUTO=0` to disable all hooks if the hot path matters
more than learning.

### Failure intelligence

[`demo_failure_intelligence_bench/`](demo_failure_intelligence_bench/)
validates that KAOS categorises errors into `transient / config / code /
infra / unknown` via built-in heuristic diagnosers (no LLM calls), tracks
fix outcomes and auto-downgrades broken "fixes" after 5+ failed attempts,
and raises systemic alerts when multiple agents hit the same fingerprint
in a short window. 60/60 validations passing.

See [`docs/neuroplasticity.md`](docs/neuroplasticity.md) for the full
mechanism and [`demo_arc_agi3_test/`](demo_arc_agi3_test/) for a 76-check
validation against a simulated ARC-AGI-3 meta-harness workload.

---

## Meta-Harness — automated harness optimization

Run an evolutionary search over agent harnesses themselves. The proposer reads execution traces from previous iterations, proposes new harness candidates, and the evaluator scores them on a benchmark. Pareto frontier, stagnation detection (CORAL), skill distillation.

```bash
kaos mh search --benchmark text_classify --iterations 20 --candidates 4
kaos mh search --benchmark arc_agi3 --background       # detached worker
kaos mh frontier <search_agent_id>                     # Pareto frontier
kaos mh inspect <search_agent_id> <harness_id>         # source + scores + trace
kaos mh status <search_agent_id>                       # iterations, frontier size
kaos mh resume <search_agent_id> --benchmark text_classify
kaos mh knowledge                                      # skills distilled across all searches
```

Built-in benchmarks: `text_classify` (DBpedia), `math_rag`, `agentic_coding`, `arc_agi3` (ARC-AGI-3), plus an extensible framework for your own.

---

## MCP server

```bash
kaos serve                         # stdio (default — for Claude Code / Cursor)
kaos serve --transport sse --port 8788   # SSE over HTTP
```

Exposes **45 tools** to any MCP client: 18 agent lifecycle/VFS/checkpoint/query/parallel, 5 skill, 3 cross-agent memory, 5 shared-log, 9 meta-harness (including CORAL co-evolution and skill distillation), and **8 neuroplasticity** (`dream_run`, `dream_related`, `failure_lookup`, `failure_list`, `dream_consolidate`, `failure_diagnose`, `failure_fix_outcome`, `systemic_alerts`). See [`docs/mcp-integration.md`](docs/mcp-integration.md).

---

## Python library

```python
from kaos import Kaos
from kaos.memory import MemoryStore
from kaos.skills import SkillStore
from kaos.shared_log import SharedLog

db = Kaos("project.db")

# Each agent has its own isolated filesystem
a = db.spawn("refactorer")
b = db.spawn("test-writer")
db.write(a, "/src/auth.py", b"# refactored")
db.write(b, "/src/auth.py", b"# tests")  # no conflict — separate VFS

# Checkpoint / restore
cp = db.checkpoint(a, label="before-migration")
db.restore(a, cp)  # roll back just this agent

# Cross-agent memory, skills, coordination — all backed by FTS5
mem = MemoryStore(db.conn)
mem.write(a, "Found idempotency bug in retry path", type="insight")
mem.search("idempotency")

sk = SkillStore(db.conn)
sk.save("security_review", "Check for injection attacks",
        template="Review {target} for SQL injection and XSS...")
sk.search("security")

log = SharedLog(db.conn)
intent_id = log.intent(a, "refactor auth module")
log.vote(b, intent_id, approve=True, reason="plan looks safe")
log.decide(intent_id, a)

# Full SQL over everything
db.query("SELECT name, status FROM agents")
db.query("SELECT SUM(token_count) FROM tool_calls WHERE agent_id = ?", [a])
```

Running agents programmatically (async via the CCR runner):

```python
import asyncio
from kaos.ccr.runner import ClaudeCodeRunner
from kaos.router.gepa import GEPARouter

router = GEPARouter.from_config("kaos.yaml")
ccr    = ClaudeCodeRunner(db, router)

# Single agent
result = asyncio.run(ccr.run_agent(a, "Refactor auth.py for testability"))

# N agents in parallel, each with isolated VFS
results = asyncio.run(ccr.run_parallel([
    {"name": "security", "prompt": "Find vulnerabilities in auth.py"},
    {"name": "tests",    "prompt": "Write unit tests for auth.py"},
    {"name": "docs",     "prompt": "Update API docs"},
]))
```

---

## Documentation

| | |
|---|---|
| [Philosophy](docs/philosophy.md) | Why KAOS synthesizes research, integration criteria, what's next |
| [Dashboard](docs/dashboard.md) | Gantt timeline, agent inspector, live events |
| [Use Cases](docs/use-cases.md) | Code review swarm, parallel refactor, incident response, ML research, and more |
| [Checkpoints](docs/checkpoints.md) | Snapshot, restore, diff — with examples |
| [CLI Reference](docs/cli-reference.md) | Every command and flag |
| [MCP Integration](docs/mcp-integration.md) | Claude Code / Cursor setup, all 45 tools |
| [Neuroplasticity](docs/neuroplasticity.md) | Inline plasticity, failure intelligence, measured gains + overhead |
| [Meta-Harness](docs/meta-harness.md) | Automated harness optimization, CORAL co-evolution |
| [Cross-Agent Memory](docs/memory.md) | FTS5 searchable memory across agents and sessions |
| [Skill Library](docs/skills.md) | FTS5 cross-agent procedural skill templates with usage tracking |
| [Shared Log](docs/shared-log.md) | LogAct intent/vote/decide coordination protocol |
| [Architecture](docs/architecture.md) | Internals, subsystem design |
| [Schema](docs/schema.md) | All 17 SQLite tables + 2 FTS5 indexes (schema v6) |
| [Deployment](docs/deployment.md) | vLLM, production config |

Full docs index → [`docs/`](docs/)

---

## Examples

See [`examples/`](examples/) for:
- `code_review_swarm.py` — 4 agents review code in parallel
- `parallel_refactor.py` — implement + test + document simultaneously
- `self_healing_agent.py` — auto-restore on failure
- `autonomous_research_lab.py` — N hypothesis agents, SQL result comparison
- `meta_harness_*.py` — automated prompt/strategy optimization
- `memory_search.py` — cross-agent FTS5 memory write and search
- `shared_log_coordination.py` — LogAct 4-stage coordination walkthrough
- `safety_voting.py` — human-in-the-loop safety gate with voting

---

## How agents are isolated

Each agent's files, state, tool calls, and events are stored in separate rows scoped by `agent_id`. There is no shared filesystem — it's enforced at the query level, not by convention. The entire runtime is one `.db` file you can copy, share, or open in any SQLite client.

---

## Credits

KAOS builds on ideas from several open-source projects and research papers:

**Cross-Agent Memory** (`kaos/memory.py`, `kaos memory` CLI, `agent_memory_*` MCP tools)
Inspired by [claude-mem](https://github.com/thedotmack/claude-mem) by Alex Newman ([@thedotmack](https://github.com/thedotmack)), AGPL-3.0.
The core idea — agents writing compact, searchable memories for cross-session retrieval — is taken directly from claude-mem. KAOS adapts it for SQLite FTS5, multi-agent access, and typed entries.

**Shared Log / LogAct Protocol** (`kaos/shared_log.py`, `kaos log` CLI, `shared_log_*` MCP tools)
Inspired by **LogAct: Enabling Agentic Reliability via Shared Logs**
Balakrishnan, Shi, Lu, Goel, Baral, Lyu, Dredze (2026), Meta. [arXiv:2604.07988](https://arxiv.org/abs/2604.07988)
The intent/vote/decision 4-stage loop and append-only log design are taken directly from LogAct. KAOS adapts it for SQLite WAL mode, adds `policy` and `mail` entry types, and integrates agent_id as a first-class citizen.

**CORAL** (stagnation detection, skill distillation, co-evolution)
Meta-Harness's CORAL features are independently derived from similar ideas in the evolutionary optimization literature.

**Skill Library** (`kaos/skills.py`, `kaos skills` CLI, `skill_*` MCP tools)
Informed by **Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering**
Zhou, Chai, Chen, et al. (2026). [arXiv:2604.08224](https://arxiv.org/abs/2604.08224)
The paper's skills axis — parameterized procedural templates that agents save, search, and apply — is the foundation for KAOS's SkillStore. KAOS adapts it for SQLite FTS5, adds usage/success tracking for reliability ranking, and integrates it alongside memory and shared log as the third externalization layer.

**EvoSkills / MemPalace**
Earlier KAOS versions integrated ideas from EvoSkills (v0.5.1) and MemPalace (v0.5.2).

---

KAOS is open source, MIT licensed. Contributions welcome.
