# Consolidation-at-scale benchmark

Wall-clock cost of a full dream consolidation pass (dry-run) across
libraries ranging from 100 to 10,000 skills.

## Why this matters

Whitepaper §6.1 noted that we hadn't characterised how the consolidation
phase scales beyond a few dozen skills. The merge-detection step uses a
pairwise Jaccard similarity check, which is quadratic in the skill
count by construction. This benchmark measures the actual impact.

## What it measures

For each scale, three cold-open runs of `run_consolidation(dry_run=True)`
against a freshly seeded database with:

- `n` skills with randomised shared vocabulary
- `n/20` memories (half with enough hits to trigger promotion)
- `5 * n` skill_uses rows with mixed success/failure outcomes

Reports p50 and max wall time in milliseconds.

## Reproducing

```bash
uv run python demo_consolidation_scale_bench/run.py
```

Seeding dominates the runtime at 10k (~7 minutes). Measurement itself
runs in well under a minute even at that scale.

## Latest measured result (v0.8.3 re-run)

| n skills | p50 (ms) | max (ms) |
|---:|---:|---:|
| 100 | 175.1 | 672.1 |
| 1,000 | 476.0 | 482.5 |
| 10,000 | 35,545.2 | 36,948.2 |

**Effective growth exponents:**

- 100 → 1,000: exponent ~0.43 (sub-linear)
- 1,000 → 10,000: exponent ~1.87 (near-quadratic — the pairwise Jaccard
  merge scan, exactly as designed)

No regression from the v0.8.2 characterisation: the shape is identical
(sub-linear to 1k, near-quadratic above). The v0.8.3 schema change is
additive columns only and does not touch consolidation logic. Absolute
numbers vary run-to-run — note the 100-skill case is noisy (p50 175 ms,
max 672 ms): at that scale the phase finishes so fast that OS-level
jitter dominates, which is why this is a *budget* concern at large
scale, not a *latency* one.

## Interpretation

The phase is cheap up to ~1,000 skills (half a second). Beyond that the
pairwise merge-detection step becomes the dominant cost as expected. A
future optimisation could replace the O(n²) Jaccard scan with a blocked
comparison (e.g. MinHash LSH), which would bring the 10k case back into
the second-range.

For today's KAOS deployments this is acceptable: the phase runs during
`kaos dream` at human-scheduled intervals, not on the agent hot path.
Skill libraries passing 5,000 items should set
`KAOS_DREAM_MERGE_THRESHOLD=off` (skip merge detection) or shard by tag.

Raw numbers: [results.json](results.json).
