# Closing: synthesis/abstraction consolidation is structurally infeasible for KAOS

This closes the arc. Two independent, oppositely-designed attempts were
each killed by a pre-registered, falsifiable, gate-first evaluation. The
conclusion is no longer "this implementation failed" — it is a
**structural impossibility result** under KAOS's deliberate constraints.

## The two attempts and their verdicts

| Attempt | Design | Pre-reg | Verdict | Hard-class acc |
|---|---|---|---|---|
| FULL (v2) | LLM synthesizes a prose abstraction per cluster | ISA.lock.v1/v2 (hash-locked, gate-first kill proven) | **REJECT** (G1–G5) | 0.000 |
| EXT | Non-LLM extractive verbatim token-union per cluster | PROBE_PREREG.md (gates frozen before code) | **DO NOT BUILD** (P2,P3) | 0.000 |

Both scored **exactly 0.000** on the hard (compositional + abstraction)
queries — identical to raw BM25 (B0) and non-LLM dedup (B1). Neither
beat the trivial baselines by a single query.

## Why — the FTS-without-embeddings vise (the actual finding)

A retrieved abstraction must satisfy **two** properties to help a
later, semantically-disconnected query:

1. **Token-faithful** — contain the exact searchable technical tokens,
   or FTS/BM25 cannot match them later.
2. **Bridge-able** — contain the query-side vocabulary, or the
   abstraction itself is never retrieved for the disconnected query.

- **LLM synthesis (FULL_v2)** produced bridging prose but **paraphrased
  the technical tokens away** → fails property 1 → not matchable.
  (Measured: insights retrieved ~50%, but content didn't entail the
  rule tokens.)
- **Extractive union (EXT)** is **perfectly token-faithful** (P1: 44/44
  verbatim) but contains **only source tokens, never the query's
  bridging words** → the insight is never retrieved for the
  disconnected query → fails property 2.

Satisfying both **simultaneously** requires either (a) semantic
retrieval (embeddings) to bridge the vocabulary gap, or (b) weight-based
generalization. **KAOS forbids both by deliberate design** (local-first,
SQLite-FTS-only, model-agnostic, no parameter updates). Therefore
retrieval-side synthesis/abstraction consolidation **cannot** deliver
compositional/abstraction recall in KAOS. This is consistent with — and
now a concrete demonstration of — the generalization ceiling argued in
arXiv:2604.27707 and the empirical null results in MemoryBench
(arXiv:2510.17281) and CTIM-Rover (arXiv:2505.23422).

## Does this problem need to be solved? — final answer

**No.** Not the broad version (proven ceiling, no demand), and not the
narrow retrieval-faithful version (now shown structurally infeasible
under KAOS's constraints by two oppositely-designed falsified attempts).
Spending more on it would be chasing a result the constraints
mathematically exclude. The honest, evidence-backed decision is to
**stop here**.

## What actually has value

Not the feature — the **apparatus**. KAOS now contains a reusable,
hash-locked, gate-first, grader-blind, anti-goalpost evaluation harness
that:

- was proven able to KILL before any feature code existed,
- survived two honest VOIDs (each fixed as harness plumbing with proof
  no gate moved),
- rendered a clean REJECT on the LLM design,
- rendered a clean DO NOT BUILD on the extractive design at ~1/10th the
  cost (proportionate ceremony — a cheap probe gated the expensive
  pre-registration, which was correctly never earned),
- and produced a *general structural conclusion*, not just a verdict.

That harness is the deliverable. It is exactly the machinery to kill the
next tempting-but-doomed memory idea cheaply and honestly.

## Disposition of the feature code

`kaos/dream/phases/synthesis.py` (both the LLM `run()` and
`extractive_consolidate()`) is **evaluated-and-rejected research code**,
retained only so the verdict is reproducible. It is **not wired into the
dream cycle, not exported, not shipped**. No `CHANGELOG`/release claim is
made. Per the rejected-feature rule, any future revisit needs a new
design and a brand-new pre-registration — never an edit to v1/v2/probe.
