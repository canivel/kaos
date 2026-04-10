# Your New Model Regressed by 8%. KAOS Caught It Before You Shipped.

*MLOps · April 16, 2026 · 7 min read*

*Automated benchmark regression detection: 5 benchmarks, 1 model update, 12 minutes. The deploy that would have broken production was blocked before it left CI.*

---

Model updates are invisible. You swap `claude-sonnet-4-5` for `claude-sonnet-4-6` and assume it's better. It usually is — except on the one benchmark that matters most to your users.

Most teams find out from user reports. KAOS catches it in CI, in 12 minutes, before the deploy leaves the gate.

---

![KAOS regression guard demo — 5 benchmarks, code_review regresses 8.4%, CI gate blocks deploy, Meta-Harness re-optimizes](https://canivel.github.io/kaos/docs/demos/kaos_uc_regression.gif)

*Regression suite runs on model swap. code_review drops 8.4%. CI gate triggers. Meta-Harness re-optimizes in 5 iterations. Deploy approved Monday.*

---

## The Problem With Implicit Model Trust

Models change silently. A new model version has different RLHF fine-tuning, different instruction following characteristics, different strengths and weaknesses across task types. Your prompt harness was optimized for the old model's behavior. It may or may not transfer.

The dangerous assumption: "the new model is better, so our product is automatically better." Sometimes that's true. Sometimes the new model is better overall but regresses on your specific task because your harness exploited quirks of the old model's output format.

Most teams find this regression from user reports, support tickets, or a 3am alert. KAOS finds it in CI.

---

## The Regression Suite — 5 Benchmarks

Before any model swap reaches production, run all benchmarks against the new model and diff vs the baseline checkpoint taken with the old model:

```yaml
# .github/workflows/model-regression.yml
- name: Run regression suite
  run: |
    kaos spawn regression-check-v46 \
      --model claude-sonnet-4-6 \
      --baseline-checkpoint baseline-v45

    kaos run regression-check-v46 \
      "run_benchmarks text_classify code_review sentiment math_qa tool_calling"

    kaos --json query "
      SELECT benchmark, delta_pct
      FROM regression_results
      WHERE run_id = 'regression-check-v46'
        AND delta_pct < -5.0" \
    | jq -e '. | length == 0' \
    || (echo "REGRESSION DETECTED — deploy blocked" && exit 1)
```

If any benchmark regresses more than 5%, CI fails. The deploy is blocked.

---

## Results — Two Regressions Found

The regression suite runs in 12 minutes:

| Benchmark | v4-5 Score | v4-6 Score | Delta | Status |
|---|---|---|---|---|
| text_classify | 0.87 | 0.87 | 0.0% | NO CHANGE |
| tool_calling | 0.88 | **0.91** | **+3.4%** | IMPROVED |
| math_qa | 0.74 | **0.76** | **+2.7%** | IMPROVED |
| sentiment | 0.83 | 0.81 | -2.4% | REGRESSION |
| code_review | 0.83 | **0.76** | **-8.4%** | **CRITICAL REGRESSION** |

Two regressions. `sentiment` is within tolerable range (-2.4%). `code_review` is not — 8.4% is a CRITICAL regression on a benchmark that directly maps to user-visible quality.

The model improves overall. But it regresses on the task that matters most to this team's product. Shipping would have been a mistake.

---

## Deep Dive — Why Code Review Regressed

```
kaos diff baseline-v45 regression-check-v46 /results/code_review_failures.md

## code_review regression analysis: 0.83 → 0.76 (-8.4%)

### Failure pattern
New model struggles to distinguish BLOCKER from IMPORTANT.

v4-5: BLOCKER/IMPORTANT confusion rate: 14%
v4-6: BLOCKER/IMPORTANT confusion rate: 31%

### Example failure (new model)
Input: "SQL query is vulnerable to injection — must fix before merge"
Expected: BLOCKER
Got:      IMPORTANT (new model downgrades severity)

### Root cause
The harness was optimized for v4-5's instruction-following pattern.
v4-5 responds strongly to "must fix" keywords → BLOCKER.
v4-6 applies more nuanced severity reasoning → IMPORTANT.

This is not a model deficiency — it's a harness mismatch.
The two-step_attr_merged strategy from the original search
may transfer better to v4-6's reasoning style.
```

The harness optimized for v4-5 doesn't transfer perfectly to v4-6. This is expected — different RLHF tuning produces different instruction-following behavior. The fix isn't a model rollback; it's a harness re-optimization.

---

## Deploy Blocked — The CI Gate

```json
[{"benchmark": "code_review",
  "baseline_score": 0.83,
  "new_score": 0.76,
  "delta_pct": -8.4}]

# 1 critical regression found
# CI gate: FAILED
# Deploy: BLOCKED
```

One row returned. One critical regression. CI exits non-zero. The deploy is blocked. The team gets a notification with the regression report and the exact benchmark that failed.

**The 5% threshold is configurable.** Set it tighter for safety-critical tasks, looser for tasks where minor fluctuation is acceptable. The important thing is that it's automatic — no human has to remember to check before deploying.

---

## Remediation — Re-run Meta-Harness (5 Iterations)

The regression report already identified the fix: re-optimize the `code_review` harness for v4-6. Quick targeted search:

```bash
kaos mh search \
  -b code_review \
  --model claude-sonnet-4-6 \
  -n 5 \
  --seed-from baseline-v45

# [mh-search] Loading from baseline-v45...
# [mh-search] Seed: two_step_attr_merged  acc=0.76 (on v4-6, was 0.83 on v4-5)
# [mh-search] Starting search from known frontier
```

```
[iter 1/5]  two_step_attr_merged_v46  acc=0.78  +0.02  IMPROVED
[iter 2/5]  attr_merged_explicit      acc=0.81  +0.03  IMPROVED
[iter 3/5]  attr_merged_explicit_v2   acc=0.81  —      no improvement
[iter 4/5]  blocker_severity_v46      acc=0.83  +0.02  IMPROVED  ← baseline restored
[iter 5/5]  blocker_severity_merged   acc=0.83  —      no further gain

Best: blocker_severity_v46  acc=0.83  (baseline fully restored)
```

5 iterations. 0.83 restored on v4-6. The fix: the two-step approach still works, but needs an explicit severity rubric calibrated to v4-6's more nuanced reasoning. The harness update is small — one section of the system prompt.

---

## The Loop

This is the full MLOps loop that KAOS makes systematic:

1. **Model update** — swap to new model version in config
2. **Regression suite** — run all 5 benchmarks, diff vs baseline checkpoint
3. **CI gate** — block deploy if any benchmark regresses more than threshold
4. **Re-optimize harness** — targeted Meta-Harness search on the regressed benchmarks
5. **Update baseline checkpoint** — the new harness + new model becomes the new baseline
6. **Deploy approved** — ship with confidence

No surprises. No user reports. No 3am incidents. Every model update goes through the same gate, and the gate is automated.

---

The 8% regression would have shipped on a Friday. Users would have filed support tickets over the weekend about code reviews suddenly downgrading severity. The on-call engineer would have spent Sunday debugging a harness mismatch.

It didn't ship. The harness was updated, tested against v4-6, and deployed Monday morning with the regression eliminated. That's what a regression guard is for.

*KAOS is MIT-licensed and runs entirely locally. No data leaves your machine.*

*GitHub: [github.com/canivel/kaos](https://github.com/canivel/kaos)*
