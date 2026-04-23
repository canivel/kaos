# Neuroplasticity — the library self-organizes as it's used

KAOS implements plasticity the same way brains do: small, fast, inline
updates on every event (synaptic plasticity), plus heavier threshold-
triggered reorganization (sleep consolidation). No daemon to start. No
command to remember. The library gets better as agents use it.

Where biology uses neurotransmitters and action potentials, KAOS uses
`skill_uses`, `memory_hits`, and `associations` — everything is just
SQLite rows the whole system can read.

## At a glance

| Event | What fires inline | Where it lands |
|---|---|---|
| `SkillStore.record_outcome(...)` | Hebbian update: this skill associates with every other skill the same agent has used. | `associations` (kind='skill'/'skill') |
| `MemoryStore.search(..., record_hits=True)` | Co-retrieved memories associate with each other; cross-modal skill↔memory edges form. | `associations` (kind='memory'/'memory', 'skill'/'memory') |
| `Kaos.complete/fail/kill(agent_id)` | Episode signal row upserted; on failure the latest errored tool_call is normalised + fingerprinted; threshold check fires consolidation in-process. | `episode_signals`, `failure_fingerprints`, `consolidation_proposals` |

Plus, periodically (every `KAOS_DREAM_THRESHOLD` completions, default 25):

| Consolidation step | What it proposes | Auto-applied? |
|---|---|---|
| **Promote** | Memory retrieved ≥ 5 times → becomes a reusable skill template | ✅ in `--apply` mode |
| **Prune** | Skill with ≤ 40% success after ≥ 6 uses → soft-deprecate (recoverable) | ✅ in `--apply` mode |
| **Merge** | Pair of skills with Jaccard ≥ 0.65 overlap → propose merge | ❌ never auto-applied — human review |
| **Policy** | Shared-log intent approved ≥ 90% across ≥ 3 cycles → row in `policies` | ✅ in `--apply` mode |

Every proposal is journalled in `consolidation_proposals` whether or not
it gets applied, so the history is auditable via SQL.

## Measured gain

Ran [`demo_neuroplasticity_bench/`](../demo_neuroplasticity_bench/) on
a synthetic but honest benchmark — 10 twin-pair queries where bm25
alone cannot reliably disambiguate, 20 skills, 80 training episodes,
epsilon-greedy pick (ε = 0.25, RNG seed 42). No planted outcomes.

| Metric | bm25 | weighted (plasticity) | gain |
|---|---:|---:|---:|
| Final top-1 accuracy | 80.0% | 90.0% | **+10.0 pp (+12.5%)** |

Training curve shows the effect in motion:

- bm25: 60% → 70% → 70% → 70% (flat; nothing learns from outcomes)
- weighted: 40% → 48% → 55% → 60% (climbing; plasticity accumulates signal)

Note that **weighted's training-phase accuracy is lower than bm25's**,
because weighted's exploration deprioritises skills that fail — so
successors get tried. The **final top-1 measurement** (no exploration)
then reflects the corrected ranking: weighted reaches 90% top-1 where
bm25 plateaus at 80%.

Raw JSON: [`demo_neuroplasticity_bench/results.json`](../demo_neuroplasticity_bench/results.json).
Rerun anytime: `uv run python demo_neuroplasticity_bench/run.py`.

## Why this is really plasticity

Biological plasticity has four properties. KAOS matches all four:

1. **Event-driven, not scheduled.** Inline hooks fire on every
   `record_outcome`, `memory_hits`, `complete/fail/kill` — not on a cron.
2. **Local.** Each hook only touches what the current agent just did;
   no global recomputation. Associations decay lazily on read, not on
   write.
3. **Both fast and slow pathways.** Synaptic updates (inline, < 1 ms)
   are distinct from consolidation (threshold-triggered, ~100 ms).
4. **Structural changes are gated.** Biology doesn't rewire the
   cortex every time a neuron fires — only after repeated reinforcement.
   KAOS consolidates only at the episode threshold, and destructive
   changes (merges) are never automatic.

## Under the hood

### Schema v5 additions

Four new tables + three columns on `agent_skills`:

| Table | Purpose |
|---|---|
| `skill_uses` (v4) | Per-application telemetry: skill_id, agent_id, used_at, success, task_hash |
| `memory_hits` (v4) | Per-retrieval telemetry: memory_id, agent_id, hit_at, query, rank_pos |
| `dream_runs` (v4) | One row per `kaos dream run` with phase timings + summary |
| `episode_signals` (v4) | One row per agent with derived aggregates (success, tokens, skills_applied) |
| `associations` (v5) | Hebbian graph: (kind_a, id_a) ↔ (kind_b, id_b), weight, uses, last_seen |
| `failure_fingerprints` (v5) | Normalised error signatures with count, tool_name, optional fix_summary + fix_skill_id |
| `policies` (v5) | Auto-promoted shared-log action patterns with approval_rate + sample_size |
| `consolidation_proposals` (v5) | Audit trail: every promote/prune/merge/split proposal with applied flag |

Plus soft-delete columns on `agent_skills`: `deprecated`, `deprecated_at`,
`deprecated_reason`.

### Module layout

```
kaos/dream/
├── __init__.py            # exports DreamCycle, DreamResult
├── signals.py             # recency_weight, wilson_lower_bound, weighted_score
├── auto.py                # inline hooks — the "synaptic" path
├── cycle.py               # DreamCycle orchestrator (7 phases)
└── phases/
    ├── replay.py          # events → episode_signals (idempotent upsert)
    ├── weights.py         # rank skills + memory by recency × success
    ├── associations.py    # read API for the Hebbian graph + related() lookup
    ├── failures.py        # catch-up fingerprint scan + lookup()
    ├── consolidation.py   # promote/prune/merge proposal + apply
    ├── policies.py        # shared-log pattern → policy promotion
    └── narrative.py       # deterministic markdown digest
```

### What agents see at runtime

```python
from kaos import Kaos
from kaos.skills import SkillStore
from kaos.memory import MemoryStore
from kaos.dream.phases.failures import lookup as failure_lookup

kaos = Kaos("project.db")
sk   = SkillStore(kaos.conn)
mem  = MemoryStore(kaos.conn)

# Plasticity-weighted skill search
# (bm25 × Wilson-lower-bound success × recency decay)
candidates = sk.search("classify text topic", rank="weighted", limit=5)

# Plasticity-weighted memory search — also records hits so the
# graph keeps learning.
snippets = mem.search("retry backoff", rank="weighted",
                      record_hits=True, requesting_agent_id=agent_id)

# When a tool_call errors, consult the fingerprint index BEFORE
# paying for an LLM diagnosis.
prior = failure_lookup(kaos.conn, "http_get", error_msg)
if prior and prior["fix_summary"]:
    # Skip the LLM round-trip — we've seen this before.
    apply_known_fix(prior)
```

### Scoring formula

```
weighted_score = max(bm25, 0.01) × usage_factor × recency_weight

usage_factor:
    0.5                                       if uses == 0
    0.5 + usage_multiplier × wilson(s, n)     otherwise  (default multiplier = 3.0)

wilson(s, n): Wilson-score lower bound — a conservative estimator that
  penalises small sample sizes. 10/10 beats 1/1; 0/10 ≈ 0.03 not 0.0.

recency_weight: exponential decay with configurable half-life (default 14 days).
  Never zero — a 1-year-old entry still has ~0.02× weight.
```

The usage_factor has ~7× swing between "proven" and "never used",
enough to overcome moderate bm25 ranking noise while not swamping
genuine relevance on totally-unrelated queries.

## CLI

```bash
kaos dream run [--dry-run|--apply] [--since TS]  # manual full cycle
kaos dream runs                                  # list past runs
kaos dream show <run_id>                         # re-print a digest
kaos dream related <skill|memory> <name-or-id>   # what co-fires?
kaos dream failures [--min-count N]              # recurring errors
kaos dream consolidate [--dry-run|--apply]       # propose or apply structural changes
```

Output is JSON when piped; rich terminal when interactive.

## MCP

See [MCP Integration](mcp-integration.md). The plasticity tools added:

| Tool | What it does |
|---|---|
| `dream_run` | Run one dream cycle; returns run_id and summary |
| `dream_related` | Given a kind+id, return the top-N associated entities |
| `dream_failures` | List recurring failure fingerprints |
| `failure_lookup` | Agent-time fast path: check if an error has a known fix |
| `dream_consolidate` | Propose or apply structural changes |

## Escape hatches

Biological plasticity has opt-outs too (anaesthetics, some drugs). KAOS:

- `KAOS_DREAM_AUTO=0` in the environment disables **all** inline hooks —
  `skill_uses` / `memory_hits` still populate, but associations, failure
  fingerprints, and threshold triggers don't fire. Useful for tests and
  for experiments that need the raw bm25 behaviour.
- `KAOS_DREAM_THRESHOLD=<N>` tunes how often consolidation fires
  (default 25 episodes). Set high to effectively disable auto-consolidation
  without affecting inline associations.
- `rank="bm25"` on `SkillStore.search` / `MemoryStore.search` bypasses
  weighted scoring for that one call.

## Roadmap

M4 — active execution feedback — is a separate decision:

- Router picks model by task-class success history (auto from episodes)
- `kaos run --ask` intake prunes redundant questions against cluster context
- Wave coordinator reads association graph to bundle skills per wave
- Meta-harness proposer seeded with dream-identified strong tool-sequences

Ship M4 when there's clear demand. Current M1+M2+M3 is already
self-organizing end-to-end — M4 is about more aggressive use of the
learned state.
