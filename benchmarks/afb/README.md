# Agent Forensics Bench (AFB) v1.0

*Can the framework tell you what an agent did, put it back, find where it went
wrong, and reproduce it — with evidence?* Six tests, synthetic seed-determined
sessions, pre-registered gates. Spec: [`spec.md`](spec.md). Run it on another
framework: [`compat/run_external.md`](compat/run_external.md).

```bash
uv run python benchmarks/afb/run_afb.py            # -> results/kaos_v<version>.json, exit 0 only on ACCEPT
```

## KAOS 2.0.2 self-run — verdict: **REJECT** (fault localization)

Pre-registered lock `preregistration.json`
sha256 `018a9fff8831d9795d7aef0285742d2eadb3c3fa02ad73a3879c360dd303c35c`,
12 agents × 24 steps, seed 20260902. Elapsed 2.3 s.

| Test | Result | Gate | |
|---|---|---|---|
| Checkpoint fidelity | 12/12 agents byte-exact after restore (**1.00**) | == 1.0 | pass |
| Journal completeness | 288/288 tool calls with row + start + end events (**1.00**) | == 1.0 | pass |
| Cross-agent isolation | **0 leaks** / 2 checks (file read raises; scoped memory search empty) | 0 | pass |
| Fault localization | median **9.5** entries inspected, 0/12 exact hits (per agent: 9 8 10 7 11 8 11 7 11 10 8 11) | median ≤ 5 | **fail** |
| Cold-start replay | 12/12 file trees reproduced from the journal (**1.00**), two replays identical | == 1.0 | pass |
| Mid-task recovery | overhead **0.083** (2 of 24 steps redone), 12/12 recovered to final state | < 0.20 | pass |

**Why it failed, honestly.** The critical-step localizer's heuristic picks the
*earliest* decisive (write-like) step before the first visible error. AFB
sessions begin with a few `fs_write` calls that seed the agent's files — a
normal shape for a real session — so the pointer lands on step 0 every time
and the auditor walks 7–11 entries to reach the planted culprit. The
heuristic assumes "first write = root cause", which is wrong whenever a
session starts by setting things up. That is a real finding about the
localizer, not about the bench, and per the no-retune rule the generator was
not changed to make it pass. The fix (e.g. weighting decisive steps by
recency to the error, or treating setup writes that are never read as
non-decisive) must be pre-registered against this same lock and re-run.

The five binary forensics properties — byte-exact checkpoints, a complete
journal, enforced isolation, deterministic replay from the journal, cheap
recovery — all hold at 100 %.

Result file: [`results/kaos_v2.0.2.json`](results/kaos_v2.0.2.json). Logged
in the experiments journal as `afb-v1-self` (`kaos experiment list`).

## Files

| File | Purpose |
|---|---|
| `preregistration.json` | Hypothesis, generator parameters, tests, gates. Hash-locked in `run_afb.py`. |
| `generate_session.py` | Seed-deterministic sessions with a known culprit and a known visible error. |
| `adapter.py` | `ForensicsAdapter` protocol + `KaosAdapter` reference implementation. |
| `run_afb.py` | The six tests; writes a result JSON with a top-level `verdict`. |
| `compat/run_external.md` | How to score another framework with the same lock. |
| `../check_gates.py` | Used by the `kaos-eval` GitHub Action: fails on REJECT/VOID. |
