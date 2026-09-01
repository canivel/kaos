# Quality-score benchmark (Track A, v0.8.3)

Does a continuous `quality ∈ [0,1]` outcome signal beat binary
`success ∈ {0,1}` for the plasticity ranker?

## Setup

Same non-adversarial library + natural-language queries as
`demo_realistic_retrieval_bench/` (40 skills, 15 queries, deployment-
specific ground truth). Two treatments over 5 seeds, 120 episodes each:

- **binary** — `record_outcome(success=bool)` (the pre-v0.8.3 signal)
- **quality** — `record_outcome(success, quality=q)` where `q` is
  partial credit: `1.0` exact match, `0.4` same-head-noun near miss,
  `0.0` otherwise. Binary throws that middle signal away.

## Reproducing

```bash
uv run python demo_quality_score_bench/run.py
```

## Latest measured result

| Signal | mean acc | pstdev |
|---|---:|---:|
| binary  | 85.3% | 0.0267 |
| quality | 89.3% | 0.0327 |

**Accuracy delta: +4.0 pp.** Quality lifts mean top-1 accuracy from
85.3% to 89.3% across 5 seeds.

## Honest note on variance

The original hypothesis was that partial credit would also *reduce*
run-to-run variance (less noisy Wilson estimator). On this workload
that did **not** hold — quality was marginally noisier
(pstdev 0.0327 vs 0.0267). The accuracy gain is real and consistent;
the variance claim is not, and the benchmark reports it rather than
hiding it. The acceptance gate is "quality must not regress mean
accuracy", which it clears comfortably (+4.0 pp). Variance behaviour is
workload-dependent and not claimed.

Raw JSON: [results.json](results.json)
