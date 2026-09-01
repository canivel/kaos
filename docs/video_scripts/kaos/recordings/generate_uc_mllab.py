"""
Generate a terminal recording: 4 ML hypotheses, 4 agents, 1 night — autonomous research lab.

Story: Inspired by Karpathy's autoresearch. 4 agents run overnight exploring different
hypotheses on a character-level language model. Architecture (LoRA vs full finetune),
optimizer (AdamW vs Lion), scaling (batch 32 vs 128), regularization (dropout 0.1 vs 0.3).
SQL query shows the winner. Results seed the next Meta-Harness search.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_mllab.py
    uv run python render_gif.py kaos_uc_mllab.yml
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
    f += out(f"  {B}{CY}KAOS — Autonomous ML Research Lab{R}  {DG}—{R}  {WH}4 Hypotheses, 1 Night{R}")
    f += out(f"  {DG}Inspired by Karpathy's autoresearch  │  char-level LM  │  isolated VFS per agent{R}")
    f += out(f"")
    f += out(f"  {DG}Baseline model:{R}   {BY}train.py{R}  val_loss={BR}2.34{R}  {DG}(want to beat this tonight){R}")
    f += out(f"")
    f += out(f"  {DG}Hypotheses to explore:{R}")
    f += out(f"  {DG}  arch-explorer:{R}   {G}LoRA vs full finetune{R}  {DG}+ cosine LR schedule{R}")
    f += out(f"  {DG}  optim-explorer:{R}  {G}AdamW vs Lion optimizer{R}")
    f += out(f"  {DG}  scale-explorer:{R}  {G}batch_size 32 vs 128{R}")
    f += out(f"  {DG}  reg-explorer:{R}    {G}dropout 0.1 vs 0.3{R}")
    f += out(f"")
    f += [pause(3000)]

    # ── Scene 2: Spawn 4 agents ───────────────────────────────────────────────
    f += section("STEP 1 — Spawn 4 hypothesis agents (isolated VFS each)")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos parallel spawn arch-explorer optim-explorer scale-explorer reg-explorer --copy train.py")
    f += blank()
    f += out(f"  {DG}Spawning 4 agents in parallel...{R}")
    f += [pause(300)]
    f += out(f"  {G}✓{R}  arch-explorer   spawned  {DG}VFS: arch-explorer.db  train.py copied{R}")
    f += out(f"  {G}✓{R}  optim-explorer  spawned  {DG}VFS: optim-explorer.db  train.py copied{R}")
    f += out(f"  {G}✓{R}  scale-explorer  spawned  {DG}VFS: scale-explorer.db  train.py copied{R}")
    f += out(f"  {G}✓{R}  reg-explorer    spawned  {DG}VFS: reg-explorer.db  train.py copied{R}")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos ls")
    f += blank()
    f += out(f"  {DG}agent_id         status   hypothesis                      files{R}")
    f += out(f"  {DG}───────────────  ───────  ──────────────────────────────  ───────────{R}")
    f += out(f"  {G}arch-explorer{R}    running  LoRA + cosine LR                train.py")
    f += out(f"  {G}optim-explorer{R}   running  AdamW vs Lion optimizer         train.py")
    f += out(f"  {G}scale-explorer{R}   running  batch_size 128                  train.py")
    f += out(f"  {G}reg-explorer{R}     running  dropout 0.3                     train.py")
    f += blank()
    f += [pause(1200)]

    # ── Scene 3: Agents running (fast forward) ────────────────────────────────
    f += section("STEP 2 — Agents running (fast-forward: training loops in parallel)")
    f += blank()
    f += out(f"  {DG}[arch-explorer  ]{R}  LoRA rank=16, cosine LR, epoch 1/5...")
    f += out(f"  {DG}[optim-explorer ]{R}  Lion optimizer lr=1e-4, epoch 1/5...", 70)
    f += out(f"  {DG}[scale-explorer ]{R}  batch_size=128, grad_accum=4, epoch 1/5...", 70)
    f += out(f"  {DG}[reg-explorer   ]{R}  dropout=0.3, weight_decay=0.1, epoch 1/5...", 70)
    f += blank()
    f += [pause(500)]

    training_interleave = [
        ("arch-explorer  ", "epoch 1/5", "val_loss=2.21", G,   "▌"),
        ("optim-explorer ", "epoch 1/5", "val_loss=2.19", G,   "▌"),
        ("scale-explorer ", "epoch 1/5", "val_loss=2.28", Y,   "▌"),
        ("reg-explorer   ", "epoch 1/5", "val_loss=2.31", Y,   "▌"),
        ("arch-explorer  ", "epoch 2/5", "val_loss=2.08", G,   "██"),
        ("optim-explorer ", "epoch 2/5", "val_loss=2.11", G,   "██"),
        ("scale-explorer ", "epoch 2/5", "val_loss=2.20", Y,   "██"),
        ("reg-explorer   ", "epoch 2/5", "val_loss=2.25", Y,   "██"),
        ("arch-explorer  ", "epoch 3/5", "val_loss=1.97", BG,  "███"),
        ("scale-explorer ", "epoch 3/5", "val_loss=2.18", Y,   "███"),
        ("optim-explorer ", "epoch 3/5", "val_loss=2.04", G,   "███"),
        ("reg-explorer   ", "epoch 3/5", "val_loss=2.19", DG,  "███"),
        ("arch-explorer  ", "epoch 4/5", "val_loss=1.93", BG,  "████"),
        ("optim-explorer ", "epoch 4/5", "val_loss=2.00", G,   "████"),
        ("scale-explorer ", "epoch 4/5", "val_loss=2.18", DG,  "████"),
        ("reg-explorer   ", "epoch 4/5", "val_loss=2.18", DG,  "████"),
    ]
    for agent, epoch, loss, color, prog in training_interleave:
        f += out(f"  {DG}[{agent}]{R}  {DG}{epoch}{R}  {color}{loss}{R}  {DG}{prog}{R}", 200)

    f += blank()
    f += [pause(1200)]

    # ── Scene 3b: Epoch 5 in progress ────────────────────────────────────────
    f += out(f"  {DG}[arch-explorer  ]{R}  epoch 5/5  training...  {DG}step 1200/1800{R}", 200)
    f += out(f"  {DG}[optim-explorer ]{R}  epoch 5/5  training...  {DG}step 1100/1800{R}", 200)
    f += out(f"  {DG}[scale-explorer ]{R}  epoch 5/5  training...  {DG}step 1050/1800{R}", 200)
    f += out(f"  {DG}[reg-explorer   ]{R}  epoch 5/5  training...  {DG}step  980/1800{R}", 200)
    f += blank()
    f += [pause(1000)]

    # ── Scene 4: First agent finishes ─────────────────────────────────────────
    f += section("STEP 3 — First agent finishes: scale-explorer")
    f += blank()
    f += out(f"  {DG}[scale-explorer ]{R}  epoch 5/5  val_loss={Y}2.18{R}  {DG}DONE{R}")
    f += out(f"  {DG}[scale-explorer ]{R}  {G}✓{R}  Baseline beaten: {BR}2.34{R} → {Y}2.18{R}  {DG}(-6.8%){R}")
    f += out(f"  {DG}[scale-explorer ]{R}  Writing results to /results/summary.json")
    f += blank()
    f += [pause(600)]
    f += out(f"  {DG}[arch-explorer  ]{R}  epoch 5/5  val_loss={G}1.89{R}  {BG}DONE ← new leader!{R}")
    f += [pause(400)]
    f += out(f"  {DG}[optim-explorer ]{R}  epoch 5/5  val_loss={G}1.97{R}  {G}DONE{R}", 120)
    f += [pause(300)]
    f += out(f"  {DG}[reg-explorer   ]{R}  epoch 5/5  val_loss={Y}2.17{R}  {DG}DONE{R}", 120)
    f += blank()
    f += [pause(1400)]

    # ── Scene 5: All agents complete ──────────────────────────────────────────
    f += section("STEP 4 — All 4 agents complete. Final losses:")
    f += blank()
    f += out(f"  {DG}agent            hypothesis                  final_val_loss  vs baseline{R}")
    f += out(f"  {DG}───────────────  ──────────────────────────  ──────────────  ──────────{R}")
    f += out(f"  {BG}arch-explorer{R}    LoRA + cosine LR            {BG}1.89{R}            {BG}-19.2%  ★{R}")
    f += out(f"  {G}optim-explorer{R}   Lion optimizer               {G}1.97{R}            {G}-15.8%{R}")
    f += out(f"  {Y}scale-explorer{R}   batch_size=128               {Y}2.18{R}            {Y}-6.8%{R}")
    f += out(f"  {DG}reg-explorer{R}     dropout=0.3                  {DG}2.17{R}            {DG}-7.3%{R}")
    f += blank()
    f += out(f"  {DG}Baseline:  val_loss={BR}2.34{R}  {DG}(beaten by all 4 agents){R}")
    f += blank()
    f += [pause(1200)]

    # ── Scene 6: SQL comparison ───────────────────────────────────────────────
    f += section("STEP 5 — SQL comparison: rank all 4 results")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos --json query \"SELECT agent_name, final_val_loss, improvement_pct, train_time_min FROM ml_results ORDER BY final_val_loss\"")
    f += blank()
    f += out(f"  {DG}agent_name       final_val_loss   improvement_pct   train_time_min{R}")
    f += out(f"  {DG}───────────────  ──────────────   ───────────────   ──────────────{R}")
    f += out(f"  {BG}arch-explorer{R}    {BG}1.89{R}             {BG}-19.2%{R}            {DG}312{R}   {BG}← WINNER{R}")
    f += out(f"  {G}optim-explorer{R}   {G}1.97{R}             {G}-15.8%{R}            {DG}287{R}")
    f += out(f"  {Y}reg-explorer{R}     {Y}2.17{R}              {Y}-7.3%{R}            {DG}254{R}")
    f += out(f"  {Y}scale-explorer{R}   {Y}2.18{R}              {Y}-6.8%{R}            {DG}341{R}")
    f += blank()
    f += out(f"  {BG}Winner:{R}  arch-explorer  {DG}(LoRA rank=16 + cosine LR + warmup 500 steps){R}")
    f += blank()
    f += [pause(2000)]

    # ── Scene 7: Read winning config ──────────────────────────────────────────
    f += section("STEP 6 — Read winning approach: kaos read arch-explorer /results/best_config.md")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos read arch-explorer /results/best_config.md")
    f += blank()
    f += out(f"  {B}# Winning Config — arch-explorer  val_loss=1.89{R}")
    f += blank()
    f += out(f"  {B}## Architecture{R}")
    f += out(f"  {DG}  method:         LoRA (rank=16, alpha=32){R}")
    f += out(f"  {DG}  target_modules: [q_proj, v_proj]{R}")
    f += out(f"  {DG}  trainable_params: 4.2M  (vs 117M full finetune){R}")
    f += blank()
    f += out(f"  {B}## Training{R}")
    f += out(f"  {DG}  optimizer:  AdamW  lr=3e-4  weight_decay=0.1{R}")
    f += out(f"  {DG}  scheduler:  cosine  warmup_steps=500{R}")
    f += out(f"  {DG}  batch_size: 64  grad_clip=1.0{R}")
    f += out(f"  {DG}  epochs:     5  early_stopping: val_loss plateau 2 epochs{R}")
    f += blank()
    f += out(f"  {B}## Key insight{R}")
    f += out(f"  {G}  LoRA enables efficient fine-tuning: -19.2% val_loss with 3.6% of params.{R}")
    f += out(f"  {G}  Cosine LR with warmup prevented early divergence seen in full finetune.{R}")
    f += blank()
    f += [pause(2400)]

    # ── Scene 8: Checkpoint and seed next search ──────────────────────────────
    f += section("STEP 7 — Checkpoint winner + seed Meta-Harness for next search")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos checkpoint arch-explorer --label winner-v1")
    f += out(f"  {G}✓{R}  Checkpoint  {DG}[winner-v1]{R}  created  {DG}snapshot_id=ckpt_f93d12{R}")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos mh search -b char_lm --seed-from arch-explorer -n 10 --background")
    f += blank()
    f += out(f"  {G}✓{R}  Benchmark loaded: {BY}char_lm{R}")
    f += out(f"  {G}✓{R}  Seeded from arch-explorer checkpoint  {DG}(LoRA + cosine best config){R}")
    f += out(f"  {G}✓{R}  Meta-Harness search launched  {DG}PID 18291  10 iterations background{R}")
    f += out(f"  {DG}  Seeds: winner-v1 config loaded into iteration 0 frontier{R}")
    f += out(f"  {DG}  Next search starts from val_loss=1.89 — not from scratch{R}")
    f += blank()
    f += [pause(1800)]

    # ── Scene 9: Summary ──────────────────────────────────────────────────────
    f += separator(700)
    f += out(f"  {BG}Overnight search complete.{R}  4 hypotheses explored, winner found, knowledge seeded.")
    f += separator()
    f += blank()
    f += out(f"  {DG}Baseline val_loss:{R}   {BR}2.34{R}")
    f += out(f"  {DG}Winner val_loss:{R}     {BG}1.89{R}  {DG}(-19.2%)  arch-explorer (LoRA + cosine LR){R}")
    f += out(f"  {DG}Runner-up:{R}           {G}1.97{R}  {DG}optim-explorer (Lion optimizer){R}")
    f += out(f"  {DG}Agents run:{R}          4  {DG}(all isolated, all finished independently){R}")
    f += out(f"  {DG}Next step:{R}           Meta-Harness refining from val_loss=1.89 tonight{R}")
    f += blank()
    f += out(f"  {DG}Inspired by Karpathy's autoresearch — KAOS adds VFS isolation + full audit trail{R}")
    f += blank()
    f += [pause(4000)]

    return f


# ── YAML output ────────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_yml = os.path.join(script_dir, "kaos_uc_mllab.yml")

    records = build()
    config  = make_config("KAOS — 4 ML Hypotheses, 4 Agents, 1 Night: Autonomous Research Lab")

    doc = {"config": config, "records": records}
    with open(out_yml, "w", encoding="utf-8") as fh:
        yaml.dump(doc, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    total_ms = sum(r.get("delay", 0) for r in records)
    print(f"Written: {out_yml}")
    print(f"Frames:  {len(records)}")
    print(f"Est. duration: {total_ms/1000:.1f}s")
    print(f"\nRender with:")
    print(f"  uv run python render_gif.py kaos_uc_mllab.yml")


if __name__ == "__main__":
    main()
