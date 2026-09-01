# Critical-step localizer benchmark (Track B2, v0.8.3)

Does the localizer find the **earliest decisive** error, not just the
visible one?

## Setup

Five synthetic agent trajectories. Each plants the decisive mistake N
steps *before* the visible error and records the ground-truth trace
index a human would point at:

- `bad_intent_up_front` — wrong plan committed first, fails 3 tools later
- `immediate_error` — no prior decision; the error is itself critical
- `wrong_write_midway` — decisive bad write between innocent reads
- `long_gap_before_failure` — decisive intent, long innocent stretch, fail
- `vote_then_fail` — a vote locks direction; action fails 2 steps later

Heuristic path only — **no LLM** is consulted (these shapes are common
enough that deterministic scoring handles them for free).

## Reproducing

```bash
uv run python demo_critical_step_bench/run.py
```

## Latest measured result

| Scenario | ground truth | localized | within ±1 |
|---|:-:|:-:|:-:|
| bad_intent_up_front | 0 | 0 | Y |
| immediate_error | 0 | 0 | Y |
| wrong_write_midway | 2 | 2 | Y |
| long_gap_before_failure | 0 | 0 | Y |
| vote_then_fail | 0 | 0 | Y |

**5/5 within ±1 step of ground truth.** Acceptance gate: ≥ 4/5.

The long-gap scenario gets the highest confidence (0.90) because a bug
that festers six innocent steps is the clearest "earliest critical"
signal — exactly the case the visible error misleads you on.

Raw JSON: [results.json](results.json)
