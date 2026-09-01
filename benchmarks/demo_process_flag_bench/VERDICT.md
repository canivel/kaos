# Binding verdict — process-flag-auditor-probe v1 (PFA)

**Lock:** `ISA.lock.json` sha256 `4f820f7354a3421a6e763c57fb14430e1696071a75cbd01167b8e12a89c01f2a`,
pre-registered at commit `9b59ab9` (no feature code existed at that commit).
**Run date:** 2026-08-01, single binding run, 180 organic episodes (80 failure-class + 100
completed), 180/180 audits parsed, leak guard clean on all prompts.
**Falsification self-test:** ADMISSIBLE — FULL:=B0 killed G1+G3, FULL:=RAND killed G1+G5,
and the real auditor caught the planted duplicate-write in the capability smoke check.

## Verdict: `REJECT: kill gate(s) failed: G1, G2, G3, G5`

| Gate | Result | Detail |
|---|---|---|
| G0 coverage + floors + leak guard | PASS | parse 1.000; floors 80/100; leak guard clean |
| G1 outcome separation | **KILL** | FULL separation **−0.062** (floor +0.150) — flagged episodes were slightly *less* likely to be failures |
| G2 beats deterministic detector | **KILL** | FULL −0.062 vs DET **+0.653** — the three-rule detector wins by 71.5pp |
| G3 bidirectional non-degeneracy | **KILL** | FULL flag rate **0.900** (band [0.05, 0.60]) — flag inflation |
| G4 evidence integrity | PASS | 262/262 flag instances cite resolvable in-episode event ids |
| G5 beats random control | **KILL** | FULL −0.062 vs RAND +0.000 |

## Instrument audit (mandatory, all gates, per `docs/falsifiable-eval.md` @ `3d1b4d5`)

- **G3 kill is the mechanism, not plumbing.** Flag histogram: `insufficient_search_coverage`
  89, `missing_validator` 83, `give_up_shaped_candidate` 78 — the three judgment-call flags
  fired near-universally on heterogeneous organic traces (84% of which have 3–9 events),
  while the two concrete-evidence flags stayed rare (`evidence_lost` 5, `duplicate_state` 7).
  The auditor reads short traces as under-worked. This is MANTA's 0.21-precision floor
  reproduced and amplified off-template, exactly as the rigor judge predicted.
- **G1/G5 kills stand despite a small unflagged cell** (n=18; 50.0% failure rate vs 43.8%
  among flagged). The point estimate is noisy at that cell size, but with a 90% flag rate
  the mechanism is dead by G3 independently — no gate outcome hinges on the noisy cell.
- **G2 audit — the informative result of the probe.** DET (`zero file_writes OR any tool
  error OR zero tool_call_starts`) separates at **+65.3pp** (flagged 66.9% failure rate,
  n=118; unflagged **1.6%**, n=62). Rule decomposition: `zero_tool_calls` fired 111×,
  `zero_file_writes` 85×, `tool_error` 2×. DET is mechanically outcome-blind (it reads
  only event counts), but honesty requires the gloss: on 3–4-event traces these rules
  largely detect "the agent died before doing any work" — a legitimate process signal
  that is heavily correlated with early termination. It is triage, not root-cause diagnosis.
- **G4's perfect 262/262 is weak evidence, disclosed as such:** event ids are printed
  inline in the rendered trace, so citing them is mechanically easy. The gate measures
  citation integrity (a hallucinating auditor citing out-of-episode ids would fail);
  it does not measure flag correctness. Its pass changes nothing given four kills.
- **G0 audit:** 180/180 parses with one retry budget unused in most calls; leak-guard
  scrubbing verified on rendered prompts. No defect found.

**Disposition:** REJECT → nothing ships (monotonicity trivially satisfied). No retune;
no rerun. The lock's stated ~0.4 ACCEPT prior was optimistic; the G2-kill scenario the
lock named as "arguably the most likely kill" is what happened, at 14× the pre-registered
margin.

## What this probe bought (the useful rejection)

1. **The LLM-auditor idea is closed for KAOS's workload shape** at current trace
   granularity: an outcome-blind LLM over 3–9-event heterogeneous traces is a flag-inflation
   machine with negative separation. This extends the benchmark-gifts account: MANTA's
   auditor precision was propped up by templated benchmark traces (M-axis gift), and off-
   template it collapses — measured, not argued.
2. **A free replacement fell out.** The frozen DET baseline — three read-only SQL counts —
   separates failure-class episodes at +65.3pp with a 1.6% miss rate on its clean side.
   As dream-cycle *triage* ("this episode did no substantive work — look here first") it
   is strictly better than the probed mechanism at ~zero cost. Mechanizing it is a NEW
   candidate (deterministic did-no-work triage) requiring its own lock or invariant-gated
   infra classification per the HFP precedent — it does not ship on this verdict either.
3. **The discipline stack worked end-to-end on its first natively-governed run** (first
   probe born under the codified `3d1b4d5` audit rules): bidirectional G3 caught the
   degeneracy direction GDL's gate missed, the self-test was meaningful (a substituted
   arm could and did fail it before the fix), and the audit found no defective gate —
   the REJECT is clean.

**Ledger:** 14th candidate evaluated; PFA probed and REJECTED. REJECT is a successful
outcome under this discipline.
