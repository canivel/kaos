# WMP — Wiki-Maintained Proposer (pre-registration)

**Candidate #17**, distilled from WikiSkill (arXiv:2608.27454, Google Research);
paper-eval logged as experiment `wikiskill-paper-eval` (exp:4), record
`tb1:98befd9a…` in Attraktor. **Lock:** `ISA.lock.json` (sha256 in `gates.py`),
committed BEFORE any implementation code existed.

## Thesis under test

A maintained failure-pattern wiki in the **mh_search proposer's** context lifts
the search frontier — and the lift survives the two controls the paper never
ran: a **word-scrambled wiki** (padding placebo) and a **cost gate** (≤2×
proposer context).

Proposer-side only, per the paper's own ablation (proposer access +23.3pts,
inference-side access −2.8pts). Nothing touches harness/inference context.

## Arms (18 searches: 3 replicates × 2 benchmarks × 3 arms)

| Arm | Proposer context |
|---|---|
| B0 | current archive digest + frontier summary |
| FULL | B0 + `## Failure-pattern wiki` (1 maintainer LLM call/iteration, ≤2,000 chars) |
| L1 | FULL with the wiki word-scrambled (same tokens, destroyed instruction) |

Budget frozen: iterations=3, candidates=2, eval_subset=10, max_parallel=2,
benchmarks `text_classify` + `math_rag` (synthetic, mechanical scoring — the
only KAOS surfaces with dense M2 signal). Metric: frontier best accuracy.

## Gates

- **G0** (VOID): all 18 searches complete; B0 mean ≥ 0.30 somewhere.
- **G1** (KILL): pooled Δ(FULL−B0) ≥ +0.05 AND one-sided 90% bootstrap LB > 0.
- **G2** (KILL): Δ(FULL−L1) ≥ +0.03 — scrambled must not reproduce the gain.
- **G3** (KILL): FULL proposer-context chars ≤ 2.0× B0.

**Falsification self-test:** FULL := B0 must fail G1, else the harness is
inadmissible. Verdict: ACCEPT iff G1∧G2∧G3; any kill REJECTS; no retune-and-rerun.

**Consequences:** ACCEPT → maintainer ships as an mh_search option + Attraktor
record upgrades. REJECT via G2 → closes proposer-side synthesis the way the
FTS-vise closed retrieval-side synthesis. Honest prior: ~0.35 ACCEPT.
