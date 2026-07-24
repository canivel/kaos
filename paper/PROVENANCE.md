# Data Provenance Ledger — every number in the paper traces here

Rule: no quantitative claim appears in the paper without a row in this table.
All artifact paths are committed in https://github.com/canivel/kaos (main).

| # | Claim in paper | Value(s) | Artifact (committed) | Notes |
|---|---|---|---|---|
| P1 | Adversarial retrieval bench gain | BM25 80.0% → weighted 90.0% (+10.0pp); n=10 queries, 20 skills, 80 episodes | `demo_neuroplasticity_bench/results.md`, `results.json` | small-n disclosed in paper; +10pp = net 1 flipped query (2 gains, 1 regression) |
| P2 | Realistic retrieval bench gain | 73.3% → 86.7% (+13.3pp); n=15 queries, 40 skills, 120 episodes | `demo_realistic_retrieval_bench/results.md`, `results.json` | +13.3pp = 2 flipped queries |
| P3 | Hot-path overhead | record_outcome p50 overhead −24.6µs; memory_search −87.0µs (≈0, within noise); p99 +2.14ms | `demo_plasticity_overhead_bench/results.md` | overhead = auto-ON − auto-OFF; baseline dominated by SQLite fsync |
| P4 | Quality-score signal | binary 85.3% → quality 89.3% (+4.0pp), 5 seeds; pstdev 0.0267 → 0.0327 (variance hypothesis NOT confirmed) | `demo_quality_score_bench/results.md` | negative sub-result reported |
| P5 | α sensitivity | plateau: 93.3% for α ∈ {2,3,5,8,12}; α=0 → 73.3% | `demo_alpha_sweep_bench/results.md` | default α=3 on plateau |
| P6 | Consolidation cost | p50 175.13ms / 475.97ms / 35,545.22ms at 100 / 1k / 10k skills (dry-run, 3 repeats) | `demo_consolidation_scale_bench/results.md` | motivates batch-at-completion, not per-event |
| P7 | Cross-agent FTS5 search at scale | p95 = 1.537ms @1k agents; 9.214ms @10k agents (8 threads, mixed load) | `demo_storage_scale_bench/results_curve.json` | db sizes 7.7MB / 61.9MB |
| P8 | Durability pragma effect | write p95 1894.837ms → 15.433ms; throughput 29.0 → 1118.1 ops/s (FULL/100 → NORMAL/1000) | `demo_storage_scale_bench/results_sweep.json` | ≈122.8× latency, ≈38.6× throughput |
| P9 | Synthesis-consolidation REJECT | LLM arm: FULL = 0.000 on hard classes despite synth-in-topK ≈ 50%; verdict REJECT (G1–G5) | `demo_synthesis_consolidation_bench/VERDICT.md`, `ISA.lock.v2.json` (sha256 09310794…),  commits `5ffe77f`,`f5f8f75`,`ac5d322` (VOID runs incl. `3e79811`) | gates locked before code |
| P10 | Extractive probe DO-NOT-BUILD | EXT = 0.000 on P2/P3, identical to BM25; P1 44/44 token-faithful | `demo_synthesis_consolidation_bench/CLOSING.md`, `PROBE_PREREG.md`, commits `826037d`,`34ca750`,`b5bf7fc` | the FTS-vise structural argument |
| P11 | Action-realization VOID#1 | n_action=2 < 200 required; lock forbade synthetic substitution | `demo_action_realization_bench/VERDICT.md`, `ISA.lock.json` (sha256 3ca89983…), commits `fb6d579`,`1bc1703` | falsification self-test ADMISSIBLE |
| P12 | Instrument-integrity bugs (self-audit) | tautological judge kappa (x==x); empty-kill-gate ACCEPT; verify() crash | commit `48ce322` (fix, red-first); panel record `docs/roadmap/v0.10-candidates.md` + `v0.10-panel-results.json` (committed with this paper) | found by 48-agent self-audit |
| P13 | Storage-sharding rejection | premise measured false (see P7/P8) | `demo_storage_scale_bench/README.md`, commit `8d6db7d` | REJECT-by-measurement |
| P14 | ARC-AGI-3 field observation | Jun 8: #47/~1,100, score 0.43 · Jul 10: #219/1,680, 0.93 · Jul 11: #177/1,693, 1.02 · Jul 18: #39/~1,700 · Jul 24: score 1.33 (rank not recorded) | Kaggle public leaderboard (arc-prize-2026-arc-agi-3), operator-recorded snapshots (site git history: gh-pages commits `cfe78b6`,`9fa43ab`,`191bdf0`,`21a6494`,`e2f8f14`) | observational only; no causal claim |
| P15 | Suite / surface counts | 701 tests passing; 58 MCP tools; schema v9, 26 tables + 2 FTS5 indexes; consolidation threshold default 100 (`kaos/dream/auto.py`) | repo @ `8783871`; `kaos/mcp/server.py::mcp_tool_count()`; `kaos/schema.py` | tool count derives from code |
| P16 | Mechanism ledger | 10 candidates evaluated since v0.7, 0 shipped without ACCEPT | `docs/falsifiable-eval.md` (ledger), memory of verdicts in per-bench VERDICT/CLOSING docs | |

Verification: `uv run python -m pytest tests/` (701 passed at `8783871`); every bench has a `run.py` reproducing its results file.
