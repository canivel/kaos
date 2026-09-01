---
type: memory
memory_id: 5
memory_type: result
key: load-test-50k-tps
source_agent: "[[perf-agent]]"
created_at: "2026-04-15T17:12:26.021"
tags: [memory, memory-result]
---

# load-test-50k-tps

> [!kaos-memory] result · by [[perf-agent]]

Load test result: 50,312 TPS sustained, p99 latency 187ms initially. Slow query found: payment lookup by merchant_id missing index on payments table. After adding index: p99 dropped to 141ms. Redis cache hit rate: 94.2%. Kafka consumer lag: 0 under peak load with 6 consumer replicas.