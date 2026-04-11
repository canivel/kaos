# How KAOS Runs 4 Specialized AI Security Agents in Parallel — and Aggregates Every Finding in SQL

*Security · April 12, 2026 · 7 min read*

*SQL injection, secrets leakage, auth bypass, unsafe deserialization — each KAOS AI agent owns one attack surface, runs in full isolation, and results aggregate across all four with a single SQL query.*

---

Security review is serialized by default. One person, one angle, one pass. They check for SQL injection. Then they switch context to look for secrets. Then auth. Then deserialization. Each context switch costs focus. Most reviewers only catch what they were last thinking about.

KAOS makes it parallel. One agent per attack surface, all at once, results aggregated via SQL when they're done.

---

![KAOS security swarm demo — 4 parallel agents scanning PR-2847, SQL aggregation of findings](https://canivel.github.io/kaos/docs/demos/kaos_uc_security.gif)

*4 agents spawn simultaneously, each scans one attack surface, findings aggregate in SQL. 20 minutes total instead of 80.*

---

## The Problem With Sequential Security Reviews

A single reviewer cannot hold all attack surfaces in mind simultaneously. The cognitive cost of context-switching is real — and it produces gaps.

- **Context switching** between SQLi → auth → secrets → deserialization loses the mental model each time
- **Anchoring bias** — once you find one issue, you tend to look for similar issues, missing orthogonal vulnerabilities
- **Fatigue** — the fourth pass over 400 lines of code is less thorough than the first

The KAOS solution: one agent per attack surface, each with no knowledge of what the others found. No anchoring. No fatigue. Full focus on one threat model each.

---

## Spawning 4 Specialized Agents

Each agent gets its own isolated VFS copy of the PR code. They run simultaneously and cannot see each other's findings — full VFS isolation by design.

```bash
kaos parallel \
  "spawn sqli-scanner    --from ./pr-2847 --task sqli_audit" \
  "spawn secrets-scanner --from ./pr-2847 --task secrets_audit" \
  "spawn auth-scanner    --from ./pr-2847 --task auth_audit" \
  "spawn deser-scanner   --from ./pr-2847 --task deser_audit"

# [sqli-scanner]    spawned  vfs_id=sqli-4a1b  status=running
# [secrets-scanner] spawned  vfs_id=sec-9c2d   status=running
# [auth-scanner]    spawned  vfs_id=auth-3e4f   status=running
# [deser-scanner]   spawned  vfs_id=desr-7g8h   status=running
#
# 4 agents running in parallel
```

---

## Agent 1: SQL Injection Scan

The SQL injection agent works through `api/users.py`, `api/search.py`, and the database layer. It finds the vulnerability in 4 minutes:

```python
# api/search.py — FINDING: SQL injection via f-string interpolation

@app.route('/search')
def search_users():
    query = request.args.get('q', '')
    # CRITICAL: direct string interpolation into SQL
    sql = f"SELECT * FROM users WHERE name LIKE '%{query}%'"
    results = db.execute(sql)
    return jsonify(results)
```

Proposed fix — parameterized query:

```python
@app.route('/search')
def search_users():
    query = request.args.get('q', '')
    sql = "SELECT * FROM users WHERE name LIKE ?"
    results = db.execute(sql, (f'%{query}%',))
    return jsonify(results)
```

Isolation matters here: this agent only sees the code. It doesn't know the secrets agent found a hardcoded key. No anchoring — it stays focused on injection patterns throughout.

---

## Agent 2: Secrets & API Keys Scan

The secrets agent finds two issues in 6 minutes: a hardcoded production API key in `config/settings.py` (CRITICAL — now in git history forever) and an SSRF risk in `api/webhooks.py` where an unvalidated user-supplied URL is passed directly to `requests.get()` (MEDIUM).

---

## Agents 3 & 4: Auth + Deserialization

The auth agent works through all authentication middleware, JWT handling, and session management — clean result after 18 minutes.

The deserialization agent checks all `pickle.loads()`, `yaml.load()`, and `eval()` call sites — also clean.

```json
[
  {"name": "sqli-scanner",    "status": "complete", "findings_count": 1},
  {"name": "secrets-scanner", "status": "complete", "findings_count": 2},
  {"name": "auth-scanner",    "status": "complete", "findings_count": 0},
  {"name": "deser-scanner",   "status": "complete", "findings_count": 0}
]
```

---

## Aggregating with SQL

All four agents have written their findings to their individual VFS stores. Aggregate across all of them with a single query:

```sql
SELECT agent_name, severity, finding_type, file_path, line_no, summary
FROM vfs_findings
WHERE pr = 'PR-2847'
ORDER BY
  CASE severity
    WHEN 'CRITICAL' THEN 1
    WHEN 'HIGH'     THEN 2
    WHEN 'MEDIUM'   THEN 3
    ELSE 4
  END
```

```
Agent            Severity  Type              File                Line  Summary
---------------  --------  ----------------  ------------------  ----  ----------------------------------------
sqli-scanner     CRITICAL  sql_injection     api/search.py       14    f-string interpolation into SQL query
secrets-scanner  CRITICAL  hardcoded_secret  config/settings.py  47    Production API key in source code
secrets-scanner  MEDIUM    ssrf              api/webhooks.py     83    Unvalidated URL passed to requests.get()
auth-scanner     CLEAN     —                 —                   —     No auth bypass vectors found
deser-scanner    CLEAN     —                 —                   —     No unsafe deserialization found
```

2 CRITICAL, 1 MEDIUM, 2 clean passes. The full picture in one query.

---

## Verifying Isolation

The power of this approach depends on isolation being real. Verify it directly:

```sql
SELECT a.name, COUNT(e.id) as shared_events
FROM agents a
LEFT JOIN vfs_events e ON e.agent_id = a.id
  AND e.event_type = 'cross_agent_read'
WHERE a.name IN ('sqli-scanner','secrets-scanner','auth-scanner','deser-scanner')
GROUP BY a.name

-- Result: 0 cross-agent reads for all 4 agents
```

Zero cross-agent reads. Each agent worked in complete isolation. No anchoring is possible because no agent could observe what the others found.

**Why isolation matters for security reviews:** If Agent 2 could see that Agent 1 found a SQL injection issue, it might start looking for similar injection patterns — and miss the hardcoded key it was supposed to find. KAOS makes it structurally impossible for agents to influence each other's findings.

---

## The Speed Math

```
Approach                   Time               Anchoring Risk
-------------------------  -----------------  --------------
Sequential (1 reviewer)    80 min             High
Sequential (4 reviewers)   20 min wall clock  Medium
KAOS parallel agents       20 min wall clock  None
```

Same findings. 4× faster when parallelized against a single reviewer. Zero anchoring risk regardless.

---

The SQL injection and the hardcoded key would have taken two separate human passes to find. The SSRF might have been missed entirely — it's an easy one to overlook when you're already mentally categorizing credentials. KAOS found all three in 20 minutes, in parallel, with a full audit trail and zero cross-agent contamination.

*KAOS is MIT-licensed and runs entirely locally. No data leaves your machine.*

*GitHub: [github.com/canivel/kaos](https://github.com/canivel/kaos)*
