# Binding verdict: synthesis-as-consolidation is REJECTED

**Verdict:** `REJECT: kill gate(s) failed: G1, G2, G3, G4, G5`
**Run:** binding run #3 (G0 sanity floor PASSED → the harness is valid and
this is a real feature verdict, not a VOID)
**Lock:** ISA.lock.v2 `sha256 09310794aad969646804ea56e1d05489c24480c57c1970b70b344ec61ef7e684` (byte-frozen; gates/thresholds/verdict_rule never changed across the whole evaluation)

## What happened

| arm | hard acc (in-dist) | verbatim | synth-in-topK (helped) |
|---|---|---|---|
| B0 / B1 / B2 / B3 | 0.000 | 1.000 | — |
| L1 / L2 / L3 | 0.000 | 1.000 | — |
| **FULL** | **0.000** | 1.000 | **0.50** |

- **G0 PASS** — all 8 arms 1.000 verbatim recall. The pipeline is sound; the verdict is a real feature signal.
- **FULL answered 0 of 440 compositional/abstraction queries.** Synthesis ran (4 organic cluster insights), the insights *were* retrieved (~50% of helped queries), and the mechanism worked end-to-end — but the synthesized content never entailed a domain's full canonical rule-token set in a retrievable form.
- **All five kill gates failed.** G1: FULL (0.000) does not beat baselines (0.000) by ≥0.10. The feature delivered **zero lift** on the hard queries it exists to help.

## Why it failed (honest root cause)

The cluster-blind `claude` synthesizer, given ~45 incident memories each
carrying only 1–2 scattered rule tokens plus distractors and a
temporal-contradiction stream, produced **fluent prose abstractions that
paraphrased the latent rule away from its exact technical terms** — e.g.
*"a leading signal from a shared downstream dependency (typically
ledgerdb)"* instead of the searchable token set
`ledgerdb p99latency deployfreeze inactive`. The frozen `_has_all`
decisive predicate requires the exact rule tokens co-located in one
retrieved item. Raw episodes provably cannot satisfy it (world
invariant); the synthesized insight could have, and didn't.

This is a **genuine negative result**, consistent with the
pre-registered base-rate disclosure (MemoryBench arXiv:2510.17281;
CTIM-Rover arXiv:2505.23422) that this feature most likely fails. It is
a *successful* falsifiable evaluation, not a failed one.

## Integrity statement (the part that matters most)

- The result was **not rigged to fail**: the synthesizer used the real
  Claude CLI, synthesis genuinely ran (4 insights), and those insights
  were retrieved for ~50% of the queries they should help. The mechanism
  was fully exercised.
- The result was **not rigged to pass**: the strict exact-token
  `_has_all` predicate was frozen at pre-registration. The LLM's
  paraphrasing means it fails that predicate. Loosening it post-hoc to a
  "semantic match" to rescue the feature is the textbook goalpost-move
  the entire lock/hash/pre-registration architecture exists to prevent —
  so it was **not done**.
- Two prior runs were **VOID** (G0 sanity floor failed: Windows
  subprocess defect; free-text single-record retrieval below the floor).
  VOID explicitly permits harness-plumbing fixes; every fix was
  committed with proof that gates/thresholds/verdict/qids/seed remained
  byte-frozen. No gate was ever moved.

## Honest nuance (stated, not relitigated)

The verdict is partly a function of the strict exact-substring token
predicate: an LLM that paraphrases is penalised even if its abstraction
is *semantically* correct. That is a deliberate, defensible
pre-registration choice — a synthesized memory is only useful for
*retrieval* if it surfaces the searchable terms; a beautifully-worded
insight that drops the technical tokens is genuinely less findable in
production. One may disagree with the predicate; one may **not** change
it after seeing the result. A different predicate is a *different
experiment* requiring a new pre-registration commit — per the lock,
"a rejected feature requires a new design, a new lock file, and a new
pre-registration commit. There is no retune-and-rerun."

## Decision

**synthesis-as-consolidation is REJECTED for KAOS v0.9.** It is not
shipped. No retune-and-rerun. If revisited, it requires a fresh design
(e.g., a synthesizer constrained to preserve source technical tokens, or
a hybrid extract-then-abstract writer) and a brand-new pre-registered
evaluation — not an edit to this one.

The evaluation harness itself worked: it was provably able to kill
(falsification self-test), it survived two honest VOIDs, and it rendered
a clear, falsifiable REJECT on a complex, organic, non-gameable problem.
That is the deliverable that has value here — not the feature.
