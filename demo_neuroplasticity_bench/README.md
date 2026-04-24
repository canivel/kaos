# demo_neuroplasticity_bench — Real measurement of plasticity gains

An honest, deterministic benchmark that measures the actual accuracy
delta between bm25 default search and plasticity-weighted search.

**No pre-engineered outcomes. No planted winners.** The scenario sets up
a query set with deliberately ambiguous FTS matches (each query has one
ground-truth correct skill and 2–3 vocabulary distractors), then runs
two identical training loops — one bm25, one weighted — and measures
per-query accuracy at the end.

## The setup

- **10 queries** covering text / time-series / images / audio / structured
  data. Each query has one *correct* skill and several plausible
  distractors that share enough vocabulary that bm25 alone can't reliably
  pick the right one.
- **20 skills** total: 10 correct, 10 distractors. All seeded with
  identical zero usage.
- **Training loop**: 80 episodes. For each episode:
    1. Pick a query from the set (round-robin).
    2. Retrieve top-1 skill via the chosen rank mode (bm25 or weighted).
    3. Compare against ground truth; record outcome.
    4. (Weighted run only: outcome now feeds plasticity for future searches.)
- **Measurement**: after training, for each query pick the top-1 skill one
  final time and check if it matches ground truth. Accuracy =
  correct_queries / 10.

The **bm25** run never uses plasticity — it records outcomes but always
searches with `rank="bm25"`. This is the control group: whatever bm25
alone gets is the baseline.

The **weighted** run uses `rank="weighted"` during training (so later
searches benefit from earlier outcomes) and at final measurement.

Same seed data, same queries, same training protocol. The only variable
is whether the rank mode is feedback-sensitive.

## Reproduce

```bash
cd demo_neuroplasticity_bench
uv run python run.py
```

Output: a JSON report on stdout and a markdown summary written to
`results.md` in this folder. Both are committed alongside the code so
you can verify the numbers match what the README claims.

## What "gain" means here

- **Absolute gain**: weighted accuracy − bm25 accuracy (percentage points)
- **Relative gain**: (weighted − bm25) / bm25 (percent improvement)
- **Break-even point**: how many episodes before weighted surpasses bm25

The benchmark prints all three and tracks the accuracy curve across
training so you can see exactly when plasticity starts winning.
