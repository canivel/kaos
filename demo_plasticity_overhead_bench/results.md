# Plasticity hook overhead — measured

Config: 200 ops, seeded with 100 skills + 50 memories.

Overhead budget: **p50 < 2.0 ms**, p99 < 20.0 ms (10× the p50 budget to absorb filesystem fsync noise).
Overhead = auto=ON minus auto=OFF baseline. The baseline is the intrinsic SQLite commit+fsync cost on this host, not our problem to optimise.


## Per-op timings (median / p99, auto ON vs OFF)

| Op | p50 auto=ON | p99 auto=ON | p50 auto=OFF | p99 auto=OFF | Overhead p50 | Overhead p99 |
|---|---:|---:|---:|---:|---:|---:|
| `record_outcome` | 949.5 µs | 13.36 ms | 934.8 µs | 2.90 ms | 14.7 µs | 10.46 ms |
| `memory_search` | 1.04 ms | 4.04 ms | 1.08 ms | 2.73 ms | -48.0 µs | 1.31 ms |
| `agent_complete` | 2.95 ms | 6.85 ms | 2.08 ms | 5.38 ms | 872.6 µs | 1.47 ms |

**Verdict:** OK — within budget.
