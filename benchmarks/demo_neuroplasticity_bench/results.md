# Neuroplasticity gain — measured results

Benchmark run: 80 episodes, 10 queries, 20 skills.

| Metric | bm25 | weighted | gain |
|---|---:|---:|---:|
| Final top-1 accuracy | 80.0% | 90.0% | +10.0pp (+12.5%) |

## Accuracy curve (% correct across 4 checkpoints)

- bm25:     [0.6, 0.7, 0.7, 0.7]
- weighted: [0.4, 0.475, 0.55, 0.6]

## Per-query breakdown

| Query | bm25 | weighted |
|---|:-:|:-:|
| classify text topic | ✗ | ✓ |
| forecast time series | ✓ | ✓ |
| detect time series anomaly | ✓ | ✓ |
| classify image label | ✓ | ✓ |
| segment image pixel region | ✓ | ✗ |
| transcribe speech audio | ✓ | ✓ |
| classify audio clip | ✓ | ✓ |
| classify tabular structured row | ✓ | ✓ |
| detect tabular anomaly row | ✗ | ✓ |
| extract named entity span | ✓ | ✓ |

Raw JSON: [results.json](results.json)
