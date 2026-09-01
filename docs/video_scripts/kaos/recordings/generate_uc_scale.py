"""
Generate animated GIF: 847 Agents. One Codebase. $18.40.

Story: KAOS spawns 847 agents (one per file in a large Python 2 codebase),
runs the migration in parallel, agents roll back on failure, AAAK compression
saves tokens in real time, and a final SQL audit shows the full picture.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_scale.py

Output:
    kaos_uc_scale.gif  (same directory)
    ../../../docs/demos/kaos_uc_scale.gif  (website)
"""

import os
import sys
import pyte
from PIL import Image, ImageDraw, ImageFont

# ── Terminal dimensions ───────────────────────────────────────────────────────

COLS        = 220
ROWS        = 50
FONT_SIZE   = 13
LINE_HEIGHT = 19
CHAR_WIDTH  = 7
PAD_X       = 18
PAD_Y       = 44
TITLE_H     = 28
LOOP        = 0
MAX_DELAY   = 2000
FPS         = 8   # target frames per second

# ── GitHub dark theme palette ─────────────────────────────────────────────────

BG_COLOR  = (13,  17,  23)
FG_COLOR  = (201, 209, 217)
TITLE_BG  = (22,  27,  34)
TITLE_FG  = (139, 148, 158)
BTN_RED   = (255, 95,  86)
BTN_YLW   = (255, 189, 46)
BTN_GRN   = (39,  201, 63)

ANSI_COLORS = {
    30: (22,  27,  34),
    31: (255, 123, 114),
    32: (63,  185, 80),
    33: (227, 179, 65),
    34: (88,  166, 255),
    35: (188, 140, 255),
    36: (57,  197, 207),
    37: (181, 186, 196),
    90: (110, 118, 129),
    91: (255, 161, 152),
    92: (86,  211, 100),
    93: (227, 179, 65),
    94: (121, 192, 255),
    95: (210, 168, 255),
    96: (86,  212, 221),
    97: (240, 246, 252),
}

# ── ANSI escape helpers ───────────────────────────────────────────────────────

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

# ── Frame helpers ─────────────────────────────────────────────────────────────

def pause(ms=500):
    return [{"delay": ms, "content": ""}]

def out(text, delay=60):
    return [{"delay": delay, "content": text + CRLF}]

def blank(delay=70):
    return [{"delay": delay, "content": CRLF}]

def prompt_line():
    return [{"delay": 400, "content": CRLF + PROMPT}]

def type_cmd(cmd, delay_per_char=55):
    frames = []
    for ch in cmd:
        frames.append({"delay": delay_per_char, "content": ch})
    frames.append({"delay": 180, "content": CRLF})
    return frames

def sep(char="━", width=80, delay=300):
    return [{"delay": delay, "content": f"{DG}{char * width}{R}{CRLF}"}]

def header(title, delay=600):
    bar = "━" * 53
    return [
        {"delay": delay, "content": f"{B}{CY}{title}{R}{CRLF}"},
        {"delay": 60,    "content": f"{DG}{bar}{R}{CRLF}"},
    ]

# ── Progress bar helpers ──────────────────────────────────────────────────────

def progress_bar(done, total, width=20):
    filled = int(done / total * width) if total else 0
    bar = "█" * filled + "░" * (width - filled)
    return bar

# ── Scene builders ────────────────────────────────────────────────────────────

def scene1_mission_briefing():
    """Scene 1 — Mission briefing, ~2s / ~16 frames."""
    f = []
    f += pause(400)
    f += blank()
    f += blank()
    f += out(f"  {B}{CY}KAOS — Enterprise Python 2→3 Migration{R}")
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
    f += out(f"  {DG}Target:{R}    {BY}acme-platform/{R}  {DG}(847 Python files, 312K lines){R}")
    f += out(f"  {DG}Strategy:{R}  1 agent per file, full VFS isolation per agent")
    f += out(f"  {DG}Provider:{R}  {G}claude-sonnet-4-6{R}  {DG}(agent_sdk, no subprocess){R}")
    f += out(f"  {DG}Compress:{R}  {CY}AAAK level 5{R}  {DG}(57% token savings){R}")
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
    f += blank()
    f += pause(1200)
    return f

def scene2_mass_spawn():
    """Scene 2 — Mass spawn, ~6s / ~48 frames."""
    f = []
    f += prompt_line()
    f += type_cmd('kaos parallel --batch 50 --from ./acme-platform "migrate py2→py3"')
    f += blank()
    f += out(f"  {DG}Spawning {BY}847{R}{DG} agents in batches of 50...{R}")
    f += blank()

    batch_data = [
        (1,  17, 50, 50, "spawned ",  True),
        (2,  17, 50, 50, "spawned ",  True),
        (3,  17, 50, 50, "spawned ",  True),
        (4,  17, 50, 32, "spawning", False),
    ]

    for batch_num, total_batches, size, done, status, complete in batch_data:
        bar = progress_bar(done, size)
        if complete:
            color = G
            bar_colored = f"{G}{bar}{R}"
        else:
            bar_colored = f"{G}{'█' * 12}{DG}{'░' * 8}{R}"
        f += out(
            f"  {DG}Batch {batch_num:2d}/{total_batches}  [{size:2d} agents]{R}  "
            f"{color if complete else BY}{status}{R}  "
            f"{bar_colored}  {BY}{done}/{size}{R}",
            delay=180,
        )

    f += out(f"  {DG}Batch  5/17  [ 50 agents]  spawning {BY}████░░░░░░░░░░░░░░░░{R}  {BY}18/50{R}", 180)
    f += out(f"  {DG}...{R}", 120)
    f += blank()
    f += out(f"  {DG}[04:12]{R}  {BY}847 agents active{R}  {DG}│{R}  {DG}0 complete{R}  {DG}│{R}  {DG}0 failed{R}")
    f += blank()
    f += pause(1200)
    return f

def scene3_parallel_dashboard():
    """Scene 3 — Parallel execution dashboard, ~12s / ~96 frames."""
    f = []
    f += blank()
    f += out(f"  {B}{DG}[04:23]{R}  {B}{CY}MIGRATION IN PROGRESS{R}")
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")

    # Animate progress across several ticks
    states = [
        (127, 698,  8,  14,  15.0),
        (198, 621, 11,  17,  23.4),
        (274, 543, 13,  17,  32.3),
        (361, 454, 15,  17,  42.6),
        (447, 367, 17,  16,  52.8),
        (542, 270, 19,  16,  64.0),
        (638, 172, 21,  16,  75.3),
        (729,  79, 24,  15,  86.1),
    ]

    recent_lines = [
        f"  {G}[✓]{R} api/users.py          {CY}print→print(){R}   {DG}+3 tests pass{R}",
        f"  {G}[✓]{R} core/models.py        {CY}unicode→str{R}     {DG}+7 tests pass{R}",
        f"  {G}[✓]{R} utils/parser.py       {CY}dict.items(){R}    {DG}+2 tests pass{R}",
        f"  {Y}[↺]{R} db/legacy.py          {Y}ROLLBACK{R}        {DG}import error detected{R}",
        f"  {G}[✓]{R} api/auth.py           {CY}xrange→range{R}    {DG}+4 tests pass{R}",
        f"  {Y}[↺]{R} ml/pipeline.py        {Y}ROLLBACK{R}        {DG}test regression (-12%){R}",
        f"  {G}[✓]{R} services/billing.py   {CY}basestring→str{R}  {DG}+5 tests pass{R}",
    ]

    for idx, (complete, running, failed, rolled, pct) in enumerate(states):
        # Overwrite the status section using ANSI cursor tricks
        # We emit the block each time; pyte will scroll it naturally
        bar_c = progress_bar(complete, 847, 20)
        bar_r = progress_bar(running, 847, 20)
        elapsed_min = 4
        elapsed_sec = 23 + idx * 12
        if elapsed_sec >= 60:
            elapsed_min += elapsed_sec // 60
            elapsed_sec %= 60
        ts = f"[{elapsed_min:02d}:{elapsed_sec:02d}]"

        f += out(f"  {DG}{ts}{R}  {B}{CY}MIGRATION IN PROGRESS{R}")
        f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
        f += out(f"  {G}Complete {R} {G}{bar_c}{R}  {BY}{complete:3d} / 847{R}   {DG}({pct:.1f}%){R}")
        f += out(f"  {DG}Running  {R} {DG}{bar_r}{R}  {DG}{running:3d} / 847{R}")
        f += out(f"  {RD}Failed   {R} {DG}{'░'*20}{R}  {RD}{failed:3d} / 847{R}")
        f += out(f"  {Y}Rolled   {R} {DG}{'░'*20}{R}  {Y}{rolled:3d} / 847{R}")
        f += blank(50)
        f += out(f"  {DG}Recent completions:{R}")
        # Show progressively more recent lines
        show_lines = recent_lines[:min(idx + 2, len(recent_lines))]
        for line in show_lines:
            f += out(line, delay=50)
        f += blank(50)
        f += pause(600)

    f += blank()
    f += pause(800)
    return f

def scene4_aaak_compression():
    """Scene 4 — AAAK compression, ~10s / ~80 frames."""
    f = []
    f += blank()
    f += out(f"  {DG}[05:41]{R}  {B}{CY}AAAK COMPRESSION — LIVE TOKEN SAVINGS{R}")
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
    f += blank()

    # Animate the numbers counting up as agents complete
    checkpoints = [
        (312,  866_292, 2.60,  4_104_409, 12.31, 1_765_148,  5.30, 2_339_261, 7.01),
        (418, 1_161_482, 3.48, 5_501_886, 16.51, 2_366_002,  7.10, 3_135_884, 9.41),
        (531, 1_474_788, 4.42, 6_986_457, 20.96, 3_005_177,  9.02, 3_981_280, 11.94),
        (624, 1_733_472, 5.20, 8_211_288, 24.63, 3_533_524, 10.60, 4_677_764, 14.03),
        (729, 2_024_604, 6.07, 9_598_383, 28.80, 4_130_285, 12.39, 5_468_098, 16.40),
        (791, 2_197_164, 6.59, 10_413_977, 31.24, 4_480_788, 13.44, 5_933_189, 17.80),
    ]

    for agents_done, saved_tok, saved_cost, without_tok, without_cost, with_tok, with_cost, net_tok, net_cost in checkpoints:
        f += out(f"  {DG}Agents completed so far:{R}  {BY}{agents_done}{R} / 847")
        f += blank(40)
        f += out(f"  {B}Per-agent digest stats:{R}")
        f += out(f"    {DG}Uncompressed avg:{R}   {BY}4,847{R} tokens")
        f += out(f"    {DG}AAAK compressed:{R}    {G}2,084{R} tokens   {G}(-57%){R}")
        f += blank(40)
        f += out(f"  {B}Cumulative savings:{R}")
        f += out(f"    {DG}Tokens saved:{R}       {BG}{saved_tok:>10,}{R}")
        f += out(f"    {DG}Cost saved:{R}         {BG}${saved_cost:.2f}{R}  {DG}at $3/M tokens{R}")
        f += blank(40)
        f += out(f"  {B}Projection (847 agents total):{R}")
        f += out(f"    {DG}Without AAAK:{R}   {BR}{without_tok:>12,}{R} tokens  →  {BR}${without_cost:.2f}{R}")
        f += out(f"    {DG}With AAAK:   {R}   {G}{with_tok:>12,}{R} tokens  →  {G}${with_cost:.2f}{R}")
        f += out(f"    {DG}Savings:     {R}   {BG}{net_tok:>12,}{R} tokens  →  {BG}${net_cost:.2f}{R}  {DG}(56.9%){R}")
        f += blank(40)
        f += out(f"  {DG}Checkpoint storage: 847 VFS snapshots  →  214 MB{R}")
        f += out(f"  {DG}Deduplication:       68% blob reuse across agents  →  147 MB saved{R}")
        f += blank(40)
        f += pause(900)

    f += pause(600)
    return f

def scene5_rollback():
    """Scene 5 — Rollback in action, ~10s / ~80 frames."""
    f = []
    f += blank()
    f += out(f"  {DG}[06:18]{R}  {B}{Y}ROLLBACK EVENT — db/connections.py{R}")
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
    f += out(f"  {DG}Agent:{R}  {BY}migrate-db-connections{R}  {DG}[vfs_id=mig-4f8a]{R}")
    f += blank()
    f += out(f"  {B}Migration applied:{R}", 80)
    f += out(f"    {DG}- replaced:{R}  {CY}has_key(){R}  {DG}→{R}  {CY}'key' in dict{R}", 70)
    f += out(f"    {DG}- replaced:{R}  {CY}iteritems(){R}  {DG}→{R}  {CY}items(){R}", 70)
    f += out(f"    {DG}- replaced:{R}  {CY}print stmt{R}  {DG}→{R}  {CY}print(){R}", 70)
    f += blank()
    f += out(f"  {B}Post-migration test run:{R}", 200)
    f += out(f"    {RD}FAILED test_connection_pool{R}  {DG}—{R}  {BR}AttributeError: 'NoneType'{R}", 120)
    f += out(f"    {RD}FAILED test_reconnect_logic{R}  {DG}—{R}  {BR}TypeError: sequence expected{R}", 120)
    f += blank()
    f += out(f"    {RD}2 failed{R}, {G}14 passed{R}  {BY}← REGRESSION DETECTED{R}", 200)
    f += blank()
    f += out(f"  {BY}Initiating rollback...{R}", 300)
    f += out(f"    {DG}kaos restore migrate-db-connections --label pre-migration{R}", 80)
    f += blank()
    f += out(f"  {G}✓{R}  {G}Restored in 0.08s{R}", 400)
    f += out(f"  {G}✓{R}  {DG}847 other agents: {G}UNAFFECTED{R}", 100)
    f += blank()
    f += out(f"  {DG}Root cause written to /qa/report.md:{R}", 150)
    f += out(f"    {DG}\"has_key() removal broke conditional in line 94{R}")
    f += out(f"     {DG}where dict may be None — needs guard before migration\"{R}")
    f += blank()
    f += pause(1400)
    return f

def scene6_hub_coordination():
    """Scene 6 — Agents coordinate via hub, ~8s / ~64 frames."""
    f = []
    f += blank()
    f += out(f"  {DG}[07:02]{R}  {B}{BC}HUB COORDINATION — PATTERN SHARING{R}")
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
    f += out(f"  {DG}Patterns discovered and shared to hub:{R}")
    f += blank()

    skills = [
        (
            "none_guard_before_has_key",
            "migrate-db-connections (after rollback)",
            "23 agents with similar dict patterns",
            "23 pre-emptive fixes applied, 0 rollbacks",
        ),
        (
            "unicode_literal_u_prefix",
            "migrate-api-serializers",
            "147 agents touching serialization",
            "prevented ~140 potential regressions",
        ),
        (
            "six_compatibility_layer",
            "migrate-core-compat",
            "89 agents touching py2/py3 compat shims",
            None,
        ),
    ]

    for skill_name, discovered_by, shared_to, result in skills:
        f += out(f"  {DG}[skill]{R}  {BG}{skill_name}{R}", 200)
        f += out(f"    {DG}Discovered by:{R}  {BY}{discovered_by}{R}", 80)
        f += out(f"    {DG}Shared to:    {R}  {CY}{shared_to}{R}", 80)
        if result:
            f += out(f"    {DG}Result:       {R}  {G}{result}{R}", 80)
        f += blank(60)
        f += pause(500)

    f += out(f"  {B}Hub stats:{R}")
    f += out(f"    {DG}Skills shared:     {R}  {BY}12{R} patterns")
    f += out(f"    {DG}Agents benefited:  {R}  {BY}394{R} / 847  {DG}(46%){R}")
    f += out(f"    {DG}Regressions prevented via hub:{R}  {G}~180 estimated{R}")
    f += blank()
    f += pause(1000)
    return f

def scene7_final_results():
    """Scene 7 — Final results, ~12s / ~96 frames."""
    f = []
    f += blank()
    f += out(f"  {DG}[08:47]{R}  {B}{BG}MIGRATION COMPLETE{R}")
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
    f += blank()

    # Animate lines filling in one by one with delays
    f += out(f"  {B}Total agents:{R}    {BY}847{R}", 120)
    f += blank(60)
    f += out(f"  {B}Outcome:{R}", 200)
    f += out(f"    {G}✓ Successful:{R}   {BG}809{R}  {DG}(95.5%){R}", 150)
    f += out(f"    {Y}↺ Rolled back:{R}   {BY}31{R}  {DG}( 3.7%){R}", 150)
    f += out(f"    {RD}✗ Failed:{R}         {RD}7{R}  {DG}( 0.8%){R}", 150)
    f += blank(80)
    f += out(f"  {B}Code quality:{R}", 250)
    f += out(f"    {DG}Files migrated:{R}   {G}809{R} / 847", 120)
    f += out(f"    {DG}Tests passing:{R}  {BG}6,847{R} / 6,847  {G}(100% of affected){R}", 120)
    f += out(f"    {DG}Regressions:{R}        {G}0{R}  {DG}(31 caught and rolled back){R}", 120)
    f += blank(80)
    f += out(f"  {B}Time:{R}", 250)
    f += out(f"    {DG}Wall clock:{R}      {BY}8m 47s{R}  {DG}(parallel){R}", 120)
    f += out(f"    {DG}Sequential est:{R}  {DG}~18 days{R}  {DG}(human){R}  {DG}│{R}  {DG}~4.2h{R}  {DG}(sequential AI){R}", 120)
    f += blank(80)
    f += out(f"  {B}Token usage:{R}", 250)
    f += out(f"    {DG}Total tokens:{R}    {BY}1,847,293{R}", 120)
    f += out(f"    {DG}Without AAAK:{R}    {DG}4,298,356{R}  {DG}(estimated){R}", 120)
    f += out(f"    {DG}AAAK savings:{R}    {BG}2,451,063 tokens{R}  {DG}→{R}  {BG}$7.35 saved{R}", 120)
    f += blank(80)
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
    f += out(f"  {B}Total cost:{R}    {BG}$18.40{R}", 400)
    f += out(f"  {B}Cost per file:{R}  {G}$0.022 / file{R}", 200)
    f += out(f"  {DG}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{R}")
    f += blank()
    f += pause(2200)
    return f

def scene8_sql_audit():
    """Scene 8 — SQL audit query, ~8s / ~64 frames."""
    f = []
    f += prompt_line()
    f += type_cmd('kaos --json query "')
    f += type_cmd('  SELECT outcome, COUNT(*) as files,')
    f += type_cmd('    SUM(lines_changed) as total_lines,')
    f += type_cmd('    AVG(tokens_used) as avg_tokens')
    f += type_cmd('  FROM migration_results')
    f += type_cmd('  GROUP BY outcome')
    f += type_cmd('  ORDER BY files DESC"')
    f += blank()
    f += out(f"  {B}outcome     {R}  {B}files{R}   {B}total_lines{R}   {B}avg_tokens{R}", 80)
    f += out(f"  {DG}─────────────────────────────────────────────{R}", 60)
    f += out(f"  {G}success    {R}    {BY}809{R}    {BY}187,432{R}       {BY}2,181{R}", 150)
    f += out(f"  {Y}rolled_back{R}     {BY}31{R}      {BY}4,847{R}       {BY}3,412{R}", 150)
    f += out(f"  {RD}failed     {R}      {BY}7{R}        {BY}891{R}       {BY}1,204{R}", 150)
    f += blank()
    f += pause(600)
    f += prompt_line()
    f += type_cmd('kaos --json query "')
    f += type_cmd('  SELECT file_path, rollback_reason')
    f += type_cmd('  FROM migration_results')
    f += type_cmd('  WHERE outcome = \'rolled_back\'')
    f += type_cmd('  ORDER BY rollback_reason"')
    f += blank()
    f += out(f"  {DG}[31 rows — all with root cause, all queryable forever]{R}", 200)
    f += blank()
    f += prompt_line()
    f += type_cmd('echo "Full audit: 847 agents, every write, every rollback"')
    f += out(f"  {G}Full audit: 847 agents, every write, every rollback{R}", 200)
    f += prompt_line()
    f += type_cmd('echo "One SQLite file. 214MB. Copy it anywhere."')
    f += out(f"  {G}One SQLite file. 214MB. Copy it anywhere.{R}", 200)
    f += blank()
    f += pause(2500)
    return f

# ── Build full frame list ─────────────────────────────────────────────────────

def build():
    frames = []
    frames += scene1_mission_briefing()
    frames += scene2_mass_spawn()
    frames += scene3_parallel_dashboard()
    frames += scene4_aaak_compression()
    frames += scene5_rollback()
    frames += scene6_hub_coordination()
    frames += scene7_final_results()
    frames += scene8_sql_audit()
    return frames

# ── Font loading ──────────────────────────────────────────────────────────────

def load_font(size):
    candidates = [
        "C:/Windows/Fonts/consola.ttf",
        "C:/Windows/Fonts/cour.ttf",
        "C:/Windows/Fonts/lucon.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()

# ── pyte terminal emulation ───────────────────────────────────────────────────

def make_screen():
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)
    return screen, stream

def feed(stream, content):
    stream.feed(content.encode("utf-8", errors="replace"))

# ── ANSI color resolution ─────────────────────────────────────────────────────

def resolve_color(color_attr, default):
    if color_attr is None or color_attr == "default":
        return default
    if isinstance(color_attr, str):
        name_map = {
            "black":   ANSI_COLORS[30],
            "red":     ANSI_COLORS[31],
            "green":   ANSI_COLORS[32],
            "brown":   ANSI_COLORS[33],
            "blue":    ANSI_COLORS[34],
            "magenta": ANSI_COLORS[35],
            "cyan":    ANSI_COLORS[36],
            "white":   ANSI_COLORS[37],
        }
        return name_map.get(color_attr, default)
    if isinstance(color_attr, int):
        return ANSI_COLORS.get(color_attr, default)
    return default

# ── Frame rendering ───────────────────────────────────────────────────────────

def render_frame(screen, font, font_bold, char_w, line_h, img_w, img_h, title):
    img  = Image.new("RGB", (img_w, img_h), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # Title bar
    draw.rectangle([0, 0, img_w, TITLE_H], fill=TITLE_BG)
    draw.text((PAD_X, 7), title, font=font, fill=TITLE_FG)
    for i, col in enumerate([BTN_RED, BTN_YLW, BTN_GRN]):
        cx = img_w - 22 - i * 18
        draw.ellipse([cx - 5, TITLE_H // 2 - 5, cx + 5, TITLE_H // 2 + 5], fill=col)

    # Terminal content
    for row_idx in range(ROWS):
        y    = PAD_Y + row_idx * line_h
        line = screen.buffer[row_idx]
        x    = PAD_X
        for col_idx in range(COLS):
            char = line[col_idx]
            ch   = char.data if char.data else " "
            fg   = resolve_color(char.fg, FG_COLOR)
            bg   = resolve_color(char.bg, BG_COLOR)
            bold = getattr(char, "bold", False)

            if bg != BG_COLOR:
                draw.rectangle([x, y, x + char_w, y + line_h], fill=bg)
            use_font = font_bold if bold else font
            if ch.strip():
                draw.text((x, y + 2), ch, font=use_font, fill=fg)
            x += char_w

    return img

# ── GIF assembly ──────────────────────────────────────────────────────────────

def save_gif(gif_frames, out_path):
    """gif_frames: list of (PIL.Image, delay_ms)."""
    images    = [f[0].convert("P", palette=Image.ADAPTIVE, colors=256) for f in gif_frames]
    durations = [max(20, min(f[1], MAX_DELAY)) // 10 * 10 for f in gif_frames]
    images[0].save(
        out_path,
        save_all=True,
        append_images=images[1:],
        optimize=False,
        duration=durations,
        loop=LOOP,
    )

# ── Main pipeline ─────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_local  = os.path.join(script_dir, "kaos_uc_scale.gif")
    out_docs   = os.path.join(script_dir, "..", "..", "..", "docs", "demos", "kaos_uc_scale.gif")
    out_docs   = os.path.normpath(out_docs)

    title = "KAOS — 847 Agents. One Codebase. $18.40."

    # Load font and measure dimensions
    font      = load_font(FONT_SIZE)
    font_bold = load_font(FONT_SIZE)

    char_w   = CHAR_WIDTH
    line_h   = LINE_HEIGHT
    try:
        bbox   = font.getbbox("M")
        char_w = bbox[2] - bbox[0]
        line_h = int((bbox[3] - bbox[1]) * 1.55)
    except Exception:
        pass

    img_w = PAD_X * 2 + COLS * char_w
    img_h = PAD_Y + ROWS * line_h + 12

    print(f"Terminal: {COLS}x{ROWS}  |  Image: {img_w}x{img_h}")

    # Build frame records
    records = build()
    total_ms = sum(r.get("delay", 0) for r in records)
    print(f"Frame records: {len(records)}  |  Est. duration: {total_ms / 1000:.1f}s")

    # Emulate terminal and render frames
    screen, stream = make_screen()
    gif_frames     = []
    prev_bytes     = None

    for idx, record in enumerate(records):
        delay   = int(record.get("delay", 80))
        content = record.get("content", "")

        if content:
            feed(stream, content)

        img       = render_frame(screen, font, font_bold, char_w, line_h, img_w, img_h, title)
        img_bytes = img.tobytes()

        if prev_bytes is None or img_bytes != prev_bytes:
            gif_frames.append((img, max(delay, 30)))
            prev_bytes = img_bytes
        else:
            if gif_frames:
                last_img, last_delay = gif_frames[-1]
                gif_frames[-1] = (last_img, last_delay + delay)

        if (idx + 1) % 100 == 0:
            print(f"  Processed {idx + 1}/{len(records)} records  ({len(gif_frames)} unique frames)")

    # Hold on last frame
    if gif_frames:
        last_img, last_delay = gif_frames[-1]
        gif_frames[-1] = (last_img, last_delay + 2500)

    print(f"Unique frames: {len(gif_frames)}")

    # Save GIFs
    for out_path in [out_local, out_docs]:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        print(f"Saving: {out_path} ...")
        save_gif(gif_frames, out_path)
        size_kb = os.path.getsize(out_path) // 1024
        print(f"  Saved: {out_path}  ({len(gif_frames)} frames, {size_kb} KB)")

    print("\nDone.")


if __name__ == "__main__":
    main()
