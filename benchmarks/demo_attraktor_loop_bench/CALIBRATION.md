# Instrument Calibration — 2026-08-16 (NON-BINDING)

**What ran:** `calibration.py` — 900 episodes (300 × 3 scenarios) through the
REAL pipeline: `ClaudeCodeRunner` + `BenchHooks` (probe arms) + `pull()` ledger
+ the frozen gates, in throwaway sandbox workspaces with scripted ground truth.
The flagship bench.db was untouched; these episodes can never feed the binding
verdict (the lock forbids harness-generated workload).

**Why it exists:** the falsification self-test proves the harness can kill an
inert treatment *statically*. Calibration proves the whole live path —
fingerprint → pull → arm assignment → injection → runner outcome → ledger →
gates — detects a true effect, refuses a null, and kills a placebo.

## Results (all three as required)

| Scenario (ground truth) | Expected | Got | Deciding evidence |
|---|---|---|---|
| **effect** — success requires the un-scrambled secret | ACCEPT | ACCEPT | G1 LB **+0.466** (p_on 0.911 vs p_off 0.379, n=135/132); scrambled ≈ off (G4 LB −0.072) |
| **null** — outcomes independent of injection | REJECT | REJECT: G1 | G1 LB **−0.088** (0.594 vs 0.606) — a lucky point-diff can't sneak through |
| **placebo** — ANY injected tokens "help", scrambled included | REJECT | REJECT: G4 | G1 *passed* (+0.462) but G4 LB **+0.408** (p_scrambled 0.920 vs p_off 0.400) — killed |

Shared checks across all runs: arm shares landed on the locked 45/45/10 within
tolerance (deterministic hash, 300 episodes); pull latency p95 = **0.6 ms**
(budget 150 ms); match-rate 1.0 on a purpose-matched brain; falsification
self-test (ON := OFF must fail G1) passed in every scenario.

**The load-bearing row is `placebo`:** a G1-only harness would have ACCEPTed a
pure prompt-padding artifact with LB +0.46. G4 is what makes the instrument
falsify its own favorite outcome.

**Status:** the instrument is admissible. The binding verdict still requires
ORGANIC flagship episodes per the lock — this document is evidence about the
measuring device, never about the loop.
