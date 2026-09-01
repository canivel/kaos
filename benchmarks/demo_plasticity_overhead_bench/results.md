# Plasticity hook overhead — measured

Config: 200 ops, seeded with 100 skills + 50 memories.

Overhead budget: **p50 < 2.0 ms**, p99 < 20.0 ms (10× the p50 budget to absorb filesystem fsync noise).
Overhead = auto=ON minus auto=OFF baseline. The baseline is the intrinsic SQLite commit+fsync cost on this host, not our problem to optimise.


## Per-op timings (median / p99, auto ON vs OFF)

| Op | p50 auto=ON | p99 auto=ON | p50 auto=OFF | p99 auto=OFF | Overhead p50 | Overhead p99 |
|---|---:|---:|---:|---:|---:|---:|
| `record_outcome` | 960.8 µs | 5.18 ms | 985.4 µs | 3.04 ms | -24.6 µs | 2.14 ms |
| `memory_search` | 986.7 µs | 11.12 ms | 1.07 ms | 11.41 ms | -87.0 µs | -297.1 µs |
| `agent_complete` | 2.96 ms | 6.68 ms | 2.00 ms | 13.26 ms | 961.9 µs | -6581.2 µs |

**Verdict:** OK — within budget.
