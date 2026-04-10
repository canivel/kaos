"""
Generate a long-form end-to-end Meta-Harness demo recording.

Problem: Code Review Comment Severity Classification
  - Input:  GitHub PR review comment
  - Labels: BLOCKER | IMPORTANT | STYLE | PRAISE
  - Baseline zero-shot: ~48%
  - After 15 iterations: ~83%

This recording walks through the full journey:
  1. Problem setup + benchmark creation
  2. kaos init + mh search launch
  3. Seed evaluation (3 seeds)
  4. 15 search iterations — proposer traces, CORAL plateau pivot, breakthrough
  5. Final frontier + knowledge compounding
  6. Winning harness code

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_mh_full_demo.py
    uv run python render_gif.py kaos_mh_full_demo.yml
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
    f += out(f"  {B}{CY}KAOS Meta-Harness{R}  {DG}—{R}  {WH}End-to-End Research Demo{R}")
    f += out(f"  {DG}From problem definition to solved harness, nothing skipped{R}")
    f += out(f"")
    f += out(f"  {DG}Research problem:{R}  {BY}Code Review Comment Severity Classification{R}")
    f += out(f"  {DG}Labels:{R}          {G}BLOCKER{R}  {Y}IMPORTANT{R}  {BL}STYLE{R}  {MG}PRAISE{R}")
    f += out(f"  {DG}Baseline:{R}        ~48% accuracy (zero-shot GPT)")
    f += out(f"  {DG}Goal:{R}            Find the best harness automatically")
    f += out(f"")
    f += [pause(2200)]

    # ── Scene 2: Show the benchmark file ─────────────────────────────────────
    f += section("STEP 1 — Define the benchmark (benchmarks/code_review.py)")
    f += blank()
    f += prompt_line()
    f += type_cmd("cat benchmarks/code_review.py")
    f += blank()
    f += out(f'{DG}"""Code Review Comment Severity Benchmark{R}')
    f += out(f'{DG}Classify a GitHub PR review comment into: BLOCKER | IMPORTANT | STYLE | PRAISE{R}')
    f += out(f'{DG}"""{R}')
    f += blank()
    f += out(f'{MG}LABELS{R} = [{G}"BLOCKER"{R}, {G}"IMPORTANT"{R}, {G}"STYLE"{R}, {G}"PRAISE"{R}]')
    f += blank()
    f += out(f'{MG}EXAMPLES{R} = [')
    f += out(f'  {{"comment": {G}"SQL query is vulnerable to injection — must fix before merge"{R},')
    f += out(f'   {G}"label"{R}: {G}"BLOCKER"{R}}},')
    f += out(f'  {{"comment": {G}"This N+1 query will cause issues at scale"{R},')
    f += out(f'   {G}"label"{R}: {G}"IMPORTANT"{R}}},')
    f += out(f'  {{"comment": {G}"Variable name `x` is not descriptive"{R},')
    f += out(f'   {G}"label"{R}: {G}"STYLE"{R}}},')
    f += out(f'  {{"comment": {G}"Nice use of early returns here, much cleaner!"{R},')
    f += out(f'   {G}"label"{R}: {G}"PRAISE"{R}}},')
    f += out(f'  {DG}# ... 196 more examples{R}')
    f += out(f']')
    f += blank()
    f += out(f'{CY}def{R} {BG}evaluate{R}(harness_fn, examples=EXAMPLES):')
    f += out(f'    {DG}"""Run harness on all examples, return accuracy + per-label F1"""{R}')
    f += out(f'    predictions = [harness_fn(e[{G}"comment"{R}]) {CY}for{R} e {CY}in{R} examples]')
    f += out(f'    correct = sum(p == e[{G}"label"{R}] {CY}for{R} p, e {CY}in{R} zip(predictions, examples))')
    f += out(f'    {CY}return{R} {{')
    f += out(f'        {G}"accuracy"{R}: correct / len(examples),')
    f += out(f'        {G}"n_correct"{R}: correct,')
    f += out(f'        {G}"n_total"{R}: len(examples),')
    f += out(f'    }}')
    f += [pause(1800)]

    # ── Scene 3: kaos init ────────────────────────────────────────────────────
    f += blank()
    f += section("STEP 2 — Initialize KAOS database")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos init")
    f += out(f"  {G}✓{R}  Initialized {BL}kaos.db{R}")
    f += out(f"  {G}✓{R}  Schema v4 applied (agents, tool_calls, vfs_files, events, blobs)")
    f += out(f"  {G}✓{R}  Knowledge agent spawned  {DG}[kaos-knowledge]{R}")
    f += out(f"  {G}✓{R}  Ready")
    f += blank()
    f += prompt_line()
    f += type_cmd("cat kaos.yaml")
    f += blank()
    f += out(f"{MG}provider{R}: {G}claude_code{R}   {DG}# uses your CC subscription, zero API cost{R}")
    f += out(f"{MG}model{R}:    {G}claude-sonnet-4-6{R}")
    f += out(f"{MG}compaction_level{R}: {BY}5{R}     {DG}# default: 57% savings, 100% quality{R}")
    f += out(f"{MG}stagnation_threshold{R}: {BY}4{R}  {DG}# CORAL pivot after 4 non-improving iters{R}")
    f += out(f"{MG}consolidation_every{R}: {BY}6{R}   {DG}# CORAL consolidation heartbeat{R}")
    f += [pause(1500)]

    # ── Scene 4: Launch search ────────────────────────────────────────────────
    f += blank()
    f += section("STEP 3 — Launch Meta-Harness search (15 iterations)")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos mh search -b code_review -n 15 -k 3 --background")
    f += blank()
    f += out(f"  {G}✓{R}  Benchmark loaded: {BY}code_review{R}  {DG}(200 examples, 4 labels){R}")
    f += out(f"  {G}✓{R}  Search agent spawned  {DG}[01JMHSRCH-code-review]{R}")
    f += out(f"  {G}✓{R}  Worker process started  {DG}PID 14832{R}")
    f += out(f"  {DG}───────────────────────────────────────────────────────────────────────{R}")
    f += out(f"  {CY}Phase 1:{R}  Evaluating {BY}3 seed harnesses{R} in parallel...")
    f += blank()
    f += [pause(700)]

    # ── Scene 5: Seed evaluation ──────────────────────────────────────────────
    f += out(f"  {DG}[seed 1/3]{R}  zero_shot         {DG}evaluating...{R}", 80)
    f += [pause(400)]
    f += out(f"  {DG}[seed 1/3]{R}  zero_shot         {G}acc=0.48{R}  cost=12.4  {DG}96/200 ✓{R}")
    f += [pause(200)]
    f += out(f"  {DG}[seed 2/3]{R}  few_shot_2        {DG}evaluating...{R}", 80)
    f += [pause(500)]
    f += out(f"  {DG}[seed 2/3]{R}  few_shot_2        {G}acc=0.54{R}  cost=18.7  {DG}108/200 ✓{R}")
    f += [pause(200)]
    f += out(f"  {DG}[seed 3/3]{R}  cot_basic         {DG}evaluating...{R}", 80)
    f += [pause(600)]
    f += out(f"  {DG}[seed 3/3]{R}  cot_basic         {G}acc=0.61{R}  cost=24.1  {DG}122/200 ✓{R}")
    f += blank()
    f += out(f"  {BG}Seed evaluation complete.{R}  Initial frontier: {BY}3{R} points")
    f += out(f"  {DG}Best seed: {R}{G}cot_basic{R} {DG}(acc=0.61){R}  {DG}─{R}  Search begins from here")
    f += [pause(1200)]

    # ── Scene 6: Iterations 1-4 ───────────────────────────────────────────────
    f += blank()
    f += separator()
    f += out(f"  {B}{CY}Search Loop{R}  {DG}─ proposer reads traces → proposes harness → evaluate → frontier{R}")
    f += separator()
    f += blank()
    f += [pause(600)]

    # Iteration 1
    f += out(f"  {BY}[iter 1/15]{R}  {DG}Proposer reading archive digest...{R}", 90)
    f += [pause(500)]
    f += out(f"  {DG}           Archive: 3 harnesses  │  compacted to 57% (AAAK notation){R}")
    f += out(f"  {DG}           Best: cot_basic acc=0.61  ERR: BLOCKER↔IMPORTANT confusion (34×){R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 1/15]{R}  {DG}Proposing...{R}  {G}role_engineer{R}  {DG}'act as senior SWE reviewing a PR'{R}")
    f += [pause(400)]
    f += out(f"  {BY}[iter 1/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(700)]
    f += out(f"  {BY}[iter 1/15]{R}  {G}role_engineer{R}    acc={G}0.67{R}  cost=21.3  {G}+0.06 ↑  IMPROVED{R}  {DG}134/200 ✓{R}")
    f += out(f"             {DG}Frontier updated: [{R}{G}0.67{R}{DG}, 0.61, 0.54, 0.48]{R}")
    f += blank()

    # Iteration 2
    f += out(f"  {BY}[iter 2/15]{R}  {DG}Proposing...{R}  {G}role_engineer_v2{R}  {DG}'triage nurse role + severity rubric'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 2/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(700)]
    f += out(f"  {BY}[iter 2/15]{R}  {G}role_engineer_v2{R} acc={G}0.71{R}  cost=26.8  {G}+0.04 ↑  IMPROVED{R}  {DG}142/200 ✓{R}")
    f += out(f"             {DG}Frontier: [{R}{G}0.71{R}{DG}, 0.67, 0.61]{R}")
    f += blank()

    # Iteration 3
    f += out(f"  {BY}[iter 3/15]{R}  {DG}Proposing...{R}  {G}rubric_detailed{R}  {DG}'explicit 4-tier rubric with examples per tier'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 3/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(600)]
    f += out(f"  {BY}[iter 3/15]{R}  {RD}rubric_detailed{R}  acc={Y}0.69{R}  cost=34.2  {Y}─  regression vs best{R}  {DG}138/200 ✓{R}")
    f += out(f"             {DG}Frontier unchanged.  stagnant_iters=1{R}")
    f += blank()

    # Iteration 4
    f += out(f"  {BY}[iter 4/15]{R}  {DG}Proposing...{R}  {G}few_shot_balanced{R}  {DG}'1 example per class, explicit contrast'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 4/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(700)]
    f += out(f"  {BY}[iter 4/15]{R}  {G}few_shot_balanced{R} acc={G}0.74{R}  cost=29.1  {G}+0.03 ↑  IMPROVED{R}  {DG}148/200 ✓{R}")
    f += out(f"             {DG}Frontier: [{R}{G}0.74{R}{DG}, 0.71, 0.67]{R}")
    f += blank()
    f += [pause(800)]

    # Iteration 5
    f += out(f"  {BY}[iter 5/15]{R}  {DG}Proposing...{R}  {G}few_shot_4x{R}  {DG}'4 examples per class'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 5/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(600)]
    f += out(f"  {BY}[iter 5/15]{R}  {RD}few_shot_4x{R}      acc={Y}0.73{R}  cost=48.9  {Y}─  marginally worse, higher cost{R}")
    f += out(f"             {DG}stagnant_iters=2{R}")
    f += blank()

    # Iteration 6
    f += out(f"  {BY}[iter 6/15]{R}  {DG}Proposing...{R}  {G}chain_contrast{R}  {DG}'CoT with explicit BLOCKER vs IMPORTANT contrast'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 6/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(700)]
    f += out(f"  {BY}[iter 6/15]{R}  {RD}chain_contrast{R}   acc={Y}0.74{R}  cost=31.4  {Y}─  matches best, no improvement{R}")
    f += out(f"             {DG}stagnant_iters=3  (threshold=4){R}")
    f += blank()

    # Iteration 7 - CORAL consolidation heartbeat
    f += out(f"  {BY}[iter 7/15]{R}  {DG}Proposing...{R}  {G}few_shot_role_merge{R}  {DG}'role + few-shot merged'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 7/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(600)]
    f += out(f"  {BY}[iter 7/15]{R}  {RD}few_shot_role_merge{R} acc={Y}0.74{R}  {Y}─  no improvement{R}")
    f += out(f"             {DG}stagnant_iters=4  ──{R}  {BR}PLATEAU DETECTED{R}")
    f += blank()
    f += [pause(500)]

    # ── Scene 7: CORAL pivot fires ────────────────────────────────────────────
    f += separator(600)
    f += out(f"  {BR}⚠  CORAL PIVOT REQUIRED{R}  {DG}(stagnant_iters=4 ≥ threshold=4){R}")
    f += separator()
    f += blank()
    f += out(f"  {DG}The proposer archive digest now includes a PIVOT block:{R}")
    f += blank()
    f += out(f"  {MG}╔══════════════════════════════════════════════════════════════════╗{R}")
    f += out(f"  {MG}║{R}  {BR}PIVOT REQUIRED{R}  {DG}─{R}  stagnant=4  best=0.74                      {MG}║{R}")
    f += out(f"  {MG}║{R}                                                                  {MG}║{R}")
    f += out(f"  {MG}║{R}  {Y}Exhausted approaches:{R}                                         {MG}║{R}")
    f += out(f"  {MG}║{R}  {DG}  • Role-playing (engineer/reviewer) — ceiling at 0.74{R}          {MG}║{R}")
    f += out(f"  {MG}║{R}  {DG}  • Few-shot examples — 1-4 per class, diminishing returns{R}       {MG}║{R}")
    f += out(f"  {MG}║{R}  {DG}  • CoT with contrast — matched best but did not improve{R}         {MG}║{R}")
    f += out(f"  {MG}║{R}                                                                  {MG}║{R}")
    f += out(f"  {MG}║{R}  {G}Required:{R} propose an {B}orthogonal direction{R}.  Ideas:              {MG}║{R}")
    f += out(f"  {MG}║{R}  {DG}  • Two-step classification (blocker? → if not, style or praise?){R}  {MG}║{R}")
    f += out(f"  {MG}║{R}  {DG}  • Structured attribute extraction before classifying{R}             {MG}║{R}")
    f += out(f"  {MG}║{R}  {DG}  • Confidence calibration + abstain on ambiguous cases{R}            {MG}║{R}")
    f += out(f"  {MG}╚══════════════════════════════════════════════════════════════════╝{R}")
    f += blank()
    f += [pause(1800)]

    # ── Scene 8: Post-pivot iterations ────────────────────────────────────────
    # Iteration 8 - pivot: two-step chain
    f += out(f"  {BY}[iter 8/15]{R}  {DG}Proposing...{R}  {G}two_step_chain{R}  {DG}'step 1: safety? → step 2: severity'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 8/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(800)]
    f += out(f"  {BY}[iter 8/15]{R}  {G}two_step_chain{R}  acc={G}0.78{R}  cost=33.2  {G}+0.04 ↑  IMPROVED{R}  {DG}156/200 ✓{R}")
    f += out(f"             {DG}Frontier: [{R}{G}0.78{R}{DG}, 0.74, 0.71]  stagnant_iters=0 (reset){R}")
    f += blank()

    # Iteration 9
    f += out(f"  {BY}[iter 9/15]{R}  {DG}Proposing...{R}  {G}attr_extract{R}  {DG}'extract: impact, scope, fixability → then classify'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 9/15]{R}  {DG}Evaluating...{R}", 80)
    f += [pause(700)]
    f += out(f"  {BY}[iter 9/15]{R}  {G}attr_extract{R}    acc={G}0.79{R}  cost=38.7  {G}+0.01 ↑  IMPROVED{R}  {DG}158/200 ✓{R}")
    f += out(f"             {DG}Frontier: [{R}{G}0.79{R}{DG}, 0.78, 0.74]{R}")
    f += blank()

    # Iteration 10 - consolidation heartbeat
    f += out(f"  {BY}[iter 10/15]{R} {DG}⟳ CORAL Consolidation heartbeat{R}  {DG}(every 6 iters){R}")
    f += out(f"             {DG}Distilling reusable skills from 10 iterations...{R}")
    f += [pause(500)]
    f += out(f"             {G}Skill written:{R}  {DG}two_step_decomposition — split safety check from severity{R}")
    f += out(f"             {G}Skill written:{R}  {DG}attr_grounding — extract impact+scope before labeling{R}")
    f += blank()
    f += out(f"  {BY}[iter 10/15]{R} {DG}Proposing...{R}  {G}two_step_attr_merged{R}  {DG}'combine both skills'{R}")
    f += [pause(300)]
    f += out(f"  {BY}[iter 10/15]{R} {DG}Evaluating...{R}", 80)
    f += [pause(800)]
    f += out(f"  {BY}[iter 10/15]{R} {G}two_step_attr_merged{R} acc={G}0.83{R} cost=41.5 {G}+0.04 ↑  IMPROVED{R} {DG}166/200 ✓{R}")
    f += out(f"             {DG}Frontier: [{R}{G}0.83{R}{DG}, 0.79, 0.78]{R}  {BG}New best!{R}")
    f += blank()
    f += [pause(900)]

    # Iterations 11-15: refinements, plateau at 0.83
    f += out(f"  {BY}[iter 11/15]{R} {DG}Proposing...{R}  {G}two_step_calibrated{R}  {DG}'+ confidence threshold for borderline cases'{R}")
    f += [pause(250)]
    f += out(f"  {BY}[iter 11/15]{R} {DG}Evaluating...{R}", 70)
    f += [pause(600)]
    f += out(f"  {BY}[iter 11/15]{R} {RD}two_step_calibrated{R} acc={Y}0.82{R} {Y}─  marginally worse{R}  stagnant=1")
    f += blank()

    f += out(f"  {BY}[iter 12/15]{R} {DG}Proposing...{R}  {G}attr_with_examples{R}  {DG}'attr extraction + 2 examples per label'{R}")
    f += [pause(250)]
    f += out(f"  {BY}[iter 12/15]{R} {DG}Evaluating...{R}", 70)
    f += [pause(600)]
    f += out(f"  {BY}[iter 12/15]{R} {G}attr_with_examples{R} acc={G}0.83{R} {DG}─  matches best{R}  stagnant=2")
    f += blank()

    f += out(f"  {BY}[iter 13/15]{R} {DG}Proposing...{R}  {G}blocker_specialist{R}  {DG}'specialized BLOCKER detector first pass'{R}")
    f += [pause(250)]
    f += out(f"  {BY}[iter 13/15]{R} {DG}Evaluating...{R}", 70)
    f += [pause(700)]
    f += out(f"  {BY}[iter 13/15]{R} {RD}blocker_specialist{R}  acc={Y}0.81{R} {Y}─  regression{R}  stagnant=3")
    f += blank()

    f += out(f"  {BY}[iter 14/15]{R} {DG}Proposing...{R}  {G}two_step_attr_v2{R}   {DG}'refined scope definition, cleaner prompt'{R}")
    f += [pause(250)]
    f += out(f"  {BY}[iter 14/15]{R} {DG}Evaluating...{R}", 70)
    f += [pause(600)]
    f += out(f"  {BY}[iter 14/15]{R} {G}two_step_attr_v2{R}   acc={G}0.83{R} {DG}─  matches best{R}  stagnant=4")
    f += blank()

    f += out(f"  {BY}[iter 15/15]{R} {DG}Proposing...{R}  {G}ensemble_vote{R}      {DG}'majority vote: 3 harnesses on each sample'{R}")
    f += [pause(250)]
    f += out(f"  {BY}[iter 15/15]{R} {DG}Evaluating...{R}", 70)
    f += [pause(800)]
    f += out(f"  {BY}[iter 15/15]{R} {RD}ensemble_vote{R}       acc={Y}0.82{R} {Y}─  cost 3× worse, no gain{R}  stagnant=5")
    f += blank()
    f += [pause(600)]

    # ── Scene 9: Search complete ───────────────────────────────────────────────
    f += separator(700)
    f += out(f"  {BG}Search complete.{R}  15 iterations  │  {G}83% accuracy{R}  │  {DG}+35 points from baseline{R}")
    f += separator()
    f += blank()
    f += [pause(1000)]

    # ── Scene 10: View frontier ────────────────────────────────────────────────
    f += section("STEP 4 — View the Pareto frontier")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos mh frontier code_review")
    f += blank()
    f += out(f"  {B}Pareto Frontier{R}  {DG}─  code_review benchmark{R}")
    f += blank()
    f += out(f"  {DG}rank  harness_id              accuracy  cost   n_correct{R}")
    f += out(f"  {DG}────  ──────────────────────  ────────  ─────  ─────────{R}")
    f += out(f"   {G}★ 1{R}   two_step_attr_merged    {G}0.830{R}    41.5   166/200  {DG}← best accuracy{R}")
    f += out(f"     {Y}2{R}   attr_with_examples      {G}0.830{R}    44.2   166/200  {DG}← same acc, higher cost{R}")
    f += out(f"     {BL}3{R}   attr_extract            0.790    38.7   158/200  {DG}← best cost-to-acc tradeoff{R}")
    f += out(f"     4   two_step_chain          0.780    33.2   156/200")
    f += out(f"     5   few_shot_balanced       0.740    29.1   148/200  {DG}← best cheap option{R}")
    f += blank()
    f += [pause(1400)]

    # ── Scene 11: View knowledge ───────────────────────────────────────────────
    f += section("STEP 5 — Knowledge compounding (persists across searches)")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos mh knowledge code_review")
    f += blank()
    f += out(f"  {B}Knowledge Base{R}  {DG}─  code_review  (persists across all future searches){R}")
    f += blank()
    f += out(f"  {G}[skill]{R}  two_step_decomposition")
    f += out(f"  {DG}  Split the classification into two sequential questions:{R}")
    f += out(f'  {DG}  1. "Does this comment identify a correctness/security problem?"{R}')
    f += out(f'  {DG}  2. If yes → BLOCKER or IMPORTANT. If no → STYLE or PRAISE.{R}')
    f += out(f"  {DG}  Discovered at iteration 8. Broke plateau at 0.74.{R}")
    f += blank()
    f += out(f"  {G}[skill]{R}  attr_grounding")
    f += out(f"  {DG}  Before classifying, extract: impact (high/med/low),{R}")
    f += out(f"  {DG}  scope (blocking merge / should fix / nice to have), fixability.{R}")
    f += out(f"  {DG}  Ground label in extracted attributes, not free-form reasoning.{R}")
    f += blank()
    f += out(f"  {G}[winner]{R} two_step_attr_merged  {DG}acc=0.83{R}  {DG}(combining both skills){R}")
    f += [pause(1600)]

    # ── Scene 12: Show winning harness ────────────────────────────────────────
    f += blank()
    f += section("STEP 6 — Winning harness code (ready to deploy)")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos mh export code_review --winner")
    f += blank()
    f += out(f"{DG}# two_step_attr_merged — generated by Meta-Harness search{R}")
    f += out(f"{DG}# accuracy: 0.83  iterations: 15  search_time: ~12 min{R}")
    f += blank()
    f += out(f"{MG}SYSTEM_PROMPT{R} = {G}'''You are a senior software engineer reviewing a PR.{R}")
    f += out(f"{G}Classify the review comment below using a two-step process:{R}")
    f += blank()
    f += out(f"{G}STEP 1 — Extract attributes:{R}")
    f += out(f"{G}  impact:       high | medium | low{R}")
    f += out(f"{G}  scope:        blocks-merge | should-fix | nice-to-have | positive{R}")
    f += out(f"{G}  correctness:  yes (bug/security/logic error) | no{R}")
    f += blank()
    f += out(f"{G}STEP 2 — Apply classification rules:{R}")
    f += out(f"{G}  If correctness=yes AND impact=high  →  BLOCKER{R}")
    f += out(f"{G}  If correctness=yes AND impact<high  →  IMPORTANT{R}")
    f += out(f"{G}  If scope=nice-to-have               →  STYLE{R}")
    f += out(f"{G}  If scope=positive                   →  PRAISE{R}")
    f += out(f"{G}  Default ambiguous to IMPORTANT.'''{R}")
    f += blank()
    f += out(f"{CY}def{R} {BG}harness{R}(comment: str) -> str:")
    f += out(f"    response = {BG}llm{R}(SYSTEM_PROMPT, comment)")
    f += out(f"    {CY}return{R} {BG}extract_label{R}(response, valid={MG}LABELS{R})")
    f += blank()
    f += [pause(1800)]

    # ── Scene 13: Audit trail ─────────────────────────────────────────────────
    f += section("STEP 7 — Full audit trail (SQL over every iteration)")
    f += blank()
    f += prompt_line()
    f += type_cmd('kaos --json query "SELECT iteration, harness_id, scores->>\'accuracy\' as acc, status FROM mh_attempts WHERE benchmark=\'code_review\' ORDER BY iteration"')
    f += blank()
    f += out(f"  iter  harness_id              acc    status")
    f += out(f"  ────  ──────────────────────  ─────  ─────────")
    for i, (name, acc, st) in enumerate([
        ("zero_shot",            "0.480", "seed"),
        ("few_shot_2",           "0.540", "seed"),
        ("cot_basic",            "0.610", "seed"),
        ("role_engineer",        "0.670", "improved"),
        ("role_engineer_v2",     "0.710", "improved"),
        ("rubric_detailed",      "0.690", "regression"),
        ("few_shot_balanced",    "0.740", "improved"),
        ("few_shot_4x",          "0.730", "regression"),
        ("chain_contrast",       "0.740", "neutral"),
        ("few_shot_role_merge",  "0.740", "neutral"),
        ("two_step_chain",       "0.780", "improved"),
        ("attr_extract",         "0.790", "improved"),
        ("two_step_attr_merged", "0.830", "improved"),
        ("attr_with_examples",   "0.830", "neutral"),
        ("two_step_attr_v2",     "0.830", "neutral"),
    ], 0):
        color = G if st == "improved" else (RD if st == "regression" else DG)
        marker = "★" if name == "two_step_attr_merged" else " "
        f += out(f"  {marker}{i+1:>3}   {name:<22}  {acc}  {color}{st}{R}", 50)
    f += blank()
    f += [pause(900)]

    # ── Scene 14: Token cost summary ──────────────────────────────────────────
    f += prompt_line()
    f += type_cmd('kaos --json query "SELECT SUM(tokens) as total_tokens, COUNT(*) as calls FROM tool_calls WHERE agent_id LIKE \'%code-review%\'"')
    f += blank()
    f += out(f"  total_tokens   calls")
    f += out(f"  ────────────   ─────")
    f += out(f"  {BY}48,291{R}         {BY}82{R}    {DG}← ~$0.14 at claude-sonnet rates ($3/Mtok){R}")
    f += blank()
    f += [pause(700)]

    # ── Scene 15: Final summary ────────────────────────────────────────────────
    f += section("Result — From research problem to production harness")
    f += blank()
    f += out(f"  {DG}Baseline (zero-shot):{R}    {RD}48%{R}  accuracy")
    f += out(f"  {DG}After Meta-Harness:{R}      {G}83%{R}  accuracy  {DG}(+35 points){R}")
    f += out(f"  {DG}Iterations used:{R}         15")
    f += out(f"  {DG}Search time:{R}             ~12 minutes")
    f += out(f"  {DG}API cost:{R}                ~$0.14")
    f += out(f"  {DG}Key insight discovered:{R}  two-step decomposition breaks BLOCKER/IMPORTANT confusion")
    f += out(f"  {DG}Skills saved:{R}            2 reusable patterns → next search starts from here")
    f += blank()
    f += out(f"  {G}Winning harness:{R}  {BY}two_step_attr_merged{R}  {DG}exported to harnesses/code_review_winner.py{R}")
    f += blank()
    f += out(f"  {DG}Next step:{R}  plug winner back into your CI pipeline or run co-evolution:{R}")
    f += out(f"  {DG}  kaos mh search -b code_review -n 10{R}   {DG}# continue from this knowledge{R}")
    f += out(f"  {DG}  kaos mh spawn-coevolution -b code_review -n 3{R}   {DG}# CORAL multi-agent{R}")
    f += blank()
    f += [pause(3000)]

    return f


# ── YAML output ────────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_yml = os.path.join(script_dir, "kaos_mh_full_demo.yml")

    records = build()
    config  = make_config("KAOS — Meta-Harness: Code Review Classification (48% → 83%)")

    doc = {"config": config, "records": records}
    with open(out_yml, "w", encoding="utf-8") as fh:
        yaml.dump(doc, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    total_ms = sum(r.get("delay", 0) for r in records)
    print(f"Written: {out_yml}")
    print(f"Frames:  {len(records)}")
    print(f"Est. duration: {total_ms/1000:.1f}s")
    print(f"\nRender with:")
    print(f"  uv run python render_gif.py kaos_mh_full_demo.yml")


if __name__ == "__main__":
    main()
