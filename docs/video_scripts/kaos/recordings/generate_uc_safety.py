"""
Generate a terminal recording: safety voting — human-in-the-loop blocks a risky action.

Story: An autonomous refactoring agent proposes to drop 3 legacy database tables.
The safety monitor approves. But the human supervisor (via policy + vote) rejects —
the tables are used by a reporting service that wasn't documented. The action is
blocked, saved in memory as a lesson, and the agent proposes a safer alternative.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_safety.py
    uv run python render_gif.py kaos_uc_safety.yml

Credits:
    Safety gate pattern inspired by LogAct (Balakrishnan et al. 2026, arXiv:2604.07988)
"""
import random
import yaml
import os

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

PROMPT = f"{G}>{R} "
CRLF   = "\r\n"

def pause(ms=500):
    return {"delay": ms, "content": ""}

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

def blank(delay=80):
    return [{"delay": delay, "content": CRLF}]

def section(title, delay=900):
    width = 74
    bar = "-" * width
    return [
        {"delay": delay, "content": f"{DG}  +{bar}+{R}{CRLF}"},
        {"delay": 60,    "content": f"{DG}  |{R}  {B}{CY}{title:<{width-2}}{R}  {DG}|{R}{CRLF}"},
        {"delay": 60,    "content": f"{DG}  +{bar}+{R}{CRLF}"},
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


def build():
    f = []

    # ── Title card ────────────────────────────────────────────────────────────
    f += [pause(600)]
    f += blank()
    f += out(f"  {B}{BC}KAOS — Safety Voting Gate{R}")
    f += out(f"  {DG}Human-in-the-loop blocks a risky table drop. Action saved to memory.{R}")
    f += blank()
    f += separator()

    # ── Scene 1: Policy setup ─────────────────────────────────────────────────
    f += section("Scene 1 — Human supervisor sets standing policy")
    f += prompt_line()
    f += type_cmd('kaos log append human-supervisor --type policy \\')
    f += type_cmd('  --payload \'{"rule": "Table drops require explicit human approval."}\'')
    f += blank(300)
    f += out(f"  {BY}policy recorded{R}  {DG}position=0{R}")
    f += blank(500)

    # ── Scene 2: Refactoring agent proposes dangerous action ──────────────────
    f += section("Scene 2 — refactor-agent proposes dropping 3 tables")
    f += blank()
    f += out(f"  {DG}[refactor-agent]  Analyzing schema... found 3 tables with 0 FK references.{R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd('kaos log intent refactor-agent "DROP TABLE legacy_sessions, temp_exports, old_audit"')
    f += blank(300)
    f += out(f"  {BY}intent_id=2{R}  {DG}position=1{R}")
    f += out(f"  {DG}action: DROP TABLE legacy_sessions, temp_exports, old_audit{R}")
    f += blank(500)

    # ── Scene 3: Safety monitor auto-approves ─────────────────────────────────
    f += section("Scene 3 — safety-monitor auto-approves (no FK refs found)")
    f += blank(300)
    f += out(f"  {DG}[safety-monitor]  Checking FK references for legacy_sessions... none found{R}")
    f += out(f"  {DG}[safety-monitor]  Checking FK references for temp_exports... none found{R}")
    f += out(f"  {DG}[safety-monitor]  Checking FK references for old_audit... none found{R}")
    f += blank(300)
    f += prompt_line()
    f += type_cmd('kaos log vote safety-monitor --intent 2 --approve true --reason "No FK deps found."')
    f += blank(200)
    f += out(f"  {G}APPROVED{R}  {DG}safety-monitor  ref=2{R}")
    f += blank(500)

    # ── Scene 4: Human supervisor rejects ────────────────────────────────────
    f += section("Scene 4 — Human supervisor REJECTS (undocumented reporting service)")
    f += blank()
    f += out(f"  {BR}[human-supervisor]  WAIT — legacy_sessions is used by the BI reporting{R}")
    f += out(f"  {BR}                    service. It's not documented in the schema. REJECT.{R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd('kaos log vote human-supervisor --intent 2 --approve false --reason "legacy_sessions used by undocumented BI service."')
    f += blank(300)
    f += out(f"  {RD}REJECTED{R}  {DG}human-supervisor  ref=2{R}")
    f += out(f"  {RD}reason: legacy_sessions used by undocumented BI service.{R}")
    f += blank(400)

    # ── Scene 5: Decision recorded, action blocked ────────────────────────────
    f += section("Scene 5 — Decision recorded, abort logged, lesson saved to memory")
    f += blank(300)
    f += out(f"  {BY}Tally:{R}  approve=1  {RD}reject=1{R}  {DG}(need 2 for table drops){R}")
    f += blank(300)
    f += prompt_line()
    f += type_cmd("kaos log decide refactor-agent --intent 2")
    f += blank(200)
    f += out(f"  {RD}decision: passed=False  (1 approve, 1 reject){R}")
    f += blank(300)
    f += prompt_line()
    f += type_cmd('kaos log append refactor-agent --type abort --ref 2 --payload \'{"reason": "Human veto: undocumented BI dependency."}\'')
    f += blank(300)
    f += out(f"  {RD}abort recorded{R}  {DG}position=5{R}")
    f += blank(400)
    f += out(f"  {DG}[refactor-agent]  Saving lesson to memory...{R}")
    f += prompt_line()
    f += type_cmd('kaos memory write refactor-agent "legacy_sessions table has undocumented BI dependency. Never drop without checking BI service." --type error --key legacy-sessions-dep')
    f += blank(300)
    f += out(f"  {BY}memory_id=1{R}  {DG}type=error  key=legacy-sessions-dep{R}")
    f += blank(600)

    # ── Scene 6: Agent proposes safer alternative ─────────────────────────────
    f += section("Scene 6 — Agent proposes safe alternative: rename + deprecate")
    f += blank()
    f += out(f"  {DG}[refactor-agent]  Proposing safer alternative: RENAME not DROP{R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd('kaos log intent refactor-agent "RENAME TABLE legacy_sessions -> _deprecated_legacy_sessions (keep data)"')
    f += blank(300)
    f += out(f"  {BY}intent_id=7{R}  {DG}position=6{R}")
    f += blank(300)
    f += prompt_line()
    f += type_cmd("kaos log vote safety-monitor --intent 7 --approve true")
    f += blank(200)
    f += out(f"  {G}APPROVED{R}")
    f += prompt_line()
    f += type_cmd('kaos log vote human-supervisor --intent 7 --approve true --reason "Rename preserves data. Approved."')
    f += blank(200)
    f += out(f"  {G}APPROVED{R}")
    f += blank(300)
    f += prompt_line()
    f += type_cmd("kaos log decide refactor-agent --intent 7")
    f += blank(200)
    f += out(f"  {BG}decision: passed=True  (2 approve, 0 reject){R}")
    f += blank(300)
    f += out(f"  {DG}[refactor-agent]  Renaming tables...{R}")
    f += out(f"  {BG}Done. 3 tables renamed, 0 rows deleted. BI service unaffected.{R}")
    f += blank(600)
    f += separator()
    f += blank()
    f += out(f"  {B}{BG}Safety Gate{R}  {DG}—{R}  autonomous agents can't act without consensus.")
    f += out(f"  {DG}Lessons saved to memory, audit trail immutable.{R}")
    f += out(f"  {DG}github.com/canivel/kaos   LogAct: arXiv:2604.07988{R}")
    f += blank()
    f += [pause(2000)]

    return {"config": make_config("KAOS — Safety Voting Gate"), "records": f}


if __name__ == "__main__":
    out_dir = os.path.dirname(__file__)
    data = build()
    path = os.path.join(out_dir, "kaos_uc_safety.yml")
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, sort_keys=False, width=200)
    print(f"Written: {path}  ({len(data['records'])} frames)")
