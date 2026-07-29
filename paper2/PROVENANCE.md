# Data Provenance Ledger — paper 2 (workload-shape / transfer)

Rule: no quantitative claim appears in the paper without a row here.
All artifact paths are committed in https://github.com/canivel/kaos (main)
unless marked CITATION (external paper facts, used as corroboration only).

**Evidence tiers, declared up front and used in the paper text:**
- **Tier A** — pre-registered, hash-locked, falsifiable probes with binding verdicts.
- **Tier B** — mechanical, deterministic measurements (no lock; no mechanism under test).
- **Tier C** — panel evaluations of external papers (no measurement; motivation only,
  never evidence for a quantitative claim).

| # | Claim in paper | Value(s) | Tier | Artifact (committed) |
|---|---|---|---|---|
| W1 | M1 arg entropy: closed-vocabulary gift absent | 89.0% (97/109) of organic agents (≥8 calls) mono-label (<3 distinct normalized labels); diverse subpop n=12: median reuse 1.000, p75 1.120 (p75 recorded in W5's VERDICT diagnostic), 0% ≥ 1.30; composition: 1,405/1,639 calls (85.7%, ≈ 86%) from the harness_run search-worker archetype | B | `demo_workload_shape_bench/results.json`, commit `3045e66` |
| W2 | M2 signal density: dense-signal gift absent | `episode_signals`/`skill_uses`/`failure_fingerprints`/`critical_steps`/`memory` = 0 rows each organically; tool-call error rate 2/1,639 (0.12%); episode-grain truth only (`agents.status` 295 completed / 97 failed / 24 killed / 37 initialized) | B | same |
| W3 | M3 lexical anchoring: templated-text gift PRESENT | 85.4% (146/171) task texts carry ≥1 hard anchor (path 144, identifier 127, version 124, error-code 43, hash 43); median 656 tokens | B | same |
| W4 | M4 expert availability: per-task-expert gift absent at benchmark grain | exact failed→success task-pair coverage 6.8% (5/73); token-Jaccard ≥0.5 coverage 68.5% (50/73) | B | same |
| W5 | GDL probe (EMG distillation): full lifecycle incl. vacuous-gate instrument finding | lock sha256 `97912757…` committed before feature code (`50360ec`); falsification self-test ADMISSIBLE; binding: FULL 1.000 / B1 0.188 / L1 0.000, n=48 constructed; pairing 1.000; organic G3 median 10.000 (VACUOUS — 97/109 mono-label); post-hoc diagnostic 0/12 diverse agents ≥1.30; verdict ACCEPT-per-lock, disposition DO-NOT-SHIP; exp_id 2 | A | `demo_graphdiff_localizer_bench/{ISA.lock.json, PROBE_PREREG.md, results.json, VERDICT.md}`, commits `50360ec`, `fc410cc` |
| W6 | Life-Harness action-realization probe: VOID#1 organic scarcity | n_action = 2 < 200 lock floor; synthetic substitution forbidden by lock (sha256 `3ca89983…`); falsification self-test ADMISSIBLE | A | `demo_action_realization_bench/{ISA.lock.json, VERDICT.md}`, commits `fb6d579`, `1bc1703` |
| W7 | FTS-vise: retrieval-side synthesis impossibility under lexical-only constraints | LLM arm FULL = 0.000 on hard classes despite synth-in-topK ≈ 50% (REJECT G1–G5, lock v2 sha256 `09310794…`); extractive arm EXT = 0.000 on P2/P3 with 44/44 token-faithfulness (DO-NOT-BUILD) | A | `demo_synthesis_consolidation_bench/{VERDICT.md, CLOSING.md, PROBE_PREREG.md}`, commits `ac5d322`, `b5bf7fc`, `826037d` |
| W8 | Storage-sharding rejection-by-measurement (premise-check precedent) | cross-agent FTS5 p95 1.537 ms @1k agents, 9.214 ms @10k; durability pragma dominated write cost (p95 1,895→15 ms; 29→1,118 ops/s) | B | `demo_storage_scale_bench/{README.md, results_curve.json, results_sweep.json}`, commit `8d6db7d` |
| W9 | Positive control: mechanisms consuming the PRESENT axis (M3) do transfer | BM25+Wilson+recency retrieval +10.0pp (n=10, raw 8/10→9/10) and +13.3pp (n=15, raw 11/15→13/15) top-1 over BM25 (small-n disclosed; retroactive measurement, NO lock) | B | `demo_neuroplasticity_bench/`, `demo_realistic_retrieval_bench/` (paper-1 P1/P2); paper 1 doi:10.5281/zenodo.21533588 |
| W10 | Evaluation ledger: 13 candidates since v0.7 (May–July 2026), 0 NEW mechanisms shipped without surviving a probe | verdict classes: 2 full probes run (W5, W6), 2 measured rejects (W7, W8), remainder panel-tier; 5 REJECT / 2 DO-NOT-BUILD / 3 PARK / 1 VOID / 1 ACCEPT-do-not-ship / 1 pre-existing shipped family retroactively measured (W9) | A/B/C mix — tier stated per row in the paper's Table 2 | `docs/falsifiable-eval.md`, experiments journal (exp_id 1, 2), per-bench VERDICT/CLOSING docs |
| W11 | External corroboration: skills/episodic-memory transfer failures | SWE-Skills-Bench: 39/49 deployed skills zero gain, 3 degraded ≤ −10pp; CTIM-Rover: cross-task episodic memory beat baseline in 0 configs; HASP ablation: unfiltered evolution −24pp (60.3→36.3) | CITATION | arXiv:2603.15401, arXiv:2505.23422, arXiv:2605.17734 |
| W12 | EMG source-paper facts (motivating case) | ALFWorld/ScienceWorld only; per-task experts from an expert-trajectory dataset; single-run numbers, no seeds/CIs; unnamed embedding model; no code | CITATION | arXiv:2607.13884 (v1 html, read 2026-07-28) |
| W13 | Suite / repo state | 707 tests + 1 skipped at `fc410cc`; bench-local containment test guards the GDL DO-NOT-SHIP disposition | B | `tests/test_graphdiff_probe.py`, repo @ `fc410cc` |

Verification: `uv run python -m pytest tests/` (707 passed, 1 skipped at `fc410cc`);
`uv run python -m demo_workload_shape_bench.bench --db kaos.db` regenerates W1–W4
against the live DB (values recorded at `3045e66` are the paper's frozen snapshot).
