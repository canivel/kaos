# Quality-score benchmark — measured results

Binary `success ∈ {0,1}` vs continuous `quality ∈ [0,1]` on the non-adversarial retrieval workload.

Run: 120 episodes/run, 5 seeds.

| Signal | mean acc | pstdev |
|---|---:|---:|
| binary  | 85.3% | 0.0267 |
| quality | 89.3% | 0.0327 |

Accuracy delta: **+4.0 pp**. Variance change: **+0.0060** (seed-level variance increased — the variance-reduction hypothesis was NOT confirmed).

Raw JSON: [results.json](results.json)
