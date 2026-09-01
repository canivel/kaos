"""Harness-generated workload for the GDL probe (pre-registered as such).

Pure function of the lock's generator_seed (20260728): 8 task families
x 6 failed variants (24 silent_wrong_branch + 24 error_visible) + 2
successful episodes per family, written into a REAL kaos database via
kaos.schema.init_schema so every arm consumes production tables
(agents, tool_calls, state key='task', episode_signals).

Ground-truth divergence call_ids are recorded in the returned manifest
and NEVER exposed to any arm.
"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass

from kaos.schema import init_schema

SEED = 20260728


@dataclass
class Episode:
    agent_id: str
    family: str
    qclass: str        # 'silent_wrong_branch' | 'error_visible' | 'success'
    task: str
    gt_call_id: str | None  # planted divergence (failed episodes only)


# 8 families. Each: distinctive vocabulary, a canonical step list (args
# vary only in path STEMS between variants, so frozen normalization maps
# same-family steps to identical labels), a divergence index, and a
# wrong-branch step whose label differs from the canonical one at that
# index (different short-string mode arg or different tool).
def _families() -> list[dict]:
    return [
        dict(name="parser", dir="src", ext="py", div=3,
             task=lambda s: f"fix the tokenizer parser regression in src/parser_{s}.py and rerun the grammar suite",
             steps=[("fs_read", lambda s: {"path": f"src/parser_{s}.py"}),
                    ("grep_search", lambda s: {"pattern": "tokenize", "path": f"src/parser_{s}.py"}),
                    ("fs_read", lambda s: {"path": "tests/test_grammar.py"}),
                    ("fs_write", lambda s: {"path": f"src/parser_{s}.py", "mode": "patch"}),
                    ("shell_run", lambda s: {"cmd": "pytest tests/test_grammar.py", "cwd": "src/repo"}),
                    ("fs_read", lambda s: {"path": "build/report.txt"}),
                    ("shell_run", lambda s: {"cmd": "pytest tests/", "cwd": "src/repo"}),
                    ("log_write", lambda s: {"summary": "grammar suite green"})],
             wrong=("fs_write", lambda s: {"path": f"src/parser_{s}.py", "mode": "overwrite"})),
        dict(name="invoice", dir="billing", ext="json", div=2,
             task=lambda s: f"reconcile the invoice ledger batch billing/batch_{s}.json against the payments export",
             steps=[("fs_read", lambda s: {"path": f"billing/batch_{s}.json"}),
                    ("fs_read", lambda s: {"path": "billing/payments.csv"}),
                    ("transform_apply", lambda s: {"path": f"billing/batch_{s}.json", "op": "join-payments"}),
                    ("validate_run", lambda s: {"path": "billing/merged.json", "schema": "ledger-v2"}),
                    ("fs_write", lambda s: {"path": "billing/reconciled.json", "mode": "create"}),
                    ("report_render", lambda s: {"path": "billing/reconciled.json", "fmt": "summary"}),
                    ("log_write", lambda s: {"summary": "ledger reconciled"})],
             wrong=("transform_apply", lambda s: {"path": f"billing/batch_{s}.json", "op": "dedupe-only"})),
        dict(name="deploy", dir="infra", ext="yaml", div=4,
             task=lambda s: f"roll out the canary deploy manifest infra/canary_{s}.yaml to staging cluster",
             steps=[("fs_read", lambda s: {"path": f"infra/canary_{s}.yaml"}),
                    ("validate_run", lambda s: {"path": f"infra/canary_{s}.yaml", "schema": "k8s"}),
                    ("fs_write", lambda s: {"path": "infra/rendered.yaml", "mode": "create"}),
                    ("shell_run", lambda s: {"cmd": "kubectl diff -f infra/rendered.yaml", "cwd": "infra/env"}),
                    ("deploy_apply", lambda s: {"path": "infra/rendered.yaml", "target": "staging"}),
                    ("probe_http", lambda s: {"url": "https://staging.internal/health", "expect": "200"}),
                    ("log_write", lambda s: {"summary": "canary healthy"})],
             wrong=("deploy_apply", lambda s: {"path": "infra/rendered.yaml", "target": "production"})),
        dict(name="schema", dir="db", ext="sql", div=2,
             task=lambda s: f"apply the additive schema migration db/mig_{s}.sql and backfill the audit column",
             steps=[("fs_read", lambda s: {"path": f"db/mig_{s}.sql"}),
                    ("sql_exec", lambda s: {"path": f"db/mig_{s}.sql", "mode": "dry-run"}),
                    ("sql_exec", lambda s: {"path": f"db/mig_{s}.sql", "mode": "apply"}),
                    ("sql_query", lambda s: {"sql_file": "db/checks.sql", "expect": "rows"}),
                    ("fs_write", lambda s: {"path": "db/backfill.sql", "mode": "create"}),
                    ("sql_exec", lambda s: {"path": "db/backfill.sql", "mode": "apply"}),
                    ("log_write", lambda s: {"summary": "migration applied"})],
             wrong=("sql_exec", lambda s: {"path": f"db/mig_{s}.sql", "mode": "force"})),
        dict(name="cache", dir="services", ext="py", div=3,
             task=lambda s: f"tune the redis cache eviction policy in services/cache_{s}.py under memory pressure",
             steps=[("fs_read", lambda s: {"path": f"services/cache_{s}.py"}),
                    ("metric_query", lambda s: {"name": "cache_hit_ratio", "window": "1h"}),
                    ("fs_read", lambda s: {"path": "services/config.toml"}),
                    ("fs_write", lambda s: {"path": "services/config.toml", "mode": "patch"}),
                    ("service_restart", lambda s: {"unit": "cache", "wait": "ready"}),
                    ("metric_query", lambda s: {"name": "cache_hit_ratio", "window": "10m"}),
                    ("log_write", lambda s: {"summary": "eviction tuned"})],
             wrong=("fs_write", lambda s: {"path": "services/config.toml", "mode": "replace"})),
        dict(name="auth", dir="api", ext="py", div=4,
             task=lambda s: f"rotate the oauth refresh flow secret in api/auth_{s}.py without breaking sessions",
             steps=[("fs_read", lambda s: {"path": f"api/auth_{s}.py"}),
                    ("secret_get", lambda s: {"name": "oauth-refresh", "scope": "current"}),
                    ("secret_put", lambda s: {"name": "oauth-refresh-next", "scope": "staged"}),
                    ("fs_write", lambda s: {"path": f"api/auth_{s}.py", "mode": "patch"}),
                    ("shell_run", lambda s: {"cmd": "pytest api/tests/test_auth.py", "cwd": "api/repo"}),
                    ("secret_put", lambda s: {"name": "oauth-refresh", "scope": "promote"}),
                    ("log_write", lambda s: {"summary": "secret rotated"})],
             wrong=("secret_put", lambda s: {"name": "oauth-refresh", "scope": "promote-early"})),
        dict(name="scraper", dir="pipelines", ext="py", div=2,
             task=lambda s: f"unblock the listings scraper pipeline pipelines/scrape_{s}.py rate limited by the source",
             steps=[("fs_read", lambda s: {"path": f"pipelines/scrape_{s}.py"}),
                    ("http_fetch", lambda s: {"url": "https://source.example/api/listings", "mode": "throttled"}),
                    ("fs_write", lambda s: {"path": f"pipelines/scrape_{s}.py", "mode": "patch"}),
                    ("shell_run", lambda s: {"cmd": "python pipelines/smoke.py", "cwd": "pipelines/repo"}),
                    ("queue_put", lambda s: {"topic": "listings-raw", "batch": "smoke"}),
                    ("metric_query", lambda s: {"name": "scrape_success", "window": "15m"}),
                    ("log_write", lambda s: {"summary": "scraper unblocked"})],
             wrong=("http_fetch", lambda s: {"url": "https://source.example/api/listings", "mode": "burst"})),
        dict(name="notebook", dir="analysis", ext="ipynb", div=3,
             task=lambda s: f"parameterize the churn analysis notebook analysis/churn_{s}.ipynb for the weekly run",
             steps=[("fs_read", lambda s: {"path": f"analysis/churn_{s}.ipynb"}),
                    ("fs_read", lambda s: {"path": "analysis/params.yaml"}),
                    ("nb_execute", lambda s: {"path": f"analysis/churn_{s}.ipynb", "kernel": "python3"}),
                    ("fs_write", lambda s: {"path": "analysis/params.yaml", "mode": "patch"}),
                    ("nb_execute", lambda s: {"path": f"analysis/churn_{s}.ipynb", "kernel": "python3"}),
                    ("report_render", lambda s: {"path": "analysis/out.html", "fmt": "html"}),
                    ("log_write", lambda s: {"summary": "weekly churn rendered"})],
             wrong=("nb_execute", lambda s: {"path": f"analysis/churn_{s}.ipynb", "kernel": "python2"})),
    ]


def _insert_episode(
    conn: sqlite3.Connection, agent_id: str, task: str,
    calls: list[tuple[str, dict, str, str | None]], success: bool,
) -> list[str]:
    conn.execute(
        "INSERT INTO agents (agent_id, name, status) VALUES (?, ?, ?)",
        (agent_id, agent_id, "completed" if success else "failed"),
    )
    conn.execute(
        "INSERT INTO state (agent_id, key, value) VALUES (?, 'task', ?)",
        (agent_id, task),
    )
    ids = []
    import json as _json
    for i, (tool, args, status, err) in enumerate(calls):
        cid = f"{agent_id}-c{i:02d}"
        ids.append(cid)
        conn.execute(
            "INSERT INTO tool_calls (call_id, agent_id, tool_name, input, "
            "output, status, started_at, error_message) VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?)",
            (cid, agent_id, tool, _json.dumps(args), "ok" if status == "success" else None,
             status, f"2026-07-28T10:00:{i:02d}.000", err),
        )
    n_err = sum(1 for c in calls if c[2] == "error")
    conn.execute(
        "INSERT INTO episode_signals (agent_id, status, success, "
        "tool_calls_count, tool_calls_error) VALUES (?, ?, ?, ?, ?)",
        (agent_id, "completed" if success else "failed",
         1 if success else 0, len(calls), n_err),
    )
    return ids


def build(db_path: str) -> list[Episode]:
    rng = random.Random(SEED)
    conn = sqlite3.connect(db_path)
    init_schema(conn)
    episodes: list[Episode] = []

    for fam in _families():
        name, div = fam["name"], fam["div"]
        # 2 successful episodes per family (stems s7, s8)
        for stem in ("s7", "s8"):
            aid = f"{name}-ok-{stem}"
            calls = [(t, argf(stem), "success", None) for t, argf in fam["steps"]]
            _insert_episode(conn, aid, fam["task"](stem), calls, success=True)
            episodes.append(Episode(aid, name, "success", fam["task"](stem), None))
        # 6 failed variants: 3 silent + 3 error_visible (stems s1..s6)
        for vi, stem in enumerate(("s1", "s2", "s3", "s4", "s5", "s6")):
            qclass = "silent_wrong_branch" if vi < 3 else "error_visible"
            aid = f"{name}-fail-{stem}"
            steps = fam["steps"]
            wt, wargf = fam["wrong"]
            calls: list[tuple[str, dict, str, str | None]] = []
            for i, (t, argf) in enumerate(steps[:div]):
                calls.append((t, argf(stem), "success", None))
            gt_idx = len(calls)
            calls.append((wt, wargf(stem), "success", None))  # the silent wrong branch
            # divergent follow-ons (not present in the success trajectory)
            calls.append(("fs_read", {"path": "scratch/followup.txt"}, "success", None))
            calls.append(("retry_wait", {"reason": "unexpected state", "attempts": rng.randint(2, 4)}, "success", None))
            if qclass == "error_visible":
                calls.append(("shell_run", {"cmd": "pytest tests/", "cwd": "ci/repo"},
                              "error", "exit 1: assertion failed downstream"))
            else:
                # silent: one more coherent-looking step, then the episode just fails
                t, argf = steps[min(div + 1, len(steps) - 1)]
                calls.append((t, argf(stem), "success", None))
            ids = _insert_episode(conn, aid, fam["task"](stem), calls, success=False)
            episodes.append(Episode(aid, name, qclass, fam["task"](stem), ids[gt_idx]))

    conn.commit()
    conn.close()
    return episodes
