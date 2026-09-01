# Action-Realization Probe — Binding Verdict (v0.9 PR-4)

**Lock:** `ISA.lock.json` sha256 `3ca89983c5914d1f1f77377cf124bac223dba4bc391a59d5e329e671b79187e2` (v1, pre-registered before any probe code existed).
**Falsification self-test:** ADMISSIBLE — `FULL := B1` emits `[KILL: G1]` as required.
**Binding verdict (this run):** **`VOID#1 (insufficient organic sample)`**

```
n_action = 2     (need >= 200)
n_control = 0    (need >= 200)
n_sanity = 500   (need >= 50)   OK
```

## What happened

`workload.sample_workload(kaos.db)` returned 2 organic action-class incidents and 0 organic non-action incidents from the local KAOS database. The lock's workload invariants require n ≥ 200 in each non-sanity slice, with **synthetic substitution explicitly forbidden** (`synthetic_fallback: NONE`). With organic n below the floor, the harness emitted `VOID#1` per the pre-registered rule and did NOT compute a feature verdict.

## Why this is a successful PR-4 outcome

Per the v0.9 spec ([docs/roadmap/v0.9.md](../docs/roadmap/v0.9.md) §Sizing and honest probability):

> PR-4 *completion*: 0.70 (probe runs to verdict)
> PR-4 *probe PASS*: ~0.45 (whether the mechanism passes is a separate event; **the probe-as-shipped is what counts for v0.9, not the verdict**)

And explicitly anticipated in §Risks:

> PR-4 may VOID (e.g., the action-class incident pool is too small or unbalanced). Per discipline, VOID permits harness-plumbing fixes; gates stay byte-frozen.

The probe shipped. The verdict was determined by gates frozen at lock time. The honest result is reported here. No goalposts moved.

## What VOID#1 does NOT permit

- Editing thresholds in `kill_gates` (would change the lock hash → harness refuses to run).
- Switching the workload source to synthetic incidents (`synthetic_fallback: NONE` in the lock).
- Re-running with a different label classifier and treating the new verdict as binding (would require a new lock + new pre-registration commit).

## What VOID#1 DOES permit

- Collecting more organic data on a live KAOS deployment and re-running the same probe with the same lock.
- Adding a NEW pre-registered lock (v2) that explicitly defines a synthetic-fallback workload — but that v2 lock's verdict would NOT supersede this v1 VOID#1; it would simply be a different probe.

## Implications for v0.10

The mechanism (Action Realization Layer) **did not earn a v0.10 milestone via PR-4**. The candidate is not REJECTED; it is **un-evaluated under the binding probe**. If sufficient organic action-class incidents accumulate in a future KAOS deployment, re-running this same probe at this same lock hash would produce a binding verdict. Until then, the mechanism stays parked alongside Life-Harness's other un-evaluated slices.

## Honest accounting alongside the other v0.9 evaluations

| Idea | Evaluated outcome | Mechanism shipped? |
|---|---|---|
| SAGE | REJECTED (2/10) | No |
| synthesis-as-consolidation (LLM) | REJECT via probe | No |
| synthesis-as-consolidation (extractive) | DO NOT BUILD (structural impossibility) | No |
| AutoResearchClaw | Mostly orthogonal (3/10) + 1 parked | No |
| HASP | REVIEWED-REJECTED (0.78 conf to fail) | No |
| **Action Realization (this probe)** | **VOID#1 — un-evaluated** | **No** |

Six candidates evaluated this v0.9 cycle. Zero mechanisms shipped. The discipline is the deliverable.
