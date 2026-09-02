"""``kaos demo --print`` — the terminal aha: one screen, no keys, no config,
nothing written to the current directory. Every number printed is measured
in this run; none is hard-coded.
"""
from __future__ import annotations

import json
import os
import random
import shutil
import tempfile
import time
from pathlib import Path

from kaos._ids import new_ulid

_SUBJECTS = ["payment", "webhook", "auth token", "cache", "migration", "rate limit",
             "queue consumer", "S3 upload", "cron job", "session cookie", "search index",
             "billing invoice", "email sender", "feature flag", "deploy pipeline"]
_SYMPTOMS = ["double charge on retry", "duplicate processing", "stale reads after write",
             "timeout treated as failure", "silent data loss", "thundering herd on restart",
             "permission denied in CI", "off-by-one in pagination", "memory leak under load",
             "clock skew breaks ordering"]
_FIXES = ["Idempotency-Key generated once per logical operation and reused across retries",
          "jittered exponential backoff with a retry budget", "write-through cache with versioned keys",
          "explicit lease with fencing token", "batch with checkpoint every 500 rows",
          "separate client timeout from server failure; only retry on the latter",
          "UTC everywhere and monotonic clocks for ordering"]
_TYPES = ["observation", "result", "insight", "error", "skill"]


_AREAS = ["checkout", "refunds", "subscriptions", "onboarding", "admin console", "mobile API",
          "batch export", "reporting", "partner sync", "notifications"]


def _sentence(rng: random.Random) -> str:
    return (f"{rng.choice(_SUBJECTS).capitalize()} {rng.choice(_SYMPTOMS)} in {rng.choice(_AREAS)}: "
            f"root cause traced; fix = {rng.choice(_FIXES)}.")


def run_print(agents: int | None = None, per_agent: int | None = None, out=print) -> dict:
    agents = agents or int(os.environ.get("KAOS_DEMO_AGENTS", "2000"))
    per_agent = per_agent or int(os.environ.get("KAOS_DEMO_PER_AGENT", "25"))
    rng = random.Random(42)
    tmp = Path(tempfile.mkdtemp(prefix="kaos-demo-"))
    db_path = tmp / "demo.db"
    stats: dict = {}
    try:
        from kaos.core import Kaos
        t0 = time.perf_counter()
        db = Kaos(str(db_path))
        conn = db.conn
        agent_ids = [new_ulid() for _ in range(agents)]
        conn.executemany(
            "INSERT INTO agents (agent_id, name, status, config, metadata) VALUES (?, ?, 'completed', '{}', '{}')",
            [(aid, f"agent-{i:04d}", ) for i, aid in enumerate(agent_ids)],
        )
        rows = []
        for aid in agent_ids:
            for _ in range(per_agent):
                rows.append((aid, rng.choice(_TYPES), _sentence(rng)))
        conn.executemany("INSERT INTO memory (agent_id, type, content) VALUES (?, ?, ?)", rows)
        conn.commit()
        seed_s = time.perf_counter() - t0
        total = agents * per_agent
        stats.update(agents=agents, memories=total, seed_s=round(seed_s, 2))

        from kaos.memory import MemoryStore
        mem = MemoryStore(conn)
        query = '"payment" OR "retry" OR "idempotency"'
        lat = []
        hits = []
        for _ in range(20):
            t1 = time.perf_counter()
            raw = mem.search(query, limit=12)
            lat.append((time.perf_counter() - t1) * 1000)
            seen: set[str] = set()
            hits = []
            for h in raw:  # same bm25 score → show distinct lessons, not one template thrice
                if h.content not in seen:
                    seen.add(h.content)
                    hits.append(h)
                if len(hits) == 3:
                    break
        lat.sort()
        p95 = lat[int(len(lat) * 0.95) - 1]
        stats.update(search_p95_ms=round(p95, 2), search_min_ms=round(lat[0], 2))

        fixer = db.spawn("fix-agent")
        db.write(fixer, "/src/payments.py", b"# fix\n")
        for tool, arg in (("fs_read", "/src/payments.py"), ("fs_write", "/src/payments.py"),
                          ("fs_write", "/tests/test_payments.py")):
            cid = db.log_tool_call(fixer, tool, {"path": arg})
            db.start_tool_call(cid)
            db.complete_tool_call(cid, {"ok": True}, status="success", token_count=120)
        audit = conn.execute(
            "SELECT started_at, tool_name, status, input FROM tool_calls WHERE agent_id=? ORDER BY started_at",
            (fixer,),
        ).fetchall()
        db.close()

        name_by_id = {aid: f"agent-{i:04d}" for i, aid in enumerate(agent_ids)}
        out("")
        out("  KAOS · local-first agent harness · no keys · no cloud · MIT")
        out("  " + "─" * 66)
        out(f"  Seeded {agents:,} agents × {per_agent} memories = {total:,} entries in a temp SQLite file   {seed_s:.1f} s")
        out("")
        out(f"  [1/3] Cross-agent memory search      query: {query}")
        for h in hits:
            body = h.content if len(h.content) <= 78 else h.content[:77] + "…"
            out(f"    #{h.memory_id:<6} {h.type:<11} {name_by_id.get(h.agent_id, '?'):<10} {body}")
        out(f"    {total:,} entries searched · p95 {p95:.1f} ms over 20 runs · measured now, not quoted")
        out("")
        out("  [2/3] The audit trail is a table")
        out(f"    {'started_at':<24} {'agent':<10} {'tool':<9} {'status':<8} input")
        for r in audit:
            out(f"    {r['started_at']:<24} {'fix-agent':<10} {r['tool_name']:<9} {r['status']:<8} {r['input']}")
        out("    SELECT * FROM tool_calls WHERE agent_id = ?   — plain SQL, forever")
        out("")
        out("  [3/3] Plug it into Claude Code")
        out("    claude plugin marketplace add canivel/kaos   →   /plugin install kaos@kaos")
        out("    or:  pip install kaos-harness && kaos connect claude-code")
        out("")
        out("  Nothing was written to this directory.   github.com/canivel/kaos")
        out("")
        stats["audit_rows"] = len(audit)
        return stats
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    print(json.dumps(run_print(out=lambda *_: None)))
