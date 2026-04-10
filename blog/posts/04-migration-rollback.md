# KAOS AI Agents Detected Data Corruption at Row 847K and Rolled Back the Migration in 0.3 Seconds

*Data Engineering · April 13, 2026 · 9 min read*

*A 2M-row backfill hit 7.6% unexpected NULLs mid-stream. The KAOS migration agent detected the anomaly, rolled back its own VFS in 0.3 seconds, and left every other agent running untouched.*

---

The migration looked fine until row 847,412. Then 7.6% of rows came out NULL where they should have been NOT NULL. The `subscription_tier` column — the one that determines what every user can access — had silent data corruption at scale.

Without KAOS, you find this after the migration completes and a monitoring alert fires. With KAOS, the anomaly detector catches it mid-stream, pauses the migration, and rolls back in 0.3 seconds — before any corruption reaches production.

---

![KAOS migration rollback demo — 2M row backfill, anomaly at row 847K, 0.3s surgical rollback](https://canivel.github.io/kaos/docs/demos/kaos_uc_migration.gif)

*Phase 1 succeeds, checkpoint taken. Phase 2 backfill detects NULL anomaly at row 847,412. Rollback in 0.3s. Analytics agents unaffected.*

---

## The Migration Plan

Adding a `subscription_tier` column to a 2-million-row `users` table. Three phases, checkpoints between each, analytics agents running alongside:

```python
# migration/add_subscription_tier.py

PHASES = [
    {
        "name": "schema_change",
        "sql": "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(20)",
        "checkpoint": "pre-backfill"
    },
    {
        "name": "backfill",
        "sql": """
            UPDATE users
            SET subscription_tier = s.tier
            FROM subscriptions s
            WHERE users.id = s.user_id
        """,
        "batch_size": 10_000,
        "anomaly_check": True,
        "checkpoint": "pre-constraint"
    },
    {
        "name": "enforce_constraint",
        "sql": "ALTER TABLE users ALTER COLUMN subscription_tier SET NOT NULL",
        "checkpoint": "complete"
    }
]
```

Other analytics agents — `analytics-agent-1` and `analytics-agent-2` — are running queries against the same data throughout. The migration agent cannot interfere with them because each agent has its own isolated VFS.

---

## Phase 1 Succeeds — First Checkpoint

```
kaos run migration-agent "ALTER TABLE users ADD COLUMN subscription_tier VARCHAR(20)"

# [migration-agent] schema change: SUCCESS
# [migration-agent] 2,041,847 rows will be updated in Phase 2

kaos checkpoint migration-agent --label pre-backfill

# Checkpoint created: pre-backfill
# Phase 1 state: schema applied, no data changes yet
# Timestamp: 2026-04-13T01:33:11Z
```

This checkpoint is the safety line. If anything goes wrong in the 2-million-row backfill, `kaos restore migration-agent --label pre-backfill` returns to exactly this state — schema applied, data untouched, ready to retry with a fix.

---

## Phase 2 — The Backfill (and the Anomaly)

The backfill starts in 10,000-row batches. The anomaly detector samples NULL counts every 50K rows:

```
[backfill]  100,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  200,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  300,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  500,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  700,000 rows processed  NULL count: 0      (0.0%)  ✓
[backfill]  847,412 rows processed  NULL count: 64,412 (7.6%)  ✗

ANOMALY DETECTED: NULL rate 7.6% exceeds threshold 0.0%
Expected: 0 NULLs in subscription_tier
Got:      64,412 NULLs out of 847,412 rows processed

Migration PAUSED. No further rows updated.
```

The migration pauses automatically. 7.6% NULL rate with a NOT NULL target is not recoverable without a fix.

---

## Surgical Rollback — 0.3 Seconds

```
kaos restore migration-agent --label pre-backfill

# Restoring migration-agent to checkpoint: pre-backfill
#
# Changes reverted:
# --- migration/state.json
# -  "phase": "backfill",
# -  "rows_processed": 847412,
# -  "null_count": 64412,
# -  "status": "anomaly_paused"
# +  "phase": "schema_complete",
# +  "rows_processed": 0,
# +  "status": "ready_for_backfill"
#
# Restore complete in 0.31s
```

0.31 seconds. The full VFS state of the migration agent is rewound. The partial backfill state, the anomaly markers, the paused status — all gone. Back to a clean, known-good state.

---

## While This Was Happening — Other Agents Kept Running

```
kaos ls

# NAME                STATUS    UPTIME   EVENTS
# migration-agent     restored  14m      847 (rollback applied)
# analytics-agent-1   running   14m      1,204
# analytics-agent-2   running   14m      983
# dashboard-agent     running   14m      441
```

All three other agents kept running through the entire incident. Their VFS state was never touched. This is what isolated VFS means in practice.

**The key guarantee:** A migration agent failing and rolling back has zero effect on any other agent. Their VFS is in a separate SQLite-backed filesystem. The migration's partial state exists only inside `migration-agent`'s VFS and is now gone after the restore.

---

## Root Cause Analysis

The migration agent wrote a detailed anomaly report to its VFS before pausing:

```
kaos read migration-agent /logs/anomaly.md

## Anomaly Report: subscription_tier NULL at 7.6%

First NULL detected: user_id 8,042,183 (batch 84 of 205)
Pattern: All NULL users share a creation date before 2021-03-15

Root cause: Legacy users who registered before the subscriptions
table existed have no row in the `subscriptions` table.
The JOIN returns NULL for these users.

Fix: Use COALESCE to default unmatched users to 'free':
  UPDATE users
  SET subscription_tier = COALESCE(s.tier, 'free')
  FROM subscriptions s
  WHERE users.id = s.user_id

Estimated affected rows: ~156,000 legacy users (pre-2021-03-15)
```

The fix is one word: `COALESCE`.

---

## Retry — 2 Million Rows, 0 NULLs

```
[backfill]  500,000 rows   NULL count: 0  (0.0%)  ✓
[backfill]  1,000,000 rows NULL count: 0  (0.0%)  ✓
[backfill]  1,500,000 rows NULL count: 0  (0.0%)  ✓
[backfill]  2,000,000 rows NULL count: 0  (0.0%)  ✓
[backfill]  2,041,847 rows NULL count: 0  (0.0%)  ✓ COMPLETE

[phase 3]  ALTER TABLE users ALTER COLUMN subscription_tier SET NOT NULL
[phase 3]  SUCCESS — constraint enforced on 2,041,847 rows

Migration complete. Duration: 47m total (including rollback + retry).
```

---

## The Audit Trail

| Time | Event | Phase | Rows | NULLs | Notes |
|---|---|---|---|---|---|
| 01:33:08 | spawn | — | — | — | agent initialized |
| 01:33:11 | checkpoint | pre-schema | 0 | 0 | label: pre-schema |
| 01:33:14 | schema | schema_change | 0 | 0 | ALTER TABLE: success |
| 01:33:16 | checkpoint | pre-backfill | 0 | 0 | label: pre-backfill |
| 01:33:18 | backfill | backfill | 847,412 | 64,412 | anomaly: 7.6% NULL |
| 01:34:01 | restore | — | 0 | 0 | restored to pre-backfill (0.31s) |
| 01:34:04 | fix | — | — | — | COALESCE applied to query |
| 01:34:06 | backfill | backfill | 2,041,847 | 0 | full backfill: 0 NULLs |
| 02:21:14 | constraint | enforce_constraint | 2,041,847 | 0 | NOT NULL enforced |
| 02:21:17 | checkpoint | complete | 2,041,847 | 0 | migration complete |

---

2 million rows migrated safely. The anomaly was caught at row 847K — before any corruption reached production. Other operations never noticed. The rollback took 0.3 seconds. Without anomaly detection, you'd have found the NULL data from a user report, probably the next morning.

*KAOS is MIT-licensed and runs entirely locally. No data leaves your machine.*

*GitHub: [github.com/canivel/kaos](https://github.com/canivel/kaos)*
