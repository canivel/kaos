# PR-4 Probe Pre-Registration — Action Realization Layer (Life-Harness narrow slice)

**Status:** PRE-REGISTERED. Probe code, runner, arms, judge, and any
mechanism implementation are committed in a SUBSEQUENT commit. The lock
in this commit is the binding contract; the harness will refuse to run
against any lock whose sha256 is not in the pre-registered allow-list.

**Lock file:** `ISA.lock.json`
**Lock sha256 (v1, pre-registration):** `3ca89983c5914d1f1f77377cf124bac223dba4bc391a59d5e329e671b79187e2`
**Reference spec:** [`docs/roadmap/v0.9.md`](../docs/roadmap/v0.9.md) §"PR-4 — action-realization-probe"
**Source paper:** Life-Harness, arXiv:2605.22166
**Mechanism status:** **PROBE ONLY.** v0.9 SHIPS NO MECHANISM. Probe verdict gates the v0.10 decision.

## What is being tested

A pre-execution Action Realization Layer wrapping the tool registry — deterministic validation / canonicalization / blocking of malformed tool calls **before** they reach the tool boundary. KAOS v0.8.3 already has a *post-mortem* critical-step localizer (after failure); this would be a *pre-failure* intervention. That timing difference is the one place the v0.8.3 native baseline cannot trivially absorb the proposed mechanism.

## Kill gates (byte-frozen at lock v1)

| Gate | Predicate | Threshold |
|---|---|---|
| **G1** | FULL − B1 (v0.8.3 native) on action-class slice | ≥ +4.0 pp, bootstrap95 lo > 0, n ≥ 200 |
| **G2** | (FULL − L1 never-fire) AND (FULL − L2 random-fire) | ≥ +3.0 pp AND ≥ +2.0 pp |
| **G3** | FULL − B1 on non-action control slice | ≥ −1.0 pp (no regression) |
| **G4** | p95 inline overhead per tool call | < 500 µs |

ANY single kill-gate failure → REJECT. ACCEPT iff G1 ∧ G2 ∧ G3 ∧ G4.

## Sanity gate (non-kill)

**G0** — every arm achieves ≥ 0.95 completion-rate on a frozen sanity slice of trivially-valid tool calls. VOID on fail.

## Verdict rule

`VOID` if G0 fails OR judge-audit kappa < 0.85 OR workload n minima unmet.
`ACCEPT` iff every kill-gate passes.
`REJECT` if any kill-gate fails.
**No retune-and-rerun. No threshold edits without a new pre-registration commit + a new sha256 in `KNOWN_LOCK_SHA256`.**

## Workload (organic only — synthetic fallback explicitly forbidden under this lock)

- **Action-class slice (n ≥ 200):** failures classified action-class by v0.8.3 native (failure_fingerprints.taxonomy_class = 'action' or critical_steps rationale matching action-class regex).
- **Control slice (n ≥ 200):** failures classified non-action.
- **Sanity slice:** frozen set of trivially-valid tool calls (well-formed args, known tool, no schema violation).

If organic n_action < 200 OR organic n_control < 200 → **VOID#1 (insufficient organic sample)**. No synthetic substitution.

## Honest expected outcome

REJECT or VOID at ~0.55 confidence per the SWE-Skills-Bench negative prior (39/49 deployed skills produced zero gain) and the strong v0.8.3 native baseline (localizer + diagnoser + retry-with-feedback already absorbs most of the claimed lift).

**REJECT or VOID is a successful run.** It joins SAGE, synthesis-as-consolidation, AutoResearchClaw, HASP as evaluated-and-rejected, freeing v0.10 to ship on real evidence.

## Why this commit ships the lock and nothing else

Gate-first invariant: feature code authored BEFORE the gates can always be tuned to pass them. By committing the lock and pre-registration first — and adding the hash to the harness's allow-list only at this commit — any later run is bound by gates the author could not yet see results for. This is the same discipline that produced 4 of 5 REJECTs in v0.9's pre-PR research arc.
