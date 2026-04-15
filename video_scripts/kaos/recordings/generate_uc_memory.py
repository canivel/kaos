"""
Generate a terminal recording: cross-agent memory — proposer learns from 3 prior sessions.

Story: A Meta-Harness search starts on a math benchmark. Before proposing, the agent
queries shared memory from 3 prior searches. It finds "ensemble voting improved accuracy
by 12%", avoids a known JSON parse error, and immediately proposes an improved harness
that skips failed patterns. Iteration 1 achieves 0.87 — what took 6 iterations before.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_memory.py
    uv run python render_gif.py kaos_uc_memory.yml

Credits:
    Memory system inspired by claude-mem (Alex Newman / @thedotmack)
    github.com/thedotmack/claude-mem  (AGPL-3.0)
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

PROMPT = f"{G}>\u001b[0m "
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
    f += out(f"  {B}{BC}KAOS — Cross-Agent Memory{R}  {DG}(powered by claude-mem){R}")
    f += out(f"  {DG}Proposer learns from 3 prior sessions before writing a single line.{R}")
    f += blank()
    f += separator()

    # ── Scene 1: Check memory from prior sessions ─────────────────────────────
    f += section("Scene 1 — Prior session memory is already in the store")
    f += prompt_line()
    f += type_cmd("kaos memory ls --type result --limit 5")
    f += blank(300)
    f += out(f"  {B}Memory Store{R}  total=18  observation=7  result=5  skill=3  error=3")
    f += blank()
    f += out(f"  {BY}#12{R}  {G}result{R}  {DG}search-01  2026-04-10 14:22{R}  {DG}key=iter6-best{R}")
    f += out(f"       Harness v6 achieved accuracy=0.872 using ensemble (3x Sonnet). {DG}cost=19.4{R}")
    f += blank()
    f += out(f"  {BY}#9{R}   {G}result{R}  {DG}search-01  2026-04-10 12:41{R}  {DG}key=iter3-best{R}")
    f += out(f"       Majority-vote with chain-of-thought. accuracy=0.831. Approach: parse...")
    f += blank()
    f += out(f"  {BY}#7{R}   {G}result{R}  {DG}search-01  2026-04-10 11:30{R}")
    f += out(f"       Temperature=0 improves determinism. accuracy=0.819.")
    f += blank()
    f += out(f"  {BY}#6{R}   {RD}error{R}   {DG}search-01  2026-04-10 11:12{R}  {DG}key=json-parse-fail{R}")
    f += out(f"       JSON decode error in 40% of cases. Always wrap output in try/except.")
    f += blank()
    f += out(f"  {BY}#3{R}   {MG}skill{R}   {DG}search-00  2026-04-09 09:15{R}  {DG}key=cot-numbered{R}")
    f += out(f"       Numbered chain-of-thought (Step 1, Step 2) reduces errors by 23%.")
    f += blank(500)

    # ── Scene 2: Full-text search ─────────────────────────────────────────────
    f += section("Scene 2 — Proposer searches memory before proposing")
    f += prompt_line()
    f += type_cmd('kaos memory search "ensemble accuracy"')
    f += blank(300)
    f += out(f"  {B}{BC}2 results{R}  (BM25 relevance order)")
    f += blank()
    f += out(f"  {BY}#12{R}  {G}result{R}  {DG}iter6-best{R}")
    f += out(f"       [math_rag] Improved harness at iteration 6. Scores: accuracy=0.872.")
    f += out(f"       Approach: ensemble voting with 3 Sonnet calls, temperature=0...")
    f += blank()
    f += out(f"  {BY}#9{R}   {G}result{R}  {DG}iter3-best{R}")
    f += out(f"       Majority-vote ensemble. accuracy=0.831. Chain-of-thought prompting.")
    f += blank(600)

    f += prompt_line()
    f += type_cmd('kaos memory search "error failure" --type error')
    f += blank(300)
    f += out(f"  {BY}#6{R}   {RD}error{R}  {DG}json-parse-fail{R}")
    f += out(f"       JSON decode error in 40% of cases. Always wrap output parsing in")
    f += out(f"       try/except with fallback to regex.")
    f += blank(500)

    # ── Scene 3: New search starts, proposer has prior context ────────────────
    f += section("Scene 3 — New search begins, proposer sees cross-session context")
    f += prompt_line()
    f += type_cmd("kaos mh start --benchmark math_rag --eval-subset 20")
    f += blank(400)
    f += out(f"  {DG}Evaluating 3 seed harnesses...{R}")
    f += out(f"  {DG}Seeds done. Frontier: accuracy=0.641{R}")
    f += blank()
    f += out(f"  {B}{CY}[proposer-iter-1]{R}  Building prompt with archive digest...")
    f += out(f"  {DG}Loading skills (3 entries)...{R}")
    f += out(f"  {CY}Loading cross-session memory (query: 'math_rag')...{R}")
    f += blank(400)
    f += out(f"  {DG}## Cross-Session Memory (from shared memory store){R}")
    f += out(f"  {DG}  [result]  accuracy=0.872  ensemble 3x Sonnet  iter6-best{R}")
    f += out(f"  {DG}  [result]  accuracy=0.831  majority-vote + CoT  iter3-best{R}")
    f += out(f"  {DG}  [error]   JSON decode error 40%  json-parse-fail{R}")
    f += out(f"  {DG}  [skill]   Numbered CoT reduces errors 23%  cot-numbered{R}")
    f += blank(600)
    f += out(f"  {B}[proposer-iter-1]{R}  Proposing harness using known-good patterns...")
    f += blank(300)
    f += out(f"  {DG}  Skipping naive single-call — known low accuracy{R}")
    f += out(f"  {DG}  Applying ensemble voting (learned from memory #12){R}")
    f += out(f"  {DG}  Adding try/except JSON fallback (learned from memory #6){R}")
    f += out(f"  {DG}  Adding numbered CoT (learned from skill #3){R}")
    f += blank(400)

    # ── Scene 4: Iteration 1 scores ───────────────────────────────────────────
    f += section("Scene 4 — Iteration 1 result: skip 6 iterations of trial-and-error")
    f += blank(300)
    f += out(f"  {DG}Evaluating candidate harness-a1b2c3d...{R}")
    f += blank(800)
    f += out(f"  {B}{BG}[harness-a1b2c3d]{R}  accuracy={BG}0.864{R}  {DG}cost=18.7  iter=1{R}")
    f += out(f"  {B}{BG}NEW FRONTIER POINT{R}  {DG}(was 0.641 — +34% in 1 iteration){R}")
    f += blank()
    f += out(f"  {DG}Memory: writing result to shared store...{R}")
    f += out(f"  {DG}  => memory_id=19  type=result  key=math_rag:iter1:a1b2c3d{R}")
    f += blank(500)
    f += out(f"  {B}{CY}Future searches on math_rag will start from accuracy=0.864{R}")
    f += out(f"  {DG}(memory persists across projects — kaos memory search 'math_rag'){R}")
    f += blank(600)

    # ── Scene 5: CLI memory stats ─────────────────────────────────────────────
    f += section("Scene 5 — Memory grows across sessions")
    f += prompt_line()
    f += type_cmd("kaos --json memory ls --type result | jq 'length'")
    f += blank(300)
    f += out(f"  {BG}6{R}  {DG}(6 result entries from 2 searches){R}")
    f += blank()
    f += prompt_line()
    f += type_cmd('kaos memory search "chain thought" --type skill')
    f += blank(300)
    f += out(f"  {BY}#3{R}   {MG}skill{R}  {DG}cot-numbered{R}")
    f += out(f"       Numbered chain-of-thought (Step 1, Step 2) reduces errors by 23%")
    f += out(f"       on multi-step arithmetic.")
    f += blank(600)
    f += separator()
    f += blank()
    f += out(f"  {B}{BG}Cross-Agent Memory{R}  {DG}—{R}  write once, search everywhere, across sessions.")
    f += out(f"  {DG}github.com/canivel/kaos{R}   {DG}  Credits: claude-mem by @thedotmack{R}")
    f += blank()
    f += [pause(2000)]

    return {"config": make_config("KAOS — Cross-Agent Memory"), "records": f}


if __name__ == "__main__":
    out_dir = os.path.dirname(__file__)
    data = build()
    path = os.path.join(out_dir, "kaos_uc_memory.yml")
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh, allow_unicode=True, sort_keys=False, width=200)
    print(f"Written: {path}  ({len(data['records'])} frames)")
