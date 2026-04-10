# Your Agent Broke the Build. KAOS Fixed It While You Slept.

*Code Quality · April 11, 2026 · 8 min read*

*How isolated VFS + surgical checkpoints turn a cascading test failure into a self-correcting pipeline — with a full SQL audit of every step.*

---

The refactor looked clean. The type change was surgical — just the `amount` field. But when CI ran, one test failed. Then the fix made it four.

This is the cascading failure pattern. You're not debugging the original problem anymore. You're debugging the fix to the fix. By morning, you've got six failing tests and a commit message that says *"should be fine."*

KAOS handles this differently. Here's the exact sequence.

---

![KAOS SDLC self-healing demo — checkpoint, wrong fix, cascade, rollback, correct fix, all tests green](https://canivel.github.io/kaos/docs/demos/kaos_uc_sdlc.gif)

*Full sequence: spawn agent → checkpoint → wrong fix → 4 failures → surgical restore → root cause read → correct fix → 47 tests green.*

---

## The Scenario

Payment service. The `amount` field was refactored from `float` to `str` for API serialization consistency. One test breaks immediately:

```
FAILED tests/test_payment.py::test_payment_decimal_precision
AssertionError: 10.00 != 10.0

Expected: Decimal('10.00')
Got:      10.0

1 failed, 46 passed in 3.2s
```

The dangerous pattern: fixing numeric precision by changing types can cascade. `float`, `Decimal`, and `str` all behave differently with equality checks, rounding, and JSON serialization. One wrong fix can turn one failure into four.

---

## Step 1 — Spawn the QA Agent

The QA agent gets its own isolated VFS — a complete copy of the payment service code in its own SQLite-backed virtual filesystem. It cannot affect your working tree or any other agent.

```
kaos spawn payment-qa --from ./payment-service

# [payment-qa] agent spawned  vfs_id=pqa-8f3a
# [payment-qa] running pytest...

FAILED tests/test_payment.py::test_payment_decimal_precision
  AssertionError: assert Decimal('10.00') == 10.0

  payment/models.py line 47:
    return float(self.amount)  # ← this line, post-refactor

1 failed, 46 passed
```

The failure is isolated inside the agent's VFS. Your repo is untouched.

---

## Step 2 — Checkpoint Before Attempting Anything

Before the agent touches a single line of code, it checkpoints. Not a git stash — a point-in-time snapshot of this agent's entire VFS state.

```
kaos checkpoint payment-qa --label pre-fix-attempt

# Checkpoint created: pre-fix-attempt
# Files snapshotted: 23
# VFS state: 1 test failing, 46 passing
# Timestamp: 2026-04-11T02:14:33Z
```

This checkpoint belongs to `payment-qa` specifically. If the fix goes wrong, you restore exactly this agent's state — not a repo-wide git reset that blows up every other agent's work in progress.

---

## Step 3 — The Wrong Fix (and Why It Matters)

The agent's first attempt is logically reasonable. The test expects `Decimal('10.00')`. The field returns `float`. Obvious fix: wrap in `float()` to normalize everything.

```python
# payment/models.py — agent's first attempt
def get_amount(self):
-   return self.amount
+   return float(self.amount)  # normalize to float
```

This is catastrophically wrong for financial data. `float(Decimal('10.00'))` returns `10.0` — losing the precision. And it breaks four more tests:

```
FAILED tests/test_payment.py::test_payment_decimal_precision
FAILED tests/test_payment.py::test_payment_total_rounding
FAILED tests/test_payment.py::test_invoice_line_items_sum
FAILED tests/test_payment.py::test_refund_partial_amount

4 failed, 43 passed in 3.4s
```

1 failure became 4. The cascade happened.

---

## Step 4 — Surgical Restore

One command returns the agent to exactly the pre-fix checkpoint — not a `git reset --hard` that would affect the entire repository:

```
kaos restore payment-qa --label pre-fix-attempt

# Restoring payment-qa to checkpoint: pre-fix-attempt
# Reverting 1 file: payment/models.py
# @@ -44,7 +44,7 @@
#  def get_amount(self):
# -    return float(self.amount)
# +    return self.amount
#
# Restore complete in 0.04s
# VFS state: 1 test failing, 46 passing (pre-fix state confirmed)
```

**Surgical** is the right word. Other agents running in parallel — integration tests, the documentation agent, the security scanner — none of them are touched. This one agent's VFS is rewound. Everything else keeps going.

---

## Step 5 — Read the Diagnostics

During the failed fix attempt, the QA agent wrote a structured failure report to its VFS. That report is now readable:

```
kaos read payment-qa /qa/failure_report.md

## Failure Analysis: test_payment_decimal_precision

Root cause: Precision loss in financial calculations.

The `amount` field uses `Decimal` for exact arithmetic. After the
refactor, `models.py` returns the raw field value which is now a
string ("10.00"). The test compares against Decimal('10.00').

String != Decimal. The equality check fails.

The wrong path: Converting to `float` loses mantissa precision.
float("10.00") == 10.0 — two decimal places lost, and float
arithmetic is not associative at scale.

Correct path: Decimal(str(amount)).quantize(Decimal('0.01'))
This preserves precision, handles string input, and passes IEEE 854
decimal arithmetic requirements for financial calculations.
```

The agent diagnosed itself. The failure report sits in the VFS audit trail and is SQL-queryable forever.

---

## Step 6 — The Right Fix

```python
# payment/models.py — correct fix
from decimal import Decimal, ROUND_HALF_UP

def get_amount(self) -> Decimal:
    """Return amount as Decimal with 2dp precision."""
    return Decimal(str(self.amount)).quantize(
        Decimal('0.01'),
        rounding=ROUND_HALF_UP
    )
```

```
tests/test_payment.py::test_payment_decimal_precision  PASSED
tests/test_payment.py::test_payment_total_rounding     PASSED
tests/test_payment.py::test_invoice_line_items_sum     PASSED
tests/test_payment.py::test_refund_partial_amount      PASSED
... (42 more)

47 passed in 3.1s
```

All 47 tests pass.

---

## The Audit Trail

Every event in this sequence is recorded in the KAOS SQLite journal:

| Timestamp | Event | File | Notes |
|---|---|---|---|
| 02:14:29 | spawn | — | agent created, VFS initialized |
| 02:14:31 | tool_call | — | pytest run: 1 fail, 46 pass |
| 02:14:33 | checkpoint | — | label: pre-fix-attempt |
| 02:14:41 | write | payment/models.py | attempt: float() cast |
| 02:14:43 | tool_call | — | pytest: 4 fail — cascade |
| 02:14:44 | write | /qa/failure_report.md | root cause diagnosed |
| 02:14:45 | restore | — | restored to pre-fix-attempt |
| 02:14:52 | write | payment/models.py | Decimal.quantize() fix applied |
| 02:14:54 | tool_call | — | pytest: 47 pass |

Every write. Every restore. Every test run. Timestamped, queryable, permanent. `git log` tells you what changed. The KAOS event journal tells you *what happened*.

---

## Why This Is Different From `git reset`

- **git reset** is repo-wide. KAOS restore is per-agent.
- **git log** shows commits. KAOS events show every file write with the test output that caused it.
- **git stash** is manual. KAOS checkpoints are programmatic — your agent creates them before every risky operation.
- **git bisect** finds which commit broke things. KAOS SQL finds what the agent was doing at 02:14:41 that caused 3 new failures.

**The surgical guarantee:** In a system where 4 agents are running simultaneously, one failing and recovering does not degrade the other 3. KAOS isolation is at the VFS layer, not the filesystem layer. Each agent's state is fully independent.

---

The build fixed itself while you slept. The audit trail told you exactly what happened when you woke up — down to the millisecond, down to the exact file write that caused the cascade, down to the restore that unwound it.

*KAOS is MIT-licensed and runs entirely locally. No data leaves your machine.*

*GitHub: [github.com/canivel/kaos](https://github.com/canivel/kaos)*
