# Binding verdict — graphdiff-localizer-probe v1 (GDL)

**Lock:** `ISA.lock.json` sha256 `979127576a1196db60deb78df19d64b49f78118ab8274d1a37d2841554e2232c`,
pre-registered at commit `50360ec` (no feature code existed at that commit).
**Run date:** 2026-07-28. **Falsification self-test:** ADMISSIBLE — FULL:=B1 emitted
`[KILL: G1]`, FULL:=L1 emitted `[KILL: G1, G2]` before the binding run.

## Verdict as computed by the frozen gates: `ACCEPT`

| Gate | Result | Detail |
|---|---|---|
| G0 workload sanity | PASS | coverage equal across arms; B0 (random) acc 0.208 ≤ 0.35; n=48 |
| G0f floors | PASS | localization n=48 ≥ 40; organic agents 109 ≥ 30 |
| G1 beats native localizer | PASS | FULL 1.000 vs B1 0.188 (Δ +0.812; floors 0.70 abs / +0.10 Δ) |
| G2 wrong-pair lesion | PASS | FULL 1.000 vs L1 0.000 (Δ +1.000; floor +0.10) |
| G3 organic non-degeneracy | PASS | median node-reuse 10.000 ≥ 1.30 (109 agents) |
| G4 pairing precision | PASS | BM25 same-family top-1 rate 1.000 ≥ 0.80 |

Per the pre-registered caveat, this ACCEPT is an accept **on harness-generated
workload**: G1/G2/G4 were measured on 48 constructed episodes built from the
mechanism's own operating assumptions (declared up front in the lock). B1's
0.188 confirms the claimed blind spot mechanically: `_heuristic_localize`
returns None on all 24 silent-wrong-branch episodes (no error step → nothing
to localize) and walks to the earliest decisive step — usually too early — on
the error-visible ones.

## Instrument-audit finding: the G3 pass is VACUOUS (defect disclosed, not retuned)

Post-run audit of the organic slice (required honesty, P12 precedent):

- The live `kaos.db` slice is dominated by **mh_search worker agents**: 1,405 of
  1,639 tool calls (86%) are `harness_run`, whose only argument (`problem_id`)
  is dropped by the frozen volatile scrub. Those trajectories normalize to **one
  repeated label** — 97 of 109 agents have < 3 distinct labels.
- G3's frozen predicate (`median reuse ≥ 1.30`) was written to catch **all-unique**
  degeneracy (chain of unique labels → nothing aligns). It is satisfied
  trivially by the opposite failure mode — **mono-label** degeneracy (one label
  repeated → everything aligns, nothing localizes) — which the predicate's
  author (this probe) did not anticipate. A mono-label sequence is exactly as
  undiffable as an all-unique one.
- **Post-hoc diagnostic (labeled as such; NOT a gate; thresholds never applied
  to the verdict):** among the 12 agents with ≥ 3 distinct labels — the only
  sub-population on which a divergence diff could operate — median reuse is
  **1.000**, p75 = 1.120, and **0/12 reach the 1.30 floor**. On the informative
  slice of KAOS's real workload, the EMG node-reuse premise fails, precisely
  where the 2026-07-28 panel predicted it would (~0.5 prior on a G3 kill).

Under the no-retune clause, the G3 predicate is not edited and the run is not
repeated: the verdict on file remains `ACCEPT` as computed. The defect is in
the instrument, and the discipline's remedy for a mis-specified gate is a new
lock, not a quiet threshold change.

## Disposition: DO-NOT-SHIP pending v2 probe

An ACCEPT whose only organic gate passed vacuously does not clear the shipping
bar ("no mechanism ships on hope"). Therefore:

1. **GDL does NOT enter `kaos/` on this verdict.** The bench-local implementation
   stays bench-local.
2. Any future shipping decision requires a **v2 lock** (new sha256, new
   pre-registration commit) whose G3 replacement must handle both degeneracy
   modes — e.g., median reuse ≥ 1.30 computed over agents with label diversity
   ≥ 5, plus a mono-label exclusion, thresholds frozen before the v2 run.
   Honest expected outcome of that gate on today's data: **KILL** (0/12).
3. What v1 established, durably: (a) the contrastive-diff algorithm and the
   BM25 verbatim-task-text pairing work as specified when their structural
   premise holds (G1/G2/G4, constructed workload); (b) the v0.8.3 localizer's
   silent-branch blind spot is real and measurable; (c) **KAOS's organic
   trajectories do not currently satisfy the node-reuse premise** — the same
   class of result as the FTS-vise finding, and the third time an
   external mechanism has died on organic-workload shape rather than on
   its own logic (HASP, VOID#1, now GDL).

**Net for the ledger:** 13th candidate. Verdict `ACCEPT` (constructed workload,
per lock) + instrument defect disclosed + **DO-NOT-SHIP** disposition. The
mechanism remains parked exactly where it was before the probe, now with
evidence instead of a prior.
