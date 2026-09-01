# demo_storage_scale_bench — does the single `kaos.db` saturate?

**Verdict: NO (for the reasons the sharding idea assumed). The single-file architecture is not the bottleneck; a one-line durability pragma is.**

The v0.10 scoping panel parked the per-agent-DB / Data-Vault **sharding** proposal behind one prerequisite: *measure whether the single `kaos.db` actually saturates before proposing to shard it* (`docs/roadmap/v0.10-candidates.md`, `storage-scale-bench`, sequenced first in Tier 1 and the sole prerequisite for un-parking the federation storage decision). This is that measurement. It is infrastructure, not a mechanism — no ISA lock, no ACCEPT/REJECT. The deliverable is the saturation curve + an honest read on the premise.

Reproduce:

```bash
uv run python -m demo_storage_scale_bench.bench --scales 1000,10000 --threads 8
uv run python -m demo_storage_scale_bench.bench --scales 1000 --threads 8 --sweep
```

Environment: Windows 11, single machine, 8 worker threads, mixed workload (30% vfs_write / 30% vfs_read / 35% cross-agent memory_search / 5% checkpoint). Seeding is batched (`synchronous=NORMAL`); the measured phase uses the real `Kaos` API. Numbers are one machine's — the *shape* is the finding, not the absolute ms.

---

## Finding 1 — cross-agent FTS5 search does NOT saturate

The premise behind "one big DB won't scale, give every agent its own DB" is that shared structures (cross-agent memory search) degrade with population. They don't.

| agents | db size | **memory_search p95** | memory_search p99 | lock errors |
|---:|---:|---:|---:|---:|
| 1,000 | 7.7 MB | **1.5 ms** | 2.8 ms | 0 |
| 10,000 | 61.9 MB | **9.2 ms** | 10.5 ms | 0 |

At 10k agents (≈50k FTS-indexed memory rows) cross-agent BM25 search is **9 ms p95** — **~55× under** the panel's informal sanity line of 500 ms. FTS5 over one file is not the thing that breaks. Sharding would *lose* this capability (each per-agent DB can only search its own memories; cross-agent recall becomes N-way federated search) to fix a problem that does not exist.

## Finding 2 — the real bottleneck is write-commit contention, and it's flat with scale

The interesting cost is not size, it's concurrency. Under 8 threads all committing to one DB:

| agents | vfs_write p95 | vfs_read p95 | checkpoint p95 | throughput |
|---:|---:|---:|---:|---:|
| 1,000 | 1769 ms | 1610 ms | 2174 ms | 29 ops/s |
| 10,000 | 2049 ms | 1789 ms | 2115 ms | 28 ops/s |

Write/read/checkpoint p95 is ~2 seconds — and **barely moves from 1k to 10k**. That flatness is the tell: this is *writer contention* (SQLite's single WAL writer + an `fsync` on every commit at `synchronous=FULL`), not data volume. It would look identical at 100 agents or 100k.

## Finding 3 — one pragma removes the bottleneck (this is what settles the sharding question)

`synchronous` and `wal_autocheckpoint` are **per-connection** pragmas. Before this bench, `kaos/core.py` hardcoded `wal_autocheckpoint=100` and never set `synchronous` (inheriting SQLite's `FULL`) — both unmeasured. This bench made them configurable and swept them (1k agents, 8 threads):

| pragmas | vfs_write p95 | vfs_read p95 | checkpoint p95 | **throughput** | lock errors |
|---:|---:|---:|---:|---:|---:|
| **FULL / wal100** (old default) | 1895 ms | 1290 ms | 2075 ms | 29 ops/s | 0 |
| **NORMAL / wal1000** | **15 ms** | 0.57 ms | 30 ms | **1118 ops/s** | 0 |
| NORMAL / wal4000 | 21 ms | 0.54 ms | 2.5 ms | 835 ops/s | 0 |

**`synchronous=NORMAL` is a ~125× write-latency improvement and a ~38× throughput improvement (29 → 1118 ops/s) from a single config line, with zero lock errors.** `NORMAL` is the SQLite-recommended setting for WAL mode; the only tradeoff is that an OS crash or power loss (not an application crash) may lose the last few committed transactions — the database stays consistent and uncorrupted. For a local-first agent runtime that is a standard, acceptable trade for two orders of magnitude of throughput.

---

## Implication for the sharding / federation decision

- **Per-agent-DB sharding is REJECT-by-measurement** *for the throughput/scaling rationale that motivated it.* The write-contention it was meant to relieve is recovered ~125× by a pragma, without a rewrite and without losing cross-agent FTS5 search, Hebbian associations, or the shared log. Optimizing an architecture to fix what a config line fixes is the premature-optimization tax the panel warned about.
- **Federation (`federation-pkg-layer`) is untouched by this** and remains the strategic build. It was always storage-agnostic — sharing signed agent packages across teams does not depend on whether each team's agents live in one DB or many. Federation proceeds on the single-DB architecture.
- **The one caveat the numbers don't cover:** true OS-process isolation / independent backup-and-restore / per-tenant hard deletion. If a future requirement is "each tenant's data must be a physically separate file for compliance or blast-radius reasons," that is a *governance* argument for per-tenant DBs, not a *performance* one — and it would be scoped as such, with its own gates, not justified by scaling.

## Recommended follow-ups (each small, each its own change)

1. **Flip the default to `synchronous=NORMAL`** (or expose it in `kaos.yaml` with NORMAL recommended). Made configurable here; default left at `FULL` so this bench introduced no silent behavior change. The flip is a one-line decision with a 125× payoff — **author's call**, because it changes durability semantics.
2. **Reconsider the v0.9.2 `read()`-commits-the-FILE_READ-event fix at scale.** It correctly stopped readers from holding the writer lock, but it made every read an `fsync` commit — visible above as `vfs_read` p95 tracking `vfs_write` at `FULL`. At `NORMAL` it collapses to 0.5 ms, so the pragma also resolves this; still, batching/sampling FILE_READ events is worth measuring as an audit-cost-vs-throughput decision.
3. **Checkpoint manifests** are stored as O(files) inline JSON (`checkpoints.py`); at large VFS counts, dedup via the existing `BlobStore` (keep `manifest_hash`). Not on the hot path here but flagged by the panel.

## Files

- `bench.py` — the runnable bench (populate + concurrent measure + pragma sweep)
- `results_curve.json` — the 1k/10k scale curve (default pragmas), full latency dict
- `results_sweep.json` — the pragma sweep at 1k (FULL vs NORMAL)
