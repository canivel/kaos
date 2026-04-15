"""
Generate a terminal recording: New model version — catch the 8% regression before it ships.

Story: New claude-sonnet version deployed. Before swapping in production, KAOS automatically
re-runs 5 benchmarks and diffs vs baseline checkpoint. Finds 8% regression on code_review,
3% on sentiment. Blocks the deploy. Auto-remediates via Meta-Harness. Deploy approved.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_regression.py
    uv run python render_gif.py kaos_uc_regression.yml
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

    # ── Scene 1: Title card — CI pipeline ────────────────────────────────────
    f += [pause(600)]
    f += out(f"")
    f += out(f"")
    f += out(f"  {B}{CY}KAOS — Model Regression Suite{R}  {DG}—{R}  {WH}Catch Regressions Before They Ship{R}")
    f += out(f"")
    f += out(f"  {DG}CI pipeline triggered:{R}")
    f += out(f"  {BY}  Model version updated:{R}  claude-sonnet-4-5  {DG}→{R}  {G}claude-sonnet-4-6{R}")
    f += out(f"  {DG}  Action: running regression suite before swap...{R}")
    f += out(f"")
    f += out(f"  {DG}Benchmarks:{R}  text_classify  │  code_review  │  sentiment  │  math_qa  │  tool_calling")
    f += out(f"  {DG}Baseline:{R}    checkpoint  {DG}[baseline-v45]{R}  {DG}(scores from claude-sonnet-4-5){R}")
    f += out(f"  {DG}Threshold:{R}   -5% regression blocks deploy{R}")
    f += out(f"")
    f += [pause(3000)]

    # ── Scene 2: Step 1 — Run regression suite ────────────────────────────────
    f += section("STEP 1 — Run regression suite: 5 benchmarks in parallel")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos parallel run regression-check-v46 -- 'run benchmarks text_classify code_review sentiment math_qa tool_calling'")
    f += blank()
    f += out(f"  {DG}Loading baseline checkpoint:  baseline-v45{R}")
    f += out(f"  {DG}Model under test:             claude-sonnet-4-6{R}")
    f += blank()
    f += out(f"  {G}✓{R}  text_classify    spawned  {DG}[200 examples, 4 classes]{R}")
    f += out(f"  {G}✓{R}  code_review      spawned  {DG}[200 examples, BLOCKER/IMPORTANT/STYLE/PRAISE]{R}")
    f += out(f"  {G}✓{R}  sentiment        spawned  {DG}[150 examples, pos/neu/neg]{R}")
    f += out(f"  {G}✓{R}  math_qa          spawned  {DG}[100 examples, numeric answers]{R}")
    f += out(f"  {G}✓{R}  tool_calling     spawned  {DG}[80 examples, function selection]{R}")
    f += blank()
    f += out(f"  {DG}Running 5 benchmarks in parallel against claude-sonnet-4-6...{R}", 200)
    f += blank()
    f += [pause(1500)]

    # ── Scene 3: Results coming in ────────────────────────────────────────────
    f += section("STEP 2 — Results coming in")
    f += blank()
    f += out(f"  {DG}benchmark        score_v46   baseline_v45   delta     status{R}")
    f += out(f"  {DG}───────────────  ─────────   ────────────   ───────   ──────────────────{R}")
    f += [pause(400)]

    benchmarks = [
        ("text_classify ", "0.87", "0.87", "  0.0%", DG, "NO CHANGE",    DG,  " "),
        ("tool_calling  ", "0.91", "0.88", " +3.4%", G,  "IMPROVED",     G,   "✓"),
        ("math_qa       ", "0.76", "0.74", " +2.7%", G,  "IMPROVED",     G,   "✓"),
        ("sentiment     ", "0.81", "0.83", " -2.4%", Y,  "REGRESSION",   Y,   "⚠"),
        ("code_review   ", "0.76", "0.83", " -8.4%", BR, "REGRESSION ✗", BR,  "✗"),
    ]
    for bm, score, baseline, delta, dcolor, status, scolor, mark in benchmarks:
        f += out(f"  {mark}  {bm}  {score}       {DG}{baseline}{R}        {dcolor}{delta}{R}   {scolor}{status}{R}", 500)
        f += [pause(600)]

    f += blank()
    f += [pause(1400)]

    # ── Scene 4: Deep dive on code_review ─────────────────────────────────────
    f += section("STEP 3 — Deep dive: code_review regression (-8.4%)")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos diff baseline-v45 regression-check-v46 /results/code_review_failures.md")
    f += blank()
    f += out(f"  {DG}Comparing baseline-v45 → regression-check-v46  (code_review_failures.md){R}")
    f += blank()
    f += out(f"  {G}  + Improvements:{R}  {DG}none detected{R}")
    f += blank()
    f += out(f"  {RD}  - New failures  (+14 vs baseline):{R}")
    f += out(f"  {RD}  ──────────────────────────────────────────────────────────────────────{R}")
    f += out(f"  {RD}  - comment: 'This N+1 query will cause performance issues at scale'{R}")
    f += out(f"  {RD}    expected: IMPORTANT   got: BLOCKER  ← severity inflation{R}")
    f += blank()
    f += out(f"  {RD}  - comment: 'Memory leak possible if exception thrown here'{R}")
    f += out(f"    {RD}  expected: BLOCKER    got: IMPORTANT  ← severity deflation{R}")
    f += blank()
    f += out(f"  {RD}  - comment: 'This could be a security issue in some edge cases'{R}")
    f += out(f"    {RD}  expected: IMPORTANT  got: BLOCKER  ← over-classification{R}")
    f += blank()
    f += out(f"  {RD}  - (14 more failures of the same pattern...){R}")
    f += blank()
    f += out(f"  {BR}Pattern:{R}  {BY}claude-sonnet-4-6 struggles with BLOCKER vs IMPORTANT boundary{R}")
    f += out(f"  {DG}  Same weakness fixed by Meta-Harness two_step_attr_merged harness in v4.5!{R}")
    f += blank()
    f += [pause(2600)]

    # ── Scene 5: Deploy blocked ────────────────────────────────────────────────
    f += separator(700)
    f += out(f"  {BR}██ DEPLOY BLOCKED ██{R}  {DG}CI gate triggered{R}")
    f += separator()
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos --json query \"SELECT benchmark, score_v46, baseline_v45, delta_pct FROM regression_results WHERE delta_pct < -5\"")
    f += blank()
    f += out(f"  {DG}Scanning regression_results...{R}", 300)
    f += [pause(400)]
    f += out(f"  {DG}benchmark      score_v46   baseline_v45   delta_pct{R}")
    f += out(f"  {DG}─────────────  ─────────   ────────────   ─────────{R}")
    f += out(f"  {BR}code_review{R}    {BR}0.76{R}        {DG}0.83{R}           {BR}-8.4%{R}")
    f += blank()
    f += out(f"  {BR}1 benchmark below threshold (-5%).{R}")
    f += blank()
    f += out(f"  {BR}  ╔══════════════════════════════════════════════════════════════════╗{R}")
    f += out(f"  {BR}  ║{R}  {B}{BR}DEPLOY BLOCKED{R}                                                  {BR}║{R}")
    f += out(f"  {BR}  ║{R}  {DG}code_review: -8.4%  (threshold: -5%){R}                          {BR}║{R}")
    f += out(f"  {BR}  ║{R}  {DG}Notification: 2 regressions. Blocking swap to claude-sonnet-4-6.{R} {BR}║{R}")
    f += out(f"  {BR}  ║{R}  {DG}Action required: remediate code_review benchmark.{R}              {BR}║{R}")
    f += out(f"  {BR}  ╚══════════════════════════════════════════════════════════════════╝{R}")
    f += blank()
    f += [pause(3000)]

    # ── Scene 6: Remediation via Meta-Harness ─────────────────────────────────
    f += section("STEP 5 — Remediation: re-run Meta-Harness on affected benchmark")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos mh search -b code_review --model claude-sonnet-4-6 -n 5 --seed-from baseline-v45")
    f += blank()
    f += out(f"  {G}✓{R}  Benchmark: code_review  {DG}(200 examples){R}")
    f += out(f"  {G}✓{R}  Model: claude-sonnet-4-6")
    f += out(f"  {G}✓{R}  Seeded from: baseline-v45  {DG}(two_step_attr_merged acc=0.83){R}")
    f += out(f"  {G}✓{R}  Worker started  {DG}PID 22841  5 iterations{R}")
    f += blank()
    f += out(f"  {DG}[iter 1/5]{R}  {DG}Testing known winner: two_step_attr_merged...{R}", 200)
    f += [pause(500)]
    f += out(f"  {DG}[iter 1/5]{R}  two_step_attr_merged  acc={Y}0.76{R}  {DG}(baseline was 0.83 on v4.5){R}")
    f += out(f"             {DG}Harness works but model changed — need re-tuning{R}")
    f += blank()

    f += out(f"  {DG}[iter 2/5]{R}  {DG}Proposing: two_step_attr_v46 (recalibrated thresholds){R}", 180)
    f += [pause(400)]
    f += out(f"  {DG}[iter 2/5]{R}  two_step_attr_v46     acc={G}0.80{R}  {G}+0.04 ↑  IMPROVED{R}")
    f += blank()

    f += out(f"  {DG}[iter 3/5]{R}  {DG}Proposing: explicit_boundary_v46 (BLOCKER severity anchors){R}", 180)
    f += [pause(400)]
    f += out(f"  {DG}[iter 3/5]{R}  explicit_boundary_v46 acc={G}0.83{R}  {BG}+0.03 ↑  RESTORED  ← 0.83!{R}")
    f += blank()

    f += out(f"  {DG}[iter 4/5]{R}  acc={G}0.83{R}  {DG}─  no further gain  stagnant=1{R}", 150)
    f += out(f"  {DG}[iter 5/5]{R}  acc={G}0.83{R}  {DG}─  no further gain  stagnant=2{R}", 150)
    f += blank()
    f += [pause(600)]

    f += out(f"  {BG}Remediation complete.{R}  code_review restored to acc=0.83 with explicit_boundary_v46")
    f += blank()
    f += [pause(1000)]

    # ── Scene 7: Deploy approved ───────────────────────────────────────────────
    f += separator(700)
    f += out(f"  {BG}██ DEPLOY APPROVED ██{R}  {DG}All benchmarks within threshold{R}")
    f += separator()
    f += blank()
    f += out(f"  {DG}Final regression check (with updated harness):{R}")
    f += blank()
    f += out(f"  {DG}benchmark        score_v46   baseline_v45   delta     status{R}")
    f += out(f"  {DG}───────────────  ─────────   ────────────   ───────   ──────────────{R}")
    f += out(f"  {G}text_classify{R}    0.87        0.87            0.0%   {DG}NO CHANGE{R}")
    f += out(f"  {G}tool_calling{R}     0.91        0.88           +3.4%   {G}IMPROVED   ✓{R}")
    f += out(f"  {G}math_qa{R}          0.76        0.74           +2.7%   {G}IMPROVED   ✓{R}")
    f += out(f"  {Y}sentiment{R}        0.81        0.83           -2.4%   {Y}MINOR      ⚠{R}")
    f += out(f"  {G}code_review{R}      0.83        0.83            0.0%   {G}RESTORED   ✓{R}")
    f += blank()
    f += out(f"  {G}✓{R}  No benchmark below -5% threshold.")
    f += out(f"  {G}✓{R}  Harness updated: explicit_boundary_v46 deployed alongside model swap.")
    f += out(f"  {G}✓{R}  Swapping production: claude-sonnet-4-5  →  {BG}claude-sonnet-4-6{R}")
    f += blank()
    f += [pause(1000)]

    # ── Scene 8: Summary ──────────────────────────────────────────────────────
    f += section("Result — Regression caught, remediated, deploy approved")
    f += blank()
    f += out(f"  {DG}Regression detected:{R}    {BR}code_review -8.4%{R}  {DG}+ sentiment -2.4%{R}")
    f += out(f"  {DG}Deploy blocked:{R}         {BR}automatic CI gate  (threshold -5%){R}")
    f += out(f"  {DG}Root cause:{R}             BLOCKER/IMPORTANT boundary shift in claude-sonnet-4-6")
    f += out(f"  {DG}Remediation:{R}            5-iteration Meta-Harness search  {DG}(3 iters to fix){R}")
    f += out(f"  {DG}code_review restored:{R}   {G}0.83  (0% delta from baseline){R}")
    f += out(f"  {DG}Deploy status:{R}          {BG}APPROVED  with updated harness{R}")
    f += blank()
    f += out(f"  {DG}Full audit trail:{R}  every benchmark run, diff, and harness change in kaos.db")
    f += blank()
    f += [pause(4000)]

    return f


# ── YAML output ────────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_yml = os.path.join(script_dir, "kaos_uc_regression.yml")

    records = build()
    config  = make_config("KAOS — New Model Version: Catch the 8% Regression Before It Ships")

    doc = {"config": config, "records": records}
    with open(out_yml, "w", encoding="utf-8") as fh:
        yaml.dump(doc, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    total_ms = sum(r.get("delay", 0) for r in records)
    print(f"Written: {out_yml}")
    print(f"Frames:  {len(records)}")
    print(f"Est. duration: {total_ms/1000:.1f}s")
    print(f"\nRender with:")
    print(f"  uv run python render_gif.py kaos_uc_regression.yml")


if __name__ == "__main__":
    main()
