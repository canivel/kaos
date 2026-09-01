# Critical-step localizer benchmark

Five planted-bug trajectories where the decisive mistake is N steps before the visible error. Heuristic path only (no LLM).

| Scenario | ground truth | localized | within +/-1 |
|---|:-:|:-:|:-:|
| bad_intent_up_front | 0 | 0 | Y |
| immediate_error | 0 | 0 | Y |
| wrong_write_midway | 2 | 2 | Y |
| long_gap_before_failure | 0 | 0 | Y |
| vote_then_fail | 0 | 0 | Y |

**5/5 within +/-1 step.** Acceptance gate: >= 4/5.

Raw JSON: [results.json](results.json)
