# Extractive-consolidation cheap probe — PRE-COMMITTED kill threshold

**Committed BEFORE any EXT code exists** (verifiable: this commit's tree
has no `extractive` consolidation function). Same gate-first discipline
as the rejected feature, scaled to a 30-line deterministic candidate
with a documented failure prior. A full ISA.lock.v3 hash-locked
pre-registration is **not** justified until this cheap probe is cleared
— that decision is itself a true-validation principle (proportionate
ceremony), not a shortcut.

## Candidate

Non-LLM extractive keyphrase-union consolidation: per Hebbian cluster
(same `_components`, same weight threshold as the rejected design),
compute the cluster-wide discriminative token union (PMI / df-based:
tokens that recur across cluster members but are not corpus-generic),
write them as ONE `insight` memory, index it. No LLM in the path.

## Pre-committed gates (frozen here, before EXT exists)

Evaluated on the EXISTING frozen organic world (`seed=20260516`,
540 incidents → 1620 memories), hard classes only
(`compositional_multihop` ∪ `abstraction_only`, in-distribution),
reusing the existing blind judge + arms machinery.

- **P1 — token-faithfulness (mechanical, zero tolerance):** every token
  in every EXT insight MUST be a verbatim (lowercased) substring of some
  source memory in its cluster. <100% → the candidate is not even the
  thing claimed → DO NOT BUILD.
- **P2 — beats the cheap baselines:** `acc(EXT) − max(acc(B0), acc(B1))`
  on hard in-dist **≥ +0.05**.
- **P3 — beats the rejected design:** `acc(EXT) − acc(FULL_v2)` **≥ +0.05**,
  where FULL_v2 is the just-rejected LLM synthesis replayed verbatim
  from its hash-locked `.synth_cache/cache.json` (it cannot be
  re-weakened).

## Verdict rule

- Any of P1/P2/P3 fails → **DO NOT BUILD.** Report faithfully. No
  retune-and-rerun. The candidate is dead; revisiting needs a new
  design and a new pre-registration.
- All pass → escalate to a full `ISA.lock.v3.json` hash-locked
  pre-registration with the complete kill-gate suite (G1/G2/G4/G5 reused
  + G6 "beat FULL_v2 by ≥0.10" + G7 "mechanical verbatim-token check"),
  per the research recommendation. The probe passing is NECESSARY, not
  SUFFICIENT — it only earns the right to the expensive evaluation.

## Honest prior

Per MemoryBench (arXiv:2510.17281) and CTIM-Rover (arXiv:2505.23422),
and given EXT's edge may be a synthetic-world artifact (BM25 over the
K=25 window may already retrieve token-sufficient sets on real
workloads), the expected outcome is **P2/P3 fail → DO NOT BUILD**. That
is a successful, cheap, honest result — the whole point of probing
before pre-registering.
