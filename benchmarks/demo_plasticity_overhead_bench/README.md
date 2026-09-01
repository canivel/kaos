# demo_plasticity_overhead_bench — Inline hook overhead measurement

Honest microbenchmark for **how much latency the inline plasticity hooks
add per agent-facing operation**. This was the third merge-blocker I
flagged in the review: every `SkillStore.record_outcome`,
`MemoryStore.search(record_hits=True)`, and `Kaos.complete()` now fires
extra DB writes — the question is how much that costs.

## Reproduce

```bash
cd demo_plasticity_overhead_bench
uv run python run.py
```

Output: `results.json` and `results.md` in this folder with the measured
per-op timings (median + p99) for hooks-ON vs hooks-OFF.

## What it measures

- `skill_record_outcome_us` — median µs per `SkillStore.record_outcome`
  call, with and without `KAOS_DREAM_AUTO=0`. The delta is the
  Hebbian-association write cost.
- `memory_search_us` — median µs per `MemoryStore.search(record_hits=True)`
  call. Delta = the memory-hit + co-occurrence write cost.
- `agent_complete_us` — median µs per `Kaos.complete()` call. Delta =
  the episode_signals upsert + consolidation-threshold check.

Budget: **< 5 ms per op** at the p50 with auto ON. If the p99 stays under
20 ms we're comfortable. Anything worse and we should optimise.

## Reading the results

Each op is run 1000 times against a library pre-seeded with 100 skills
and 50 memory entries — big enough that the sibling-query in the auto
hook has real work to do, small enough that the benchmark runs in
seconds.

The script exits with code 0 when:

- p50 with auto ON < `LATENCY_BUDGET_MS` per op
- p99 with auto ON < 4× `LATENCY_BUDGET_MS`

Otherwise it exits 1 so CI can gate on overhead regressions.
