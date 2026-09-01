# WMP Probe — VERDICT: REJECT (G1, G2)

**Lock:** `ISA.lock.json` sha256 `95b7f621…` (v1, pre-registered 2026-08-18
before any implementation existed). **Falsification self-test: PASSED**
(FULL := B0 correctly fails G1 — the harness can kill an inert wiki).
**Binding verdict: `REJECT: kill gate(s) failed: G1, G2`.** No retune-and-rerun.

## Numbers

| Gate | Result | Measured |
|---|---|---|
| G0 completion/sanity | PASS | all 6 cells × 3 runs complete; B0 means [1.0, 1.0] |
| G1 wiki lifts frontier | **FAIL** | pooled Δ(FULL−B0) = +0.0000 (floor +0.05), LB +0.0000 |
| G2 scrambled ≠ gain | **FAIL** | pooled Δ(FULL−L1) = +0.0000 (floor +0.03) |
| G3 cost ≤ 2× | PASS | **1.79×** proposer-context chars |

Every one of the 18 searches — all three arms, both benchmarks — reached
frontier best accuracy **1.000** within the 3-iteration budget.

## Honest interpretation

This is a **ceiling-saturated REJECT**: the pre-registered workload
(synthetic `text_classify` and `math_rag`) is solvable to 1.0 by the bare
proposer within budget, so no proposer-context mechanism could have shown a
lift here — the risk named verbatim in the lock's `honest_expected_outcome`
(#3). The verdict binds as registered. What it establishes:

1. **On these benchmarks, the wiki is pure cost:** +79% proposer context for
   zero measurable benefit. That much is real and portable.
2. **It does NOT establish** that proposer-side RCA wikis are worthless on
   workloads with headroom — WikiSkill's +23pt claim remains untested at
   fidelity. A retry requires a NEW lock with a harder, non-saturating
   workload and a ceiling gate (VOID if B0 ≥ 0.9), as candidate #18 (GAS)
   already pre-registers in its sketch.
3. **The deeper finding is about the instrument:** KAOS's mh benchmarks in
   their synthetic form cannot discriminate proposer mechanisms at all.
   Any future proposer-side probe must first fix the workload. (The same
   session's AutoSaddler gap test hit the identical ceiling.)

## Side effects already shipped (the probe's rent)

- mh_search per-problem timeout was divided by n_problems (60/32 = 1.9s
  killed every real `llm()` call) — fixed.
- Seed evaluation skipped `eval_subset` and scored seeds on a different
  problem set than candidates — fixed.
- Synthetic text_classify `get_test_set()` was silently empty — fixed.
- The wiki maintainer's first-ever RCA output correctly root-caused the
  timeout bug in the instrument evaluating it.
