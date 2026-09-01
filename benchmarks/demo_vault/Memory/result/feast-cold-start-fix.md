---
type: memory
memory_id: 1
memory_type: result
key: feast-cold-start-fix
source_agent: "[[fraud-agent]]"
created_at: "2026-04-15T17:12:25.878"
tags: [memory, memory-result]
---

# feast-cold-start-fix

> [!kaos-memory] result · by [[fraud-agent]]

Feast cold-start fix: when online store has no features for a new merchant_id, GBM scorer receives null vector causing NaN propagation and scoring crash. Fix: inject global merchant risk percentile (p50) as prior. AUC impact: none at p95. Applied iteration 3, resolved in 18s by SurrogateVerifier.