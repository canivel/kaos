# Realistic retrieval benchmark — measured results

This is the non-adversarial counterpart to `demo_neuroplasticity_bench/`.

- Natural-language queries, not keyword-style.
- Realistic skill library (40 skills) with natural vocabulary overlap
  but NO engineered twin-pair distractors.
- Ground truth is the deployment-specific preferred default, learnt
  from outcome feedback — something BM25 alone cannot infer.

Benchmark run: 120 episodes, 15 queries, 40 skills.

| Metric | bm25 | weighted | gain |
|---|---:|---:|---:|
| Final top-1 accuracy | 73.3% | 86.7% | +13.3pp (+18.2%) |

## Accuracy curve (% correct across 4 checkpoints)

- bm25:     [0.6333333333333333, 0.6666666666666666, 0.6333333333333333, 0.65]
- weighted: [0.6, 0.7, 0.7, 0.7]

## Per-query breakdown

| Query | bm25 | weighted |
|---|:-:|:-:|
| I need to move a schema change into production | - | - |
| snapshot the database before the release | Y | Y |
| clear the cache for the feature flag namespace | Y | Y |
| new endpoint for the accounts resource | Y | Y |
| throttle abusive clients on the search endpoint | Y | Y |
| fire off that email send in the background | Y | Y |
| drain the failed-payment retry queue | - | Y |
| save the uploaded report into object storage | Y | Y |
| load last night's csv extract into the warehouse | Y | Y |
| check if the payments service is up | Y | Y |
| run the tests before I push | Y | Y |
| ship the new image to staging | - | - |
| someone leaked a key so rotate it | Y | Y |
| give me a tl dr of the incident log | Y | Y |
| start a branch for the refund handling work | - | Y |

Raw JSON: [results.json](results.json)
