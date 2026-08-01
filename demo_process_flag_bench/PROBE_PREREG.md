# Pre-registration — process-flag-auditor-probe (PFA, v1)

**Status at this commit: NO feature code exists.** This document and `ISA.lock.json`
are committed before `workload.py`, `auditor.py`, `arms.py`, or `run.py` are written.
The lock sha256 is pinned in `gates.py::KNOWN_LOCK_SHA256` in the same commit.

## Provenance

Distilled from **MANTA** (arXiv:2607.28527, Huang/Wang/Lai/Zhang/Cardie/Huang) by the
3-judge panel of 2026-08-01 — the 14th mechanism candidate since v0.7 and the first
with a fully clean admissibility profile (no embeddings, no training, no GPU anywhere
in the source mechanism). The panel demoted MANTA's auditor from *repair trigger*
(inadmissible on the paper's own numbers) to *diagnostic candidate generator*, rescoped
its input from relay packets / shared_log (organic n=0) to the event journal (organic
supply verified), and restricted the flag enum to the 6 supply-backed flags.

| MANTA component | PFA disposition |
|---|---|
| Trace Auditor over relay packets | RESCOPED to events + tool_calls journal |
| 11-flag taxonomy | RESTRICTED to 6 supply-backed flags (drops pre-registered in lock) |
| Auto-repair loop (1 mutation/run) | EXCLUDED — diagnostic-only |
| Topology planner/mutation | OUT OF SCOPE (parked, unlock floor on shared_log traffic) |
| Playbook | OUT OF SCOPE (parked behind this probe's verdict) |

## The claim being probed

The dream-cycle diagnosers are error-string-triggered. Verified on the live DB:
121 organic failure-class episodes, only 2 tool-call errors, **zero organic
diagnoses ever produced**. Error-free failures are structurally invisible today.
PFA claims an outcome-blind LLM reading only process evidence can flag them —
with separation that beats a three-rule deterministic detector (G2) and a
matched-rate random control (G5), at a sane flag rate (G3), with evidence
pointers that resolve (G4).

## Design honesty notes

1. **Organic-only, no synthetic substitution** (VOID#1 pattern respected). Floors:
   ≥40 failure-class + ≥80 completed eligible episodes; measured 116/234+ at design
   time, so floors should hold — but the lock, not the measurement, is binding.
2. **Outcome blindness is mechanically enforced.** The rendering function may not
   emit terminal events or status tokens; a leak-guard asserts this per prompt and
   its failure VOIDs the run. The judge is mechanical (agents.status), never seen
   by any arm.
3. **The most likely kill is G2** — the deterministic detector may capture the
   separation cheaply (zero-file-write is a strong give-up signal). That outcome
   would be a *useful* rejection: it would hand KAOS a three-rule detector instead
   of an LLM bill.
4. **LLM nondeterminism disclosed**: single binding run, raw responses persisted,
   no re-roll. Per the codified rules (`docs/falsifiable-eval.md` @ `3d1b4d5`),
   every gate is audited post-run — passes included — and the audit can only
   downgrade the disposition.
5. **No end-task claim.** ACCEPT licenses building the diagnostic surface
   (dream-cycle integration, `process_flags` additive table) — nothing more.
   Any future claim that flags *improve outcomes* is a separate probe under the
   frozen HASP bar.

No retune-and-rerun under any outcome.
