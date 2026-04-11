# How KAOS AI Agents Found a Production Root Cause in 12 Seconds

*SRE / Operations · April 14, 2026 · 8 min read*

*23% HTTP 500 rate at 2am. A KAOS agent queried the append-only event journal, found 847 ConnectionPoolErrors, and traced them to a single config write 47 minutes prior — in 12 seconds.*

---

The pager fires at 2am. HTTP 500 rate: 23%. Your first question is always the same: **what changed?**

The traditional answer involves grepping application logs, checking the deploy history in four different places, DMing the on-call engineer who did the last deployment, and reading git commits to find the one that touched the right config. That process takes 45 to 90 minutes on a good night.

The KAOS answer is a SQL query. It takes 12 seconds.

---

![KAOS incident response demo — SQL query finds root cause in 12 seconds, hotfix drops error rate to 0%](https://canivel.github.io/kaos/docs/demos/kaos_uc_incident.gif)

*Pager fires at 02:17. SQL query at 02:17:12. Root cause identified at 02:17:24. Fix deployed. Error rate: 23% → 0%.*

---

## Traditional Incident Response vs KAOS

```
Traditional                        KAOS
---------------------------------  -----------------------------------------
grep application logs (10 min)     SQL query over event journal (<1s)
check deploy system (5 min)        included in the same query
read git commits (5 min)           every VFS write is timestamped
ask the team (20 min)              not needed
correlate timelines (15 min)       ORDER BY timestamp ASC
```

---

## Step 1 — Query the Error Pattern

First query: what errors are happening, which agent, and when did they start?

```sql
SELECT timestamp, agent_id, tool_name, error
FROM tool_calls
WHERE status = 'error'
  AND timestamp > datetime('now', '-1 hour')
ORDER BY timestamp DESC
LIMIT 20
```

```
timestamp             agent_id      tool_name      error
2026-04-14 02:16:58   api-gateway   db_query       ConnectionPoolError: pool exhausted
2026-04-14 02:16:57   api-gateway   db_query       ConnectionPoolError: pool exhausted
2026-04-14 02:16:55   api-gateway   db_query       ConnectionPoolError: pool exhausted
... (844 more rows, all ConnectionPoolError, all api-gateway)

First error: 2026-04-14 01:29:41  (47 minutes ago)
```

847 `ConnectionPoolError` exceptions from `api-gateway`, all starting exactly 47 minutes ago. The pattern is unambiguous: connection pool is exhausted. The question is why it changed 47 minutes ago.

---

## Step 2 — Find the Cause in VFS Events

Second query: what changed in the 2 hours before the errors started?

```sql
SELECT timestamp, agent_id, file_path, content_preview
FROM vfs_events
WHERE timestamp > datetime('now', '-2 hours')
  AND event_type = 'write'
ORDER BY timestamp ASC
```

```
timestamp             agent_id      file_path           content_preview
2026-04-14 01:28:53   api-gateway   config/db.yaml      ...pool_size: 2...
2026-04-14 01:28:54   api-gateway   config/app.yaml     ...log_level: debug...
2026-04-14 01:29:41   api-gateway   logs/error.log      ConnectionPoolError...
```

One line, one minute before errors started: `config/db.yaml` was written. The content preview shows `pool_size: 2`.

---

## The 1-Line Diff

```diff
--- config/db.yaml (pre-deploy checkpoint)
+++ config/db.yaml (HEAD)
@@ -8,7 +8,7 @@
 database:
   host: postgres-primary.internal
   port: 5432
-  pool_size: 10
+  pool_size: 2
   pool_timeout: 30
   max_overflow: 5
```

Exactly one line changed. `pool_size` went from `10` to `2`. The timestamp of that write is 01:28:53. The first error is 01:29:41. 48 seconds later, when the 2-connection pool was exhausted under production load.

**Root cause found at 02:17:24. Pager fired at 02:17:00. 12 seconds from alert to root cause.**

---

## Safe Hotfix

```
kaos checkpoint api-gateway --label broken-pool-size-2
# (preserved for post-mortem analysis)

# Apply the fix
kaos write api-gateway /config/db.yaml \
  "$(cat config/db.yaml | sed 's/pool_size: 2/pool_size: 10/')"
```

Error rate by minute:

```
minute   errors
02:17    847
02:18    412
02:19     89
02:20     14
02:21      2
02:22      0  ✓
```

Error rate drops from 23% to 0% in 5 minutes.

---

## The Post-Mortem in SQL

```sql
SELECT
  COUNT(*)                                              AS affected_requests,
  MIN(timestamp)                                        AS outage_start,
  MAX(timestamp)                                        AS outage_end,
  ROUND(
    (JULIANDAY(MAX(timestamp)) - JULIANDAY(MIN(timestamp))) * 24 * 60, 1
  )                                                     AS duration_min
FROM tool_calls
WHERE status = 'error'
  AND agent_id = 'api-gateway'
  AND error LIKE '%ConnectionPoolError%'
```

```
affected_requests   outage_start              outage_end                duration_min
4,847               2026-04-14 01:29:41       2026-04-14 02:22:03       52.4
```

4,847 affected requests. 52.4 minutes. All attributable to a single config write at 01:28:53.

**The full story in one place:** The event journal contains the config write, the first error, every subsequent error, and the resolution timestamp. No correlation across systems required. One SQLite file holds the complete incident timeline.

---

## What Made This 12 Seconds Instead of 90 Minutes

Three things, in order:

1. **Every VFS write is journaled.** When `api-gateway` wrote `config/db.yaml`, that write was appended to the event log with a timestamp, agent ID, and content. No extra instrumentation required.
2. **The event journal is a SQLite table.** `SELECT ... WHERE timestamp > ...` runs in milliseconds. No log aggregation service. No Elasticsearch cluster. No log parsing pipeline.
3. **VFS writes are content-addressable.** The diff between `pre-deploy` and `HEAD` is a SQL operation — compare blob hashes, retrieve content. Exact 1-line diff in under a second.

You don't have to grep logs. You don't have to check the deploy system. You don't have to ask anyone. The question "what changed?" has always had a fast answer — you just needed the infrastructure to make it a SQL query.

---

The question "what changed?" should always have a fast answer. KAOS makes it a SQL query. The 12-second root cause lookup isn't a trick — it's what happens when every agent write is journaled in a queryable append-only log from the start.

*KAOS is MIT-licensed and runs entirely locally. No data leaves your machine.*

*GitHub: [github.com/canivel/kaos](https://github.com/canivel/kaos)*
