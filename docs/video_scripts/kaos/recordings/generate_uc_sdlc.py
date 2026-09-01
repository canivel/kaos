"""
Generate a self-healing code pipeline demo recording.

Story: A payment processing service has a flaky test that just started failing
after a refactor. An agent detects the regression, checkpoints, attempts fix 1
(wrong — breaks 3 MORE tests), auto-restores from checkpoint, reads failure
diagnostics from VFS, tries fix 2 (correct — all tests pass). Full SQL audit.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_sdlc.py
    uv run python render_gif.py kaos_uc_sdlc.yml
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
    f += blank()
    f += blank()
    f += out(f"  {B}{CY}KAOS — Self-Healing Code Pipeline{R}")
    f += out(f"  {DG}Detect · Checkpoint · Fix · Rollback · Fix again · Ship{R}")
    f += blank()
    f += out(f"  {DG}Service:{R}   {BY}payment-svc{R}  {DG}(payment processing backend){R}")
    f += out(f"  {DG}Problem:{R}   test suite just started failing after a refactor")
    f += out(f"  {DG}Failure:{R}   {RD}test_payment_decimal_precision{R}  {DG}— 1 test, introduced silently{R}")
    f += blank()
    f += out(f"  {DG}Test output:{R}")
    f += blank()
    f += out(f"  {DG}FAILED tests/test_payment.py::test_payment_decimal_precision{R}")
    f += out(f"  {DG}  AssertionError: {R}{RD}10.00 != 10.0{R}")
    f += out(f"  {DG}  assert calculate_total(5, 2) == Decimal('10.00'){R}")
    f += out(f"  {DG}  refactor changed float(amount) path — decimal precision lost{R}")
    f += blank()
    f += out(f"  {DG}KAOS will:{R}  checkpoint → try fix 1 (wrong) → auto-rollback → fix 2 (correct){R}")
    f += blank()
    f += [pause(3200)]
    f += [pause(2000)]

    # ── Scene 2: kaos ls ──────────────────────────────────────────────────────
    f += prompt_line()
    f += type_cmd("kaos ls")
    f += blank()
    f += out(f"  {B}agent_id{R}          {B}status{R}   {B}files{R}   {B}size{R}     {B}created{R}")
    f += out(f"  {DG}────────────────  ───────  ──────  ───────  ─────────────────────{R}")
    f += out(f"  {G}payment-svc{R}       {G}active{R}    {BY}14{R}      {BY}38 KB{R}   2026-04-10 09:14:03")
    f += out(f"  {DG}payment-qa{R}        idle      0       —        —")
    f += blank()
    f += out(f"  {DG}payment-svc VFS:{R}  src/payment.py  src/invoice.py  src/refund.py")
    f += out(f"                    tests/test_payment.py  {DG}(47 tests, 1 failing){R}")
    f += blank()
    f += [pause(1400)]

    # ── Scene 3: Detect regression ────────────────────────────────────────────
    f += section("STEP 1 — Detect regression: run test suite")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos mcp agent_spawn payment-qa")
    f += blank()
    f += out(f"  {G}✓{R}  Spawning agent  {DG}payment-qa{R}")
    f += out(f"  {G}✓{R}  VFS snapshot of payment-svc  {DG}→  payment-qa:/workspace/{R}")
    f += out(f"  {G}✓{R}  Agent ready  {DG}[01JPAY-QA-d9f2]{R}")
    f += blank()
    f += out(f"  {DG}Running: pytest tests/ -v --tb=short{R}")
    f += blank()
    f += [pause(1200)]
    f += out(f"  {G}tests/test_payment.py::test_payment_zero_amount{R}           {G}PASSED{R}", 70)
    f += out(f"  {G}tests/test_payment.py::test_payment_negative{R}              {G}PASSED{R}", 70)
    f += out(f"  {G}tests/test_payment.py::test_currency_formatting{R}           {G}PASSED{R}", 70)
    f += out(f"  {Y}tests/test_payment.py::test_payment_decimal_precision{R}     {RD}FAILED{R}", 80)
    f += out(f"  {G}tests/test_payment.py::test_invoice_total{R}                 {G}PASSED{R}", 70)
    f += out(f"  {G}tests/test_payment.py::test_refund_amount{R}                 {G}PASSED{R}", 70)
    f += out(f"  {G}tests/test_payment.py::test_currency_rounding{R}             {G}PASSED{R}", 70)
    f += out(f"  {DG}  ... (40 more passed){R}", 60)
    f += blank()
    f += out(f"  {DG}─────────────────────────────────────────────────────────────────────{R}")
    f += out(f"  {RD}FAILED{R}  tests/test_payment.py::{RD}test_payment_decimal_precision{R}")
    f += out(f"  {DG}  E   AssertionError: {R}{RD}Decimal('10.00') != 10.0{R}")
    f += out(f"  {DG}  E   assert calculate_total(5, 2) == Decimal('10.00'){R}")
    f += blank()
    f += out(f"  {BY}46 passed{R}, {RD}1 failed{R}  {DG}in 2.1s{R}")
    f += blank()
    f += [pause(1600)]

    # ── Scene 4: Checkpoint before fix ───────────────────────────────────────
    f += section("STEP 2 — Checkpoint before attempting fix")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos checkpoint payment-svc --label pre-fix-attempt")
    f += blank()
    f += out(f"  {G}✓{R}  Checkpoint created")
    f += out(f"  {DG}  id:      {R}{BY}ckpt_7f3a9b2c{R}")
    f += out(f"  {DG}  label:   {R}{G}pre-fix-attempt{R}")
    f += out(f"  {DG}  files:   {R}{BY}14{R}  files snapshotted")
    f += out(f"  {DG}  size:    {R}{BY}38.2 KB{R}  compressed to  {BY}11.4 KB{R}  {DG}(70% savings, content-addressed){R}")
    f += out(f"  {DG}  time:    {R}2026-04-10 09:14:47 UTC")
    f += out(f"  {DG}  blobs:   {R}14 refs stored in blob store  {DG}[kaos.db/blobs]{R}")
    f += blank()
    f += out(f"  {DG}Checkpoint is immutable. Restoring will not create new blobs.{R}")
    f += blank()
    f += [pause(1400)]

    # ── Scene 5: Wrong fix ────────────────────────────────────────────────────
    f += section("STEP 3 — Fix attempt 1 (wrong approach)")
    f += blank()
    f += out(f"  {DG}Agent reasoning: decimal precision issue → convert to float, let Python handle it{R}")
    f += out(f"  {DG}Agent writes patch to  {R}{BY}payment-svc:/src/payment.py{R}")
    f += blank()
    f += out(f"  {DG}─── src/payment.py  (patch applied) ────────────────────────────────{R}")
    f += out(f"  {RD}- amount_dec = Decimal(amount){R}")
    f += out(f"  {BG}+ amount_dec = float(amount)   {DG}# ← WRONG: loses Decimal precision guarantees{R}")
    f += out(f"  {DG}─────────────────────────────────────────────────────────────────────{R}")
    f += blank()
    f += out(f"  {DG}Running: pytest tests/ -v --tb=short{R}")
    f += blank()
    f += [pause(500)]
    f += out(f"  {G}tests/test_payment.py::test_payment_zero_amount{R}           {G}PASSED{R}", 70)
    f += out(f"  {G}tests/test_payment.py::test_payment_negative{R}              {G}PASSED{R}", 70)
    f += out(f"  {Y}tests/test_payment.py::test_payment_decimal_precision{R}     {RD}FAILED{R}", 80)
    f += out(f"  {Y}tests/test_payment.py::test_currency_rounding{R}             {RD}FAILED{R}", 80)
    f += out(f"  {Y}tests/test_payment.py::test_invoice_total{R}                 {RD}FAILED{R}", 80)
    f += out(f"  {Y}tests/test_payment.py::test_refund_amount{R}                 {RD}FAILED{R}", 80)
    f += out(f"  {DG}  ... (43 more passed){R}", 60)
    f += blank()
    f += out(f"  {DG}─────────────────────────────────────────────────────────────────────{R}")
    f += out(f"  {BY}43 passed{R}, {RD}4 failed{R}  {DG}in 2.4s{R}")
    f += blank()
    f += separator(500)
    f += out(f"  {BR}✗  Regression detected: 3 new failures introduced{R}")
    f += out(f"  {DG}  float() strips Decimal type guarantees — rounding errors cascade{R}")
    f += out(f"  {DG}  Failed: test_currency_rounding  test_invoice_total  test_refund_amount{R}")
    f += separator()
    f += blank()
    f += [pause(2400)]

    # ── Scene 6: Auto-restore ─────────────────────────────────────────────────
    f += section("STEP 4 — Auto-restore from checkpoint")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos restore payment-svc --label pre-fix-attempt")
    f += blank()
    f += out(f"  {G}✓{R}  Restoring  {DG}payment-svc{R}  from checkpoint  {BY}ckpt_7f3a9b2c{R}  {DG}(pre-fix-attempt){R}")
    f += out(f"  {G}✓{R}  14 files restored from blob store")
    f += out(f"  {G}✓{R}  VFS state matches checkpoint exactly  {DG}(content-hash verified){R}")
    f += out(f"  {G}✓{R}  Restore complete  {DG}in 0.03s{R}")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos diff payment-svc pre-fix-attempt HEAD")
    f += blank()
    f += out(f"  {DG}Diff: checkpoint  {G}pre-fix-attempt{R}  →  {BY}HEAD{R}  {DG}(what was undone){R}")
    f += blank()
    f += out(f"  {DG}  src/payment.py{R}  {DG}(restored to pre-attempt state){R}")
    f += out(f"  {BG}  + amount_dec = Decimal(amount)   {DG}← restored original{R}")
    f += out(f"  {RD}  - amount_dec = float(amount)     {DG}← wrong fix removed{R}")
    f += blank()
    f += out(f"  {DG}  No other files changed.  VFS is clean.{R}")
    f += blank()
    f += [pause(2000)]

    # ── Scene 7: Read failure diagnostics ────────────────────────────────────
    f += section("STEP 5 — Read failure diagnostics from VFS")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos read payment-svc /qa/failure_report.md")
    f += blank()
    f += out(f"  {B}{CY}Failure Report — payment-svc{R}  {DG}generated by payment-qa agent{R}")
    f += out(f"  {DG}───────────────────────────────────────────────────────────────────{R}")
    f += blank()
    f += out(f"  {BY}Root Cause{R}")
    f += out(f"  {DG}  src/payment.py line 34:{R}")
    f += out(f"  {DG}    calculate_total() uses Decimal arithmetic internally{R}")
    f += out(f"  {DG}    but the refactor broke the entry-point coercion path{R}")
    f += blank()
    f += out(f"  {BY}Specific Issue{R}")
    f += out(f"  {DG}  The function must return Decimal, not float.{R}")
    f += out(f"  {DG}  round() loses precision on .005 boundary values.{R}")
    f += out(f"  {RD}  round(10.005, 2) → 10.0   (float rounding — WRONG){R}")
    f += out(f"  {G}  Decimal('10.005').quantize(Decimal('0.01')) → 10.01  (correct){R}")
    f += blank()
    f += out(f"  {BY}Affected Lines{R}")
    f += out(f"  {DG}  src/payment.py:34  — amount coercion (entry point){R}")
    f += out(f"  {DG}  src/payment.py:41  — final return value must stay Decimal{R}")
    f += blank()
    f += out(f"  {BY}Recommended Fix{R}")
    f += out(f"  {G}  Use Decimal(str(amount)).quantize(Decimal('0.01'))){R}")
    f += out(f"  {DG}  Never use float() on monetary values. Never use round() on Decimal.{R}")
    f += blank()
    f += [pause(1800)]

    # ── Scene 8: Correct fix ──────────────────────────────────────────────────
    f += section("STEP 6 — Fix attempt 2 (correct approach)")
    f += blank()
    f += out(f"  {DG}Agent reads diagnostics → applies the correct fix{R}")
    f += out(f"  {DG}Agent writes patch to  {R}{BY}payment-svc:/src/payment.py{R}")
    f += blank()
    f += out(f"  {DG}─── src/payment.py  (patch applied) ────────────────────────────────{R}")
    f += out(f"  {RD}- amount_dec = Decimal(amount){R}")
    f += out(f"  {BG}+ amount_dec = Decimal(str(amount)).quantize(Decimal('0.01')){R}")
    f += out(f"  {DG}─────────────────────────────────────────────────────────────────────{R}")
    f += blank()
    f += out(f"  {DG}Running: pytest tests/ -v --tb=short{R}")
    f += blank()
    f += [pause(1100)]
    f += out(f"  {G}tests/test_payment.py::test_payment_zero_amount{R}           {G}PASSED{R}", 65)
    f += out(f"  {G}tests/test_payment.py::test_payment_negative{R}              {G}PASSED{R}", 65)
    f += out(f"  {G}tests/test_payment.py::test_payment_decimal_precision{R}     {G}PASSED{R}", 65)
    f += out(f"  {G}tests/test_payment.py::test_currency_rounding{R}             {G}PASSED{R}", 65)
    f += out(f"  {G}tests/test_payment.py::test_invoice_total{R}                 {G}PASSED{R}", 65)
    f += out(f"  {G}tests/test_payment.py::test_refund_amount{R}                 {G}PASSED{R}", 65)
    f += out(f"  {G}tests/test_payment.py::test_currency_formatting{R}           {G}PASSED{R}", 65)
    f += out(f"  {DG}  ... (40 more passed){R}", 60)
    f += blank()
    f += out(f"  {DG}─────────────────────────────────────────────────────────────────────{R}")
    f += out(f"  {BG}47 passed{R}  {DG}in 2.3s{R}  {DG}— 0 failed{R}")
    f += blank()
    f += separator(600)
    f += out(f"  {BG}✓  All tests pass.  Fix is correct.  Ready to ship.{R}")
    f += separator()
    f += blank()
    f += [pause(2500)]

    # ── Scene 9: SQL audit trail ──────────────────────────────────────────────
    f += section("STEP 7 — SQL audit trail")
    f += blank()
    f += prompt_line()
    f += type_cmd('kaos --json query "SELECT timestamp, tool_name, content FROM vfs_events WHERE agent_id=\'payment-svc\' ORDER BY timestamp"')
    f += blank()
    f += out(f"  {B}timestamp{R}             {B}tool_name{R}         {B}content{R}")
    f += out(f"  {DG}────────────────────  ────────────────  ─────────────────────────────────────────{R}")
    f += out(f"  {DG}2026-04-10 09:14:03{R}  {CY}agent_write{R}      src/payment.py  {DG}(original, Decimal(amount)){R}", 55)
    f += out(f"  {DG}2026-04-10 09:14:19{R}  {CY}agent_write{R}      src/invoice.py  {DG}(original){R}", 55)
    f += out(f"  {DG}2026-04-10 09:14:22{R}  {CY}agent_write{R}      src/refund.py   {DG}(original){R}", 55)
    f += out(f"  {DG}2026-04-10 09:14:47{R}  {G}checkpoint{R}       pre-fix-attempt  {DG}ckpt_7f3a9b2c  14 files{R}", 55)
    f += out(f"  {DG}2026-04-10 09:15:02{R}  {RD}agent_write{R}      src/payment.py  {DG}(wrong fix: float(amount)){R}", 55)
    f += out(f"  {DG}2026-04-10 09:15:11{R}  {BR}test_runner{R}      FAIL  4 failures detected", 55)
    f += out(f"  {DG}2026-04-10 09:15:12{R}  {Y}restore{R}          pre-fix-attempt  {DG}→  ckpt_7f3a9b2c  14 files{R}", 55)
    f += out(f"  {DG}2026-04-10 09:15:29{R}  {CY}agent_read{R}       /qa/failure_report.md  {DG}(diagnostics read){R}", 55)
    f += out(f"  {DG}2026-04-10 09:15:38{R}  {G}agent_write{R}      src/payment.py  {DG}(correct fix: quantize){R}", 55)
    f += out(f"  {DG}2026-04-10 09:15:47{R}  {BG}test_runner{R}      PASS  47 passed  {DG}in 2.3s{R}", 55)
    f += blank()
    f += out(f"  {DG}10 events  │  full history preserved  │  queryable forever{R}")
    f += blank()
    f += [pause(1200)]

    # ── Scene 10: Summary card ────────────────────────────────────────────────
    f += section("Result — Self-healing pipeline complete")
    f += blank()
    f += out(f"  {DG}Timeline:{R}")
    f += blank()
    f += out(f"  {DG}09:14:03{R}  {G}✓{R}  Agent payment-qa spawned, VFS snapshot ready")
    f += out(f"  {DG}09:14:19{R}  {RD}✗{R}  Regression detected: test_payment_decimal_precision")
    f += out(f"  {DG}09:14:47{R}  {G}✓{R}  Checkpoint  {BY}pre-fix-attempt{R}  created  {DG}(ckpt_7f3a9b2c){R}")
    f += out(f"  {DG}09:15:02{R}  {RD}✗{R}  Fix attempt 1: float(amount)  {RD}→  4 failures{R}  {DG}(worse){R}")
    f += out(f"  {DG}09:15:12{R}  {Y}↩{R}  Auto-restore from checkpoint  {DG}(0.03s, content-hash verified){R}")
    f += out(f"  {DG}09:15:29{R}  {CY}→{R}  Read failure diagnostics from VFS  {DG}(/qa/failure_report.md){R}")
    f += out(f"  {DG}09:15:38{R}  {G}✓{R}  Fix attempt 2: Decimal(str(amount)).quantize(Decimal('0.01'))")
    f += out(f"  {DG}09:15:47{R}  {BG}✓{R}  {BG}47 passed, 0 failed — ready to ship{R}")
    f += blank()
    f += out(f"  {DG}Total time:{R}    {BY}1 min 44 sec{R}  {DG}from detection to green{R}")
    f += out(f"  {DG}Rollbacks:{R}     {BY}1{R}  {DG}(automatic, 0.03s){R}")
    f += out(f"  {DG}Fix attempts:{R}  {BY}2{R}  {DG}(wrong, then correct){R}")
    f += out(f"  {DG}Audit events:{R}  {BY}10{R}  {DG}(every action recorded, SQL-queryable){R}")
    f += blank()
    f += out(f"  {G}The VFS checkpoint made wrong-fix recovery trivial.{R}")
    f += out(f"  {G}Failure diagnostics written by the QA agent guided the correct fix.{R}")
    f += blank()
    f += [pause(3000)]
    f += [pause(2000)]

    return f


# ── YAML output ────────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_yml = os.path.join(script_dir, "kaos_uc_sdlc.yml")

    records = build()
    config  = make_config("KAOS — Self-Healing Pipeline: Bug, Rollback, Fix, Ship")

    doc = {"config": config, "records": records}
    with open(out_yml, "w", encoding="utf-8") as fh:
        yaml.dump(doc, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)

    total_ms = sum(r.get("delay", 0) for r in records)
    word_count = sum(len(r.get("content", "").split()) for r in records)
    print(f"Written: {out_yml}")
    print(f"Frames:  {len(records)}")
    print(f"Est. duration: {total_ms/1000:.1f}s")
    print(f"Word count (approx): {word_count}")
    print(f"\nRender with:")
    print(f"  uv run python render_gif.py kaos_uc_sdlc.yml")


if __name__ == "__main__":
    main()
