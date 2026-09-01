"""
Generate a terminal recording: 2am production incident — SQL over 50K events → root cause in 12s.

Story: 2am pager fires. API returning 500 errors. Agent queries the KAOS event journal SQL,
finds the exact deployment 47 minutes ago, traces to a single config line that broke the
connection pool. Hotfix applied with checkpoint. 4,847 affected requests logged.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_incident.py
    uv run python render_gif.py kaos_uc_incident.yml
"""
import random
import yaml
import os

# ── ANSI helpers ──────────────────────────────────────────────────────────────
R  = "\u001b[0m"
B  = "\u001b[1m"
G  = "\u001b[32m"
Y  = "\u001b[33m"
BL = "\u001b[34m"
MG = "\u001b[35m"
CY = "\u001b[36m"
WH = "\u001b[37m"
DG = "\u001b[90m"
BG = "\u001b[92m"
BY = "\u001b[93m"
BC = "\u001b[96m"
BB = "\u001b[94m"
RD = "\u001b[31m"
BR = "\u001b[91m"

PROMPT = f"{G}❯{R} "
CRLF   = "\r\n"

def pause(ms=500):
    return {"delay": ms, "content": ""}

def nl():
    return {"delay": 60, "content": CRLF}

def prompt_line():
    return [{"delay": 500, "content": CRLF + PROMPT}]

def type_cmd(cmd, wpm=200):
    frames = []
    for ch in cmd:
        d = int(60000 / (wpm * 5)) + random.randint(-8, 18)
        frames.append({"delay": max(30, d), "content": ch})
    frames.append({"delay": 200, "content": CRLF})
    return frames

def out(text, delay=55):
    return [{"delay": delay, "content": text + CRLF}]

def out_slow(text, delay=120):
    return [{"delay": delay, "content": text + CRLF}]

def blank(delay=80):
    return [{"delay": delay, "content": CRLF}]

def section(title, delay=900):
    width = 74
    bar = "─" * width
    return [
        {"delay": delay, "content": f"{DG}  ┌{bar}┐{R}{CRLF}"},
        {"delay": 60,    "content": f"{DG}  │{R}  {B}{CY}{title:<{width-2}}{R}  {DG}│{R}{CRLF}"},
        {"delay": 60,    "content": f"{DG}  └{bar}┘{R}{CRLF}"},
    ]

def separator(delay=400):
    return [{"delay": delay, "content": f"{DG}{'─'*78}{R}{CRLF}"}]

def make_config(title):
    return {
        "command": "bash", "cwd": None,
        "env": {"recording": True},
        "cols": 110, "rows": 36,
        "repeat": 0, "quality": 100,
        "frameDelay": "auto", "maxIdleTime": 2000,
        "frameBox": {
            "type": "window", "title": title,
            "style": {"border": "0px black solid"},
        },
        "watermark": {"imagePath": None, "style": {
            "position": "absolute", "right": "15px", "bottom": "15px",
            "width": "100px", "opacity": "0.9",
        }},
        "cursorStyle": "bar", "fontFamily": "Consolas, Menlo, monospace",
        "fontSize": 14, "lineHeight": 1.3, "theme": {
            "background": "#0d1117", "foreground": "#c9d1d9",
        },
    }


# ── Recording frames ───────────────────────────────────────────────────────────

def build():
    f = []

    # ── Scene 1: Title card — 2am alert ───────────────────────────────────────
    f += [pause(600)]
    f += out(f"")
    f += out(f"")
    f += out(f"  {B}{BR}[ALERT]{R}  {WH}api.prod.example.com{R}  {DG}—{R}  {BR}HTTP 500 rate: 23%{R}  {DG}(threshold: 1%){R}")
    f += out(f"  {DG}Time: 2026-04-10 02:17:43 UTC  │  Severity: P0  │  On-call: Danilo{R}")
    f += out(f"")
    f += out(f"  {B}{CY}KAOS — 2am Production Incident Response{R}")
    f += out(f"  {DG}Event journal: 50,000+ events  │  SQL-queryable in real time{R}")
    f += out(f"  {DG}Target: root cause in under 60 seconds{R}")
    f += out(f"")
    f += [pause(2000)]

    # ── Scene 2: Step 1 — Query recent errors ─────────────────────────────────
    f += section("STEP 1 — Query recent errors from event journal")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos --json query \"SELECT timestamp, agent_id, tool_name, error FROM tool_calls WHERE status='error' AND timestamp > NOW() - INTERVAL '1 hour' ORDER BY timestamp DESC LIMIT 20\"")
    f += blank()
    f += out(f"  {DG}Scanning 50,247 events...{R}", 300)
    f += [pause(500)]
    f += out(f"  {DG}timestamp              agent_id       tool_name    error{R}")
    f += out(f"  {DG}─────────────────────  ─────────────  ───────────  ──────────────────────────────{R}")
    error_rows = [
        ("02:17:41", "ConnectionPoolError: pool exhausted (max=2)"),
        ("02:17:39", "ConnectionPoolError: pool exhausted (max=2)"),
        ("02:17:37", "ConnectionPoolError: pool exhausted (max=2)"),
        ("02:17:35", "ConnectionPoolError: pool exhausted (max=2)"),
        ("02:17:33", "ConnectionPoolError: pool exhausted (max=2)"),
        ("02:17:31", "ConnectionPoolError: pool exhausted (max=2)"),
    ]
    for ts, err in error_rows:
        f += out(f"  {DG}2026-04-10 {ts}{R}  {Y}api-gateway{R}    db_query     {BR}{err}{R}", 80)
    f += out(f"  {DG}...{R}", 60)
    f += out(f"  {DG}(20 rows, 847 total errors in last hour){R}")
    f += blank()
    f += out(f"  {BY}Pattern:{R}  {BR}847 errors in 1 hour, ALL from api-gateway, ALL ConnectionPoolError{R}")
    f += out(f"  {DG}  pool_size is too low — something changed the connection pool config{R}")
    f += blank()
    f += [pause(1400)]

    # ── Scene 3: Step 2 — Correlate with deploy history ───────────────────────
    f += section("STEP 2 — Correlate with deploy history (VFS event log)")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos --json query \"SELECT timestamp, agent_id, file_path, content FROM vfs_events WHERE timestamp > NOW() - INTERVAL '2 hours' AND event_type='write' ORDER BY timestamp\"")
    f += blank()
    f += out(f"  {DG}Scanning vfs_events...{R}", 300)
    f += [pause(400)]
    f += out(f"  {DG}timestamp              agent_id       file_path{R}")
    f += out(f"  {DG}─────────────────────  ─────────────  ─────────────────────────────────{R}")
    f += out(f"  {DG}2026-04-10 00:22:14{R}  deploy-runner  config/app.yaml              {DG}(version bump){R}")
    f += out(f"  {DG}2026-04-10 00:22:16{R}  deploy-runner  requirements.txt             {DG}(deps update){R}")
    f += out(f"  {BR}2026-04-10 01:30:51{R}  {Y}deploy-runner{R}  {BR}config/db.yaml{R}               {BR}← 47 min ago{R}")
    f += out(f"  {DG}2026-04-10 01:30:52{R}  deploy-runner  config/cache.yaml            {DG}(cache ttl){R}")
    f += blank()
    f += out(f"  {BR}⚑  Suspicious:{R}  {BY}config/db.yaml written 47 minutes ago{R}  {DG}— error rate spiked at 01:30{R}")
    f += blank()
    f += [pause(1500)]

    # ── Scene 4: Step 3 — Confirm the culprit ────────────────────────────────
    f += section("STEP 3 — Confirm the culprit: diff pre-deploy vs HEAD")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos diff api-gateway pre-deploy HEAD")
    f += blank()
    f += out(f"  {DG}Comparing checkpoint pre-deploy → HEAD  (file: config/db.yaml){R}")
    f += blank()
    f += out(f"  {DG}  config/db.yaml{R}")
    f += out(f"  {DG}  ─────────────────────────────────────────────────────────────{R}")
    f += out(f"  {DG}    host:       db.prod.internal{R}")
    f += out(f"  {DG}    port:       5432{R}")
    f += out(f"  {DG}    database:   app_production{R}")
    f += out(f"  {RD}  - pool_size: 5{R}   {DG}← pre-deploy value{R}")
    f += out(f"  {G}  + pool_size: 2{R}   {DG}← current value  ✗  TOO LOW{R}")
    f += out(f"  {DG}    timeout:    30{R}")
    f += out(f"  {DG}    max_overflow: 0{R}")
    f += blank()
    f += out(f"  {B}1 line changed.{R}  {BR}pool_size: 5 → 2{R}")
    f += blank()
    f += out(f"  {DG}Error rate timeline:{R}")
    f += out(f"  {DG}  01:28  →  0.0%  (nominal){R}")
    f += out(f"  {DG}  01:30  →  0.0%  (deploy begins){R}")
    f += out(f"  {BR}  01:31  →  8.4%  (pool exhaustion starts){R}")
    f += out(f"  {BR}  01:35  → 18.2%  (escalating){R}")
    f += out(f"  {BR}  02:17  → 23.0%  ← NOW{R}")
    f += blank()
    f += out(f"  {BY}Root cause confirmed:{R}  {BR}pool_size reduced from 5 to 2 by deploy 47 minutes ago.{R}")
    f += blank()
    f += [pause(1800)]

    # ── Scene 5: Step 4 — Safe hotfix with checkpoint ─────────────────────────
    f += section("STEP 4 — Safe hotfix with checkpoint")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos checkpoint api-gateway --label broken-state")
    f += out(f"  {G}✓{R}  Checkpoint  {DG}[broken-state]{R}  saved  {DG}(broken config preserved for post-mortem){R}")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos write api-gateway /config/db.yaml pool_size=5")
    f += out(f"  {G}✓{R}  Written: config/db.yaml  {DG}pool_size: 2 → 5{R}")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos run api-gateway -- 'reload config'")
    f += out(f"  {DG}[api-gateway]{R}  Config reloaded.  pool_size=5 active.")
    f += blank()
    f += out(f"  {DG}Error rate monitor:{R}")
    f += out(f"  {BR}  02:17:50  →  23.0%{R}")
    f += [pause(300)]
    f += out(f"  {Y}  02:18:05  →  11.4%  {DG}(pool draining backlog){R}", 200)
    f += [pause(300)]
    f += out(f"  {Y}  02:18:20  →   4.8%{R}", 200)
    f += [pause(300)]
    f += out(f"  {G}  02:18:35  →   0.7%{R}", 200)
    f += [pause(300)]
    f += out(f"  {G}  02:18:50  →   0.0%  {BG}✓ RESOLVED{R}", 200)
    f += blank()
    f += [pause(1200)]

    # ── Scene 6: Step 5 — Post-mortem query ───────────────────────────────────
    f += section("STEP 5 — Post-mortem query: total blast radius")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos --json query \"SELECT COUNT(*) as affected_requests, MIN(timestamp) as start, MAX(timestamp) as end FROM tool_calls WHERE status='error' AND agent_id='api-gateway'\"")
    f += blank()
    f += out(f"  {DG}Scanning tool_calls...{R}", 300)
    f += [pause(400)]
    f += out(f"  {DG}affected_requests   start                  end{R}")
    f += out(f"  {DG}─────────────────   ─────────────────────  ─────────────────────{R}")
    f += out(f"  {BY}4,847{R}               {DG}2026-04-10 01:31:04{R}    {DG}2026-04-10 02:18:50{R}")
    f += blank()
    f += out(f"  {DG}Duration:{R}   {BY}47 minutes 46 seconds{R}")
    f += out(f"  {DG}Requests:{R}   {BY}4,847{R} errors  {DG}(23% of 21,074 total requests in window){R}")
    f += out(f"  {DG}Cause:{R}      {BR}pool_size: 5 → 2  (1-line config change in deploy){R}")
    f += out(f"  {DG}Fix:{R}        {G}pool_size: 2 → 5  (1-line revert){R}")
    f += out(f"  {DG}Fix time:{R}   {G}58 seconds from alert acknowledgement{R}")
    f += blank()
    f += [pause(1000)]

    # ── Scene 7: Summary ───────────────────────────────────────────────────────
    f += separator(700)
    f += out(f"  {BG}Incident resolved.{R}  Root cause identified in {B}12 seconds{R} via SQL over event journal.")
    f += separator()
    f += blank()
    f += out(f"  {DG}Alert received:{R}     02:17:43")
    f += out(f"  {DG}Root cause found:{R}   02:17:55  {G}(12 seconds){R}")
    f += out(f"  {DG}Hotfix applied:{R}     02:18:00")
    f += out(f"  {DG}Error rate → 0%:{R}   02:18:50")
    f += blank()
    f += out(f"  {DG}Full audit trail:{R}   every query, write, and config change in kaos.db")
    f += out(f"  {DG}Blast radius:{R}       {BY}4,847 requests{R}  over 47 minutes")
    f += out(f"  {DG}Recovery:{R}           {G}1 config line reverted, 0 rollback required{R}")
    f += blank()
    f += [pause(3000)]

    return f


# ── YAML output ────────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_yml = os.path.join(script_dir, "kaos_uc_incident.yml")

    records = build()
    config  = make_config("KAOS — 2am Production Incident: SQL Over 50K Events → Root Cause in 12s")

    doc = {"config": config, "records": records}
    with open(out_yml, "w", encoding="utf-8") as fh:
        yaml.dump(doc, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    total_ms = sum(r.get("delay", 0) for r in records)
    print(f"Written: {out_yml}")
    print(f"Frames:  {len(records)}")
    print(f"Est. duration: {total_ms/1000:.1f}s")
    print(f"\nRender with:")
    print(f"  uv run python render_gif.py kaos_uc_incident.yml")


if __name__ == "__main__":
    main()
