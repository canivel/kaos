"""
Generate a terminal recording: shared log — 4 agents coordinate a database migration.

Story: A data team has 4 agents running in parallel. One proposes a risky schema
migration. The others vote via the shared log. One rejects. The proposer sees the
thread, reads the reason, and rewrites the migration safely before committing.
The full audit trail is queryable as SQL.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_shared_log.py
    uv run python render_gif.py kaos_uc_shared_log.yml

Credits:
    LogAct protocol by Balakrishnan et al. 2026 (arXiv:2604.07988, Meta)
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
    f += out(f"  {B}{BC}KAOS — Shared Log (LogAct Protocol){R}")
    f += out(f"  {DG}4 agents coordinate a database migration via intent/vote/decide.{R}")
    f += blank()
    f += separator()

    # ── Scene 1: Supervisor injects policy ───────────────────────────────────
    f += section("Scene 1 — Supervisor injects a standing safety policy")
    f += prompt_line()
    f += type_cmd('kaos log append supervisor --type policy --payload \'{"rule": "Schema migrations require 2 approvals."}\'')
    f += blank(300)
    f += out(f"  {DG}position=0  type=policy  agent=supervisor{R}")
    f += out(f"  {DG}rule: Schema migrations require 2 approvals.{R}")
    f += blank(500)

    # ── Scene 2: Agent declares intent ───────────────────────────────────────
    f += section("Scene 2 — data-agent declares migration intent")
    f += prompt_line()
    f += type_cmd('kaos log intent data-agent "ALTER TABLE events ADD COLUMN batch_id TEXT"')
    f += blank(300)
    f += out(f"  {BY}intent_id=2{R}  {DG}position=1  agent=data-agent{R}")
    f += out(f"  {DG}action: ALTER TABLE events ADD COLUMN batch_id TEXT{R}")
    f += blank(500)

    # ── Scene 3: Peers vote ───────────────────────────────────────────────────
    f += section("Scene 3 — Peers cast votes")
    f += blank()
    f += out(f"  {DG}[research-agent-A]  reading log...{R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd('kaos log vote research-agent-A --intent 2 --approve true --reason "Additive migration, safe."')
    f += blank(300)
    f += out(f"  {G}APPROVED{R}  {DG}position=2  research-agent-A  ref=2{R}")
    f += blank(400)
    f += out(f"  {DG}[safety-monitor]  reading log...{R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd('kaos log vote safety-monitor --intent 2 --approve false --reason "NULL default violates NOT NULL constraint on 50M rows."')
    f += blank(300)
    f += out(f"  {RD}REJECTED{R}  {DG}position=3  safety-monitor  ref=2{R}")
    f += out(f"  {RD}reason: NULL default violates NOT NULL constraint on 50M rows.{R}")
    f += blank(600)

    # ── Scene 4: Tally ────────────────────────────────────────────────────────
    f += section("Scene 4 — View the vote thread and decide")
    f += prompt_line()
    f += type_cmd("kaos log tail --n 5")
    f += blank(300)
    f += out(f"  {DG} 0  [POLICY  ]  supervisor{R}")
    f += out(f"  {DG}       rule: Schema migrations require 2 approvals.{R}")
    f += out(f"  {DG} 1  [INTENT  ]  data-agent{R}")
    f += out(f"  {DG}       action: ALTER TABLE events ADD COLUMN batch_id TEXT{R}")
    f += out(f"  {DG} 2  [VOTE    ]  research-agent-A  ref=2{R}")
    f += out(f"  {G}       approve: True  reason: Additive migration, safe.{R}")
    f += out(f"  {DG} 3  [VOTE    ]  safety-monitor  ref=2{R}")
    f += out(f"  {RD}       approve: False  reason: NULL default violates NOT NULL constraint...{R}")
    f += blank(600)
    f += out(f"  {BY}Tally for intent #2:{R}  approve=1  reject=1  {RD}passed=False{R}  {DG}(need 2){R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd("kaos log decide data-agent --intent 2")
    f += blank(300)
    f += out(f"  {DG}position=4  type=decision  passed=False  (1 approve, 1 reject){R}")
    f += blank(500)

    # ── Scene 5: Agent revises and re-proposes ────────────────────────────────
    f += section("Scene 5 — Agent reads rejection reason, rewrites migration safely")
    f += blank()
    f += out(f"  {DG}[data-agent]  safety-monitor rejected: NULL default violates NOT NULL...{R}")
    f += out(f"  {DG}[data-agent]  Revision: add DEFAULT '' to satisfy NOT NULL{R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd("kaos log intent data-agent \"ALTER TABLE events ADD COLUMN batch_id TEXT NOT NULL DEFAULT ''\"" )
    f += blank(300)
    f += out(f"  {BY}intent_id=6{R}  {DG}position=5  new intent (revised){R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd("kaos log vote research-agent-A --intent 6 --approve true")
    f += blank(200)
    f += out(f"  {G}APPROVED{R}  {DG}position=6{R}")
    f += prompt_line()
    f += type_cmd("kaos log vote safety-monitor --intent 6 --approve true --reason 'NOT NULL DEFAULT is safe.'")
    f += blank(200)
    f += out(f"  {G}APPROVED{R}  {DG}position=7{R}")
    f += blank(400)
    f += prompt_line()
    f += type_cmd("kaos log decide data-agent --intent 6")
    f += blank(300)
    f += out(f"  {BG}position=8  type=decision  passed=True  (2 approve, 0 reject){R}")
    f += blank(300)
    f += out(f"  {DG}[data-agent]  executing migration...{R}")
    f += blank(600)
    f += prompt_line()
    f += type_cmd('kaos log append data-agent --type commit --ref 6 --payload \'{"summary": "ALTER TABLE done. 50M rows updated."}\'')
    f += blank(300)
    f += out(f"  {BG}position=9  type=commit  ref=6{R}")
    f += out(f"  {BG}summary: ALTER TABLE done. 50M rows updated.{R}")
    f += blank(600)

    # ── Scene 6: Full audit trail ─────────────────────────────────────────────
    f += section("Scene 6 — Full immutable audit trail for compliance")
    f += prompt_line()
    f += type_cmd("kaos log ls")
    f += blank(300)
    f += out(f"  {B}Shared Log{R}  total=10")
    f += out(f"    commit    1")
    f += out(f"    decision  2")
    f += out(f"    intent    2")
    f += out(f"    policy    1")
    f += out(f"    vote      4")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos query \"SELECT type, agent_id, created_at FROM shared_log ORDER BY position\"")
    f += blank(300)
    f += out(f"  {DG}type        agent            created_at{R}")
    f += out(f"  {DG}policy      supervisor       2026-04-10T14:00:01{R}")
    f += out(f"  {DG}intent      data-agent       2026-04-10T14:00:12{R}")
    f += out(f"  {G}vote        research-agent-A 2026-04-10T14:00:31{R}")
    f += out(f"  {RD}vote        safety-monitor   2026-04-10T14:00:44{R}")
    f += out(f"  {RD}decision    data-agent       2026-04-10T14:00:55{R}")
    f += out(f"  {DG}intent      data-agent       2026-04-10T14:01:12{R}")
    f += out(f"  {G}vote        research-agent-A 2026-04-10T14:01:28{R}")
    f += out(f"  {G}vote        safety-monitor   2026-04-10T14:01:35{R}")
    f += out(f"  {BG}decision    data-agent       2026-04-10T14:01:42{R}")
    f += out(f"  {BG}commit      data-agent       2026-04-10T14:02:01{R}")
    f += blank(600)
    f += separator()
    f += blank()
    f += out(f"  {B}{BG}Shared Log{R}  {DG}—{R}  every agent action voted on, recorded, auditable.")
    f += out(f"  {DG}github.com/canivel/kaos{R}   {DG}  LogAct: arXiv:2604.07988{R}")
    f += blank()
    f += [pause(2000)]

    return {"config": make_config("KAOS — Shared Log (LogAct)"), "records": f}


if __name__ == "__main__":
    out_dir = os.path.dirname(__file__)
    data = build()
    path = os.path.join(out_dir, "kaos_uc_shared_log.yml")
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, sort_keys=False, width=200)
    print(f"Written: {path}  ({len(data['records'])} frames)")
