# demo_dream_test — Neuroplasticity M1 End-to-End Use Case

This folder contains a single self-checking use case that proves the
`kaos dream` neuroplasticity cycle works end-to-end. It is the validation
script gating the M1 merge to main.

## What it exercises

- Schema v4 migration (fresh DB gets `skill_uses`, `memory_hits`,
  `dream_runs`, `episode_signals` without any manual setup).
- `SkillStore.record_outcome` → writes to `skill_uses` automatically.
- `MemoryStore.search(record_hits=True)` → writes to `memory_hits`.
- `DreamCycle.run(dry_run=True)` → replays events, scores everything,
  writes a digest, does NOT mutate `episode_signals`.
- `DreamCycle.run(dry_run=False)` → same, plus upserts `episode_signals`.
- `SkillStore.search(rank="weighted")` → reorders results based on
  Wilson lower bound × recency (proven different from bm25).
- `MemoryStore.search(rank="weighted")` → same for memory entries.
- Deterministic digest contains hot/cold skills, hot/cold memory,
  recommendations.
- `kaos dream runs` and `kaos dream show <id>` list and render the
  persisted history.

## Reproduce

```bash
cd demo_dream_test
uv run python scenario.py          # seeds + runs + validates; exits non-zero on failure
```

On success the script prints every validation check with a `[PASS]` prefix
and a summary at the end.

## What the scenario plants

Three projects (`payments`, `ml-fraud`, `compliance`), each with:

- 2 agents (lead + helper) that complete successfully
- 2-3 skills per project with **deliberately engineered** usage patterns:
  - `hot-*` skills: 10 applications, ~100% success → should top the weighted ranking
  - `mid-*` skills: 5 applications, ~60% success → middle of pack
  - `cold-*` skills: 0 uses → bottom of the ranking (and flagged cold)
- 2 memory entries per project:
  - One is retrieved 5-8 times via FTS search (record_hits=True)
  - One is never retrieved (cold)

Then the dream cycle must:

1. Replay 6 completed agents.
2. Rank `hot-*` ahead of `cold-*` when searching with `rank="weighted"`.
3. Rank the retrieved memory ahead of the never-retrieved one.
4. Mark the cold skills with `coldness >= 0.5` in the digest.
5. Persist a `dream_runs` row with phase timings and a digest path.
