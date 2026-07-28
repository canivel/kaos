# Pre-registration — graphdiff-localizer-probe (GDL, v1)

**Status at this commit: NO feature code exists.** This document and `ISA.lock.json`
are committed BEFORE `workload.py`, `graphdiff.py`, `arms.py`, or any arm
implementation is written. The lock's sha256 is pinned in `gates.py::KNOWN_LOCK_SHA256`
in the same commit; the harness refuses to run on any edited lock.

## Provenance

Distilled from **EMG — Experience Memory Graph: One-Shot Error Correction for Agents**
(arXiv:2607.13884, Wenjun Wang et al., UESTC) by the 3-judge panel review of 2026-07-28
(13th mechanism candidate since v0.7). The paper's own evidence was judged REJECT-grade
(single runs, text games, expert-trajectory supervision KAOS lacks, unnamed embedding
model, no code). The distilled slice drops everything inadmissible:

| EMG component | GDL disposition |
|---|---|
| Query-embedding retrieval | REPLACED by BM25 over VERBATIM task texts |
| External expert trajectories (ETO) | REPLACED by own past successful episodes |
| FGW optimal-transport matching | DEFERRED — cheap earliest-divergence sequence diff only |
| LLM-verbalized insights + prompt injection | OUT OF SCOPE (that is EPR/TKC, both parked) |
| One-shot no-retry execution | OUT OF SCOPE — KAOS keeps retry-with-feedback |
| Deterministic trajectory→labeled-graph conversion | KEPT (normalization rules frozen in lock) |
| Contrastive fail-vs-success localization | KEPT — this is the probed claim |

## The claim being probed

The v0.8.3 critical-step localizer is **single-trajectory**: heuristic scoring over
error flags and decisive-tool hints, LLM fallback. Its blind spot is the **silent
wrong-branch failure** — no tool call errors; the agent takes a coherent wrong turn
and the episode just fails. GDL claims a deterministic diff against a paired past
success localizes the decisive step better, with zero LLM calls and zero embeddings.

## Design honesty notes

1. **Workload is harness-generated and says so.** Ground-truth divergence labels
   cannot exist organically (nobody annotates the decisive step of real failures).
   VOID#1 taught us not to smuggle synthetic data under an organic lock; this lock
   pre-registers generation up front. The price, stated now: **an ACCEPT here is an
   accept on constructed workload** — the verdict must carry that caveat verbatim,
   and organic replication is a separate future probe.
2. **G3 is the reality check and it is organic-only.** The constructed workload
   cannot test whether real KAOS trajectories normalize into non-degenerate graphs —
   that is measured on the live `kaos.db` (109 agents with ≥8 tool calls at design
   time; floor 30). The panel expects the mechanism most plausibly dies here
   (median node-reuse < 1.30), and the lock lets it die there even if G1/G2 pass.
3. **The judge is mechanical.** Correct = predicted `call_id` equals the planted
   ground-truth `call_id`, strict. No LLM anywhere in labeling; kappa recorded as
   1.0 by construction.
4. **The falsification self-test uses B1, not B0.** FULL := B1 must emit
   `[KILL: G1]` (the +10pp delta clause makes this structurally guaranteed to fire
   if the harness is sound); FULL := L1 must also KILL. B0 (random) additionally
   caps workload degeneracy via G0's `B0 ≤ 0.35` clause.

## What ships on each verdict

- **ACCEPT** → v0.10+ may implement GDL as a dream-cycle phase (9th diagnoser input,
  `method='graph-diff'` in `critical_steps`) behind a follow-up organic-validity plan.
- **REJECT via G3** → closes trajectory-graph mechanisms for KAOS's workload shape
  generally (EMG, and materially informs the parked ATG's graph substrate). High-value
  negative result.
- **REJECT via G1/G2/G4** → the contrastive-diff idea fails even on friendly workload;
  ledger entry, nothing ships.
- **VOID** → uninterpretable; fix the harness defect (documented, gates untouched)
  or accumulate organic data; no retune.

No retune-and-rerun under any outcome.
