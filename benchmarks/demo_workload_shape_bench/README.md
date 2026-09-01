# Workload-shape metrics bench — measured verdict

**Question:** do the four workload properties that published agent-mechanism
benchmarks provide for free actually exist in KAOS's organic workload?
This bench is descriptive measurement (like `demo_storage_scale_bench`),
not a gated probe: there is no mechanism candidate here, only facts that
either support or kill the transfer-paper thesis before a word is drafted.

**Run:** `uv run python -m demo_workload_shape_bench.bench --db kaos.db`
(read-only; all metrics deterministic; no LLM, no embeddings, no sampling).
Source DB: the operator's live `kaos.db` — 453 agents, 1,639 tool calls,
171 task texts; composition dominated by ARC-AGI-3 mh_search work plus
general dev/ops usage. Disclosed, not sampled around.

## Results (2026-07-28)

| Axis | Benchmark gift | Organic measurement | Verdict for the gift |
|---|---|---|---|
| **M1 arg entropy** | closed action vocabulary (e.g. ALFWorld `(type,object,receptacle)`) | 89.0% of agents (97/109 with ≥8 calls) are mono-label after frozen normalization; among the 12 label-diverse agents median node-reuse = **1.000**, p75 1.12, **0% reach 1.30** | **ABSENT** — trajectories are either one repeated action or all-unique chains; nothing in between |
| **M2 signal density** | dense per-step outcome signals | `episode_signals`, `skill_uses`, `failure_fingerprints`, `critical_steps`, `memory`: **0 rows each**, organically. 2/1,639 tool calls errored (0.12%). Outcome truth exists only at episode grain (`agents.status`: 295 completed / 97 failed / 24 killed) | **ABSENT** — corroborates VOID#1 (n_action=2) and quantifies the OLA premise |
| **M3 lexical anchoring** | templated task text (trivial retrieval) | **85.4%** of 171 task texts carry ≥1 hard lexical anchor (paths 144, identifiers 127, versions 124, error codes 43, hashes 43); median 656 tokens | **PRESENT** — real tasks are anchor-DENSE. This is why BM25-over-verbatim-text keeps working (paper-1 retrieval gains; GDL G4 pairing 1.000) |
| **M4 expert availability** | one expert trajectory per task | exact-task failed→success pair coverage **6.8%** (5/73 failed agents); loose token-Jaccard ≥0.5 coverage 68.5% (50/73) | **ABSENT at benchmark grain** — per-task experts are rare; loose similar-pairs are common but M1 makes them undiffable |

## Honest read

1. **The thesis survives, refined.** Not "benchmarks lie about everything" —
   two of four gifts are genuinely absent organically (M1, M2), one is absent
   at the grain mechanisms need (M4-exact), and one is present (M3). The
   refined claim: *which* mechanism families transfer is predicted by *which*
   axes their premise consumes.
2. **The ledger matches the axes.** GDL died on M1 (0/12 reuse floor — its
   probe's vacuous-G3 audit is the same measurement). Life-Harness VOID#1
   died on M2 (n_action=2 < 200). The retrieval mechanisms that DID survive
   measurement (BM25+Wilson, +10.0/+13.3pp in paper 1) consume M3, the one
   axis the organic workload actually supplies.
3. **Composition caveat, stated plainly:** kaos.db is one system's dev-era
   workload, mh_search-heavy (86% of calls are `harness_run`). The M1
   mono-label rate is partly a composition fact. The 12-agent diverse
   subpopulation is small; per-axis numbers are point estimates with no
   variance story. The paper must carry this as a limitation, not a footnote.
4. **M2's zeros are double-edged and must be reported as such:** they show
   organic signal scarcity AND that this dev DB predates/bypasses the
   plasticity write paths (nobody called `record_outcome()` here). Both
   readings are true; the second is why OLA-style backfill is a live
   candidate rather than refuted.

Artifacts: `results.json` (full per-agent M1 distributions included),
this README. Every number in the transfer paper's Table 1 traces here.
