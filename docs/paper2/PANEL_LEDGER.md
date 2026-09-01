# Panel Ledger — paper 2 ("Benchmark Gifts"), review of 2026-07-28

Three-level, nine-reviewer panel run against draft commit `56895a8`
(workflow `wf_bca234da-d7c`, 9/9 completed). Verdicts: 0 REJECT, 7 MAJOR,
2 MINOR. Findings: **12 BLOCKER / 25 MAJOR / 24 MINOR.** All blockers and
all substantive majors applied; dispositions below.

## Blockers (all FIXED)

| Theme (reviewers) | Finding | Disposition |
|---|---|---|
| Hallucinated chronology (Ground-2, Rigor-2) | "six months / 2026-01 through 2026-07" vs git truth: v0.7 = 2026-04-15, evaluations 2026-05-16 → 2026-07-28 | FIXED — "three months since v0.7 (May–July 2026)" everywhere; Table 2 caption corrected |
| Wrong interval (Ground-2, Hostile-1) | "five weeks later" — VOID#1 (`1bc1703`, 05-24) to shape audit (`3045e66`, 07-28) is nine weeks | FIXED — "nine weeks" |
| Dropped denominator (Rigor-1, Hostile-2) | Abstract "89.0% of agent trajectories" is 97/109 with ≥8 calls, not 97/453 | FIXED — qualifier in abstract + archetype attribution |
| False shipping claim (Rigor-1, Rigor-3, Hostile-3) | "none was shipped without surviving a probe" false for the retroactively-measured retrieval family | FIXED — "no NEW mechanism…; pre-existing family retroactively held to the standard" |
| Broken intro list (Rigor-3, Hostile-1) | "We propose four:" followed by the contributions list; gifts never enumerated | FIXED — gifts enumerated inline; `\paragraph{Contributions.}` |
| Circularity unconfronted (Hostile-1) | Axes derived from the deaths they "predict" — never addressed | FIXED — new §6 paragraph: retrodictive on this ledger; out-of-sample pieces named; published to be falsified |
| Novelty vs paper 1 (Hostile-1) | "first such series" claim collides with companion paper's own 10-candidate ledger | FIXED — delta delineated (axis account + tier bookkeeping); "first" rescoped to binding-verdict governance |
| Tier-C count wrong (Hostile-3) | Limitations said six Tier-C rows; Table 2 has seven | FIXED — "Seven of thirteen" |

## Majors (25 — applied unless noted)

Applied: raw-count reporting for +10.0/+13.3pp (one and two net flipped
queries, not significant at these n); §4 tally aligned with table labels +
bucketing note; W8/W9 retiered A/B→B in table and PROVENANCE; "no mechanism
died on its own logic" rescoped to Tier-A transfer probes with sharding and
FTS-vise exceptions; "consumes M3 and only M3" corrected (episode-grain
status is an M2-family signal); "longitudinal study" dropped throughout;
"published candidates" → "eleven distilled from published work"; title
retitled to past-tense scoped claim; abstract biconditional → falsifiable
hypothesis; B0=0.208 reported wherever B1=0.188 appears (incumbent below
random); "does not occur" → "was not observed (0/12, rule-of-three UB ≈0.22)";
M2 double-edge (adoption artifact) disclosed in body AND abstract; self-test
G3 force-pass scope disclosed; disposition rules codified in
`docs/falsifiable-eval.md` (commit `3d1b4d5`: mandatory all-gate audit,
verdict/disposition split, monotonic downgrade-only) and cited; "audits the
discipline mandates" corrected to "now mandated, catches predate and
motivated the codification"; parked rows "pre-registered re-entry" →
"documented (panel records)"; kaos.db non-distribution disclosed in
Limitations and Appendix A.

## Minors (24)

Applied: hasp2026 bib title (no "HASP:" prefix on arXiv); "deployed" →
"publicly available" for SWE-Skills-Bench; p75 dual-sourcing note in W1;
86% composition figure added to W1; tally bucketing footnote. Remaining
minors are wording polish deferred without effect on claims.

## Deferred (recorded, not silently dropped)

- Larger-n replication of W9 retrieval benches under the multi-run protocol
  (carried over from paper 1's deferred list).
- Axis measurements on a second, non-KAOS telemetry corpus (the paper's own
  future-work item; would convert retrodiction into out-of-sample test).
- bench.py percentile fields (p75 emitted directly in results.json).
