"""
Generate a terminal recording: Production DB migration with anomaly detection and surgical rollback.

Story: Agent runs a 2M-row DB migration (adding user_tier column). Checkpoints before each
phase. At row 847,412 detects 7.6% NULL anomaly — data corruption. Surgically rolls back
just the migration agent while analytics agents keep running unaffected. Root cause found,
fix applied, migration retried and succeeds.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_migration.py
    uv run python render_gif.py kaos_uc_migration.yml
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

    # ── Scene 1: Title card ───────────────────────────────────────────────────
    f += [pause(600)]
    f += out(f"")
    f += out(f"")
    f += out(f"  {B}{CY}KAOS — Production DB Migration{R}  {DG}—{R}  {WH}Checkpoint, Detect, Rollback{R}")
    f += out(f"  {DG}2M rows  │  3 phases  │  anomaly detected at row 847K  │  rollback in 0.3s{R}")
    f += out(f"")
    f += out(f"  {DG}Migration plan:{R}   {BY}ALTER TABLE users ADD COLUMN user_tier{R}")
    f += out(f"  {DG}Backfill from:{R}   {G}subscription{R} table")
    f += out(f"  {DG}Row count:{R}       {BY}2,000,000{R}")
    f += out(f"  {DG}Checkpoint:{R}      before each phase  {DG}(KAOS VFS snapshot){R}")
    f += out(f"  {DG}Safety net:{R}      analytics agents keep running — isolation guaranteed{R}")
    f += out(f"")
    f += [pause(2200)]

    # ── Scene 2: Spawn agents ─────────────────────────────────────────────────
    f += section("STEP 1 — Spawn agents: 1 migration + 2 analytics (isolated VFS each)")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos spawn migration-agent --tag migration --db prod.db")
    f += out(f"  {G}✓{R}  Agent spawned   {DG}[migration-agent]{R}  isolation=logical  vfs=migration-agent.db")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos spawn analytics-agent-1 --tag analytics")
    f += out(f"  {G}✓{R}  Agent spawned   {DG}[analytics-agent-1]{R}  isolation=logical  vfs=analytics-1.db")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos spawn analytics-agent-2 --tag analytics")
    f += out(f"  {G}✓{R}  Agent spawned   {DG}[analytics-agent-2]{R}  isolation=logical  vfs=analytics-2.db")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos ls")
    f += blank()
    f += out(f"  {DG}agent_id             status   tag          created{R}")
    f += out(f"  {DG}───────────────────  ───────  ───────────  ──────────────────{R}")
    f += out(f"  {G}migration-agent{R}      running  migration    2026-04-10 02:14:08")
    f += out(f"  {G}analytics-agent-1{R}    running  analytics    2026-04-10 02:14:09")
    f += out(f"  {G}analytics-agent-2{R}    running  analytics    2026-04-10 02:14:10")
    f += blank()
    f += [pause(1200)]

    # ── Scene 3: Phase 1 — Schema change ─────────────────────────────────────
    f += section("PHASE 1 — Schema change: ALTER TABLE users ADD COLUMN user_tier")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos run migration-agent -- 'ALTER TABLE users ADD COLUMN user_tier VARCHAR(20)'")
    f += blank()
    f += out(f"  {DG}[migration-agent]{R}  Executing schema change...")
    f += [pause(400)]
    f += out(f"  {DG}[migration-agent]{R}  ALTER TABLE users ADD COLUMN user_tier VARCHAR(20)")
    f += out(f"  {G}✓{R}  Schema change complete  {DG}(0.04s){R}")
    f += out(f"  {G}✓{R}  Column added: {BY}user_tier VARCHAR(20) NULL{R}")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos checkpoint migration-agent --label pre-backfill")
    f += out(f"  {G}✓{R}  Checkpoint created  {DG}[pre-backfill]{R}  {DG}snapshot_id=ckpt_847a3f{R}")
    f += out(f"  {G}✓{R}  VFS state frozen: schema_v2.sql, migration_log.json")
    f += out(f"  {DG}  Checkpoint stored in kaos.db blobs  ─  instant restore available{R}")
    f += blank()
    f += [pause(1000)]

    # ── Scene 4: Phase 2 — Backfill with progress ─────────────────────────────
    f += section("PHASE 2 — Backfill: UPDATE users SET user_tier = subscription.tier ...")
    f += blank()
    f += out(f"  {DG}[migration-agent]{R}  Starting backfill: 2,000,000 rows")
    f += out(f"  {DG}[migration-agent]{R}  Query: UPDATE users u SET u.user_tier =")
    f += out(f"  {DG}                         (SELECT tier FROM subscription s WHERE s.user_id = u.id){R}")
    f += blank()
    f += [pause(300)]

    # Progress bar scrolling
    progress_steps = [
        (100000,  "100,000",  "5.0%",  "0.8s"),
        (200000,  "200,000",  "10.0%", "1.7s"),
        (300000,  "300,000",  "15.0%", "2.5s"),
        (500000,  "500,000",  "25.0%", "4.1s"),
        (650000,  "650,000",  "32.5%", "5.4s"),
        (750000,  "750,000",  "37.5%", "6.2s"),
        (800000,  "800,000",  "40.0%", "6.6s"),
        (830000,  "830,000",  "41.5%", "6.9s"),
        (847000,  "847,000",  "42.4%", "7.0s"),
    ]
    for rows, label, pct, elapsed in progress_steps:
        bar_filled = int(rows / 2000000 * 30)
        bar = "█" * bar_filled + "░" * (30 - bar_filled)
        f += out(f"  {DG}[{bar}]{R}  {BY}{label:>9}{R} / 2,000,000  ({pct})  {DG}{elapsed}{R}", 200)

    f += blank()
    f += out(f"  {DG}[migration-agent]{R}  Processing batch at row 847,412...", 150)
    f += [pause(600)]

    # ── Scene 5: Anomaly detected ─────────────────────────────────────────────
    f += separator(700)
    f += out(f"  {BR}⚠  ANOMALY DETECTED  ─  migration paused{R}")
    f += separator()
    f += blank()
    f += out(f"  {DG}[migration-agent]{R}  Integrity check triggered at row 847,412")
    f += blank()
    f += out(f"  {BR}NULL count:{R}     {BY}64,412{R} / {BY}847,412{R} rows  =  {BR}7.6% NULL{R}")
    f += out(f"  {Y}Expected:{R}       0% NULL  {DG}(column declared NOT NULL in migration plan){R}")
    f += out(f"  {RD}Threshold:{R}      1% NULL maximum — {BR}EXCEEDED by 7.6×{R}")
    f += blank()
    f += out(f"  {DG}Anomaly vector:{R}  user_tier IS NULL after backfill attempt")
    f += out(f"  {DG}Row range:{R}       user_id 14,392 – 14,887  {DG}(sparse, not sequential){R}")
    f += out(f"  {DG}Severity:{R}        {BR}CRITICAL — halting migration, triggering rollback{R}")
    f += blank()
    f += [pause(2000)]

    # ── Scene 6: Surgical rollback ────────────────────────────────────────────
    f += section("SURGICAL ROLLBACK — restore migration-agent only, analytics unaffected")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos restore migration-agent --label pre-backfill")
    f += blank()
    f += out(f"  {DG}[kaos]{R}  Loading checkpoint {DG}[pre-backfill]{R}  snapshot_id=ckpt_847a3f")
    f += out(f"  {DG}[kaos]{R}  Diff vs current state:")
    f += blank()
    f += out(f"  {DG}  ─── changes being rolled back ───────────────────────────────────────{R}")
    f += out(f"  {RD}  - rows updated:  847,412  (user_tier values — ALL reverted){R}")
    f += out(f"  {RD}  - batch_log:     14 entries removed{R}")
    f += out(f"  {RD}  - vfs write:     /logs/backfill_progress.json{R}")
    f += out(f"  {DG}  ─────────────────────────────────────────────────────────────────────{R}")
    f += out(f"  {G}  + schema:        user_tier column preserved  {DG}(Phase 1 kept){R}")
    f += out(f"  {G}  + checkpoint:    pre-backfill state restored{R}")
    f += blank()
    f += [pause(300)]
    f += out(f"  {G}✓{R}  Rollback complete  {DG}(0.3s){R}  agent state = pre-backfill snapshot")
    f += blank()
    f += [pause(800)]

    # ── Scene 7: Analytics agents still running ───────────────────────────────
    f += section("ISOLATION CHECK — analytics agents unaffected")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos ls")
    f += blank()
    f += out(f"  {DG}agent_id             status     tag          note{R}")
    f += out(f"  {DG}───────────────────  ─────────  ───────────  ───────────────────────────{R}")
    f += out(f"  {Y}migration-agent{R}      {Y}restored{R}   migration    rolled back to pre-backfill")
    f += out(f"  {G}analytics-agent-1{R}    {G}running{R}    analytics    {DG}SELECT queries, unaffected{R}")
    f += out(f"  {G}analytics-agent-2{R}    {G}running{R}    analytics    {DG}SELECT queries, unaffected{R}")
    f += blank()
    f += out(f"  {G}✓{R}  Isolation confirmed.  analytics-agent-1 and analytics-agent-2 never paused.")
    f += out(f"  {DG}  KAOS VFS isolation: each agent's writes are fully sandboxed.{R}")
    f += blank()
    f += [pause(1200)]

    # ── Scene 8: Root cause analysis ──────────────────────────────────────────
    f += section("ROOT CAUSE ANALYSIS — kaos read migration-agent /logs/anomaly.md")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos read migration-agent /logs/anomaly.md")
    f += blank()
    f += out(f"  {B}# Anomaly Report — migration-agent  2026-04-10 02:14:47{R}")
    f += blank()
    f += out(f"  {B}## Summary{R}")
    f += out(f"  {DG}  64,412 rows returned NULL for user_tier after backfill.{R}")
    f += out(f"  {DG}  These users have no matching row in the subscription table.{R}")
    f += blank()
    f += out(f"  {B}## Root Cause{R}")
    f += out(f"  {DG}  The subscription table was created in 2021-03. Users who cancelled{R}")
    f += out(f"  {DG}  accounts BEFORE 2021-03 have no subscription record at all.{R}")
    f += out(f"  {DG}  The LEFT JOIN returns NULL rather than a default tier.{R}")
    f += blank()
    f += out(f"  {B}## Affected User IDs{R}")
    f += out(f"  {DG}  Legacy users (created < 2021-03-01):  64,412 accounts{R}")
    f += out(f"  {DG}  These are cancelled accounts with no active subscription.{R}")
    f += blank()
    f += out(f"  {B}## Fix{R}")
    f += out(f"  {G}  Use COALESCE: COALESCE(s.tier, 'free'){R}")
    f += out(f"  {G}  Legacy users without a subscription record → default to 'free'{R}")
    f += blank()
    f += [pause(1600)]

    # ── Scene 9: Retry with fix ───────────────────────────────────────────────
    f += section("RETRY WITH FIX — COALESCE(s.tier, 'free') for legacy users")
    f += blank()
    f += out(f"  {DG}[migration-agent]{R}  Updated query:")
    f += out(f"  {G}  UPDATE users u SET u.user_tier ={R}")
    f += out(f"  {G}    COALESCE((SELECT tier FROM subscription s WHERE s.user_id = u.id), 'free'){R}")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos run migration-agent -- 'run backfill_v2.sql'")
    f += blank()
    f += out(f"  {DG}[migration-agent]{R}  Starting retry backfill: 2,000,000 rows")
    f += [pause(300)]

    # Fast retry progress
    retry_steps = [
        ("500,000",  "25.0%", "4.1s"),
        ("1,000,000","50.0%", "8.2s"),
        ("1,500,000","75.0%","12.3s"),
        ("2,000,000","100.0%","16.4s"),
    ]
    for label, pct, elapsed in retry_steps:
        bar_filled = int(float(pct.rstrip('%')) / 100 * 30)
        bar = "█" * bar_filled + "░" * (30 - bar_filled)
        f += out(f"  {DG}[{bar}]{R}  {BY}{label:>9}{R} / 2,000,000  ({pct})  {DG}{elapsed}{R}", 180)

    f += blank()
    f += out(f"  {G}✓{R}  Backfill complete  {DG}(16.4s){R}  2,000,000 rows processed")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos run migration-agent -- 'SELECT COUNT(*) FROM users WHERE user_tier IS NULL'")
    f += blank()
    f += out(f"  {DG}count{R}")
    f += out(f"  {DG}─────{R}")
    f += out(f"  {BG}0{R}    {DG}← 0 NULLs  ✓{R}")
    f += blank()
    f += [pause(1000)]

    # ── Scene 10: Phase 3 checkpoint + SQL audit ──────────────────────────────
    f += section("PHASE 3 — Final checkpoint + SQL audit trail")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos checkpoint migration-agent --label post-backfill-success")
    f += out(f"  {G}✓{R}  Checkpoint  {DG}[post-backfill-success]{R}  created")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos --json query \"SELECT phase, rows_affected, status, duration_ms FROM migration_events ORDER BY id\"")
    f += blank()
    f += out(f"  {DG}phase               rows_affected   status     duration_ms{R}")
    f += out(f"  {DG}──────────────────  ─────────────   ─────────  ──────────{R}")
    f += out(f"  schema_change                    0   {G}success{R}        42")
    f += out(f"  checkpoint_pre_backfill          0   {G}success{R}        18")
    f += out(f"  backfill_v1              {Y}847,412{R}   {BR}anomaly{R}      7001")
    f += out(f"  rollback_to_pre_backfill {RD}847,412{R}   {G}success{R}       312  {DG}← 0.3s{R}")
    f += out(f"  backfill_v2            {G}2,000,000{R}   {G}success{R}     16412")
    f += out(f"  checkpoint_post_success          0   {G}success{R}        21")
    f += blank()
    f += out(f"  {BG}Migration complete.{R}  {G}2,000,000 rows.  0 NULLs.  Full audit trail preserved.{R}")
    f += blank()
    f += [pause(2500)]

    return f


# ── YAML output ────────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_yml = os.path.join(script_dir, "kaos_uc_migration.yml")

    records = build()
    config  = make_config("KAOS — Migrate 2M Rows, Detect Corruption at Row 847K, Rollback in 0.3s")

    doc = {"config": config, "records": records}
    with open(out_yml, "w", encoding="utf-8") as fh:
        yaml.dump(doc, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    total_ms = sum(r.get("delay", 0) for r in records)
    print(f"Written: {out_yml}")
    print(f"Frames:  {len(records)}")
    print(f"Est. duration: {total_ms/1000:.1f}s")
    print(f"\nRender with:")
    print(f"  uv run python render_gif.py kaos_uc_migration.yml")


if __name__ == "__main__":
    main()
