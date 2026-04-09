"""
Generate terminalizer YAML recordings for KAOS end-to-end use cases.
Each recording shows a realistic workflow from scratch to results.

Use cases:
  uc01_code_review_swarm        - 4 agents reviewing code in parallel
  uc02_self_healing_agent       - checkpoint + auto-restore on failure
  uc03_post_mortem_debug        - SQL queries to diagnose a failed agent
  uc04_meta_harness_classifier  - full meta-harness search: 45% → 87%
  uc05_parallel_refactor        - tests + refactor + docs in parallel
  uc06_fraud_detection          - meta-harness on fraud data
  uc07_autonomous_research      - 4 ML hypothesis agents + SQL results
  uc08_coevolution_coral        - 3 agents co-evolving with skills
"""
import random
import yaml
import os

R  = "\u001b[0m"; B  = "\u001b[1m"
G  = "\u001b[32m"; Y  = "\u001b[33m"; BL = "\u001b[34m"
MG = "\u001b[35m"; CY = "\u001b[36m"; DG = "\u001b[90m"
BG = "\u001b[92m"; BY = "\u001b[93m"; BC = "\u001b[96m"
BB = "\u001b[94m"; RD = "\u001b[31m"

PROMPT = f"{G}❯{R} "
CRLF   = "\r\n"

def prompt():
    return [{"delay": 420, "content": CRLF + PROMPT}]

def type_cmd(cmd, wpm=200):
    frames = []
    for ch in cmd:
        delay = int(60000 / (wpm * 5)) + random.randint(-8, 15)
        frames.append({"delay": max(28, delay), "content": ch})
    frames.append({"delay": 160, "content": CRLF})
    return frames

def out(text, delay=55):
    return [{"delay": delay, "content": text}]

def section(title):
    bar = "─" * (len(title) + 4)
    return out(f"{CRLF}{DG}┌{bar}┐{CRLF}│  {BY}{title}{DG}  │{CRLF}└{bar}┘{R}{CRLF}")

def make_config(title):
    return {
        "command": "bash", "cwd": None,
        "env": {"recording": True},
        "cols": 108, "rows": 34,
        "repeat": 0, "quality": 100,
        "frameDelay": "auto", "maxIdleTime": 1800,
        "frameBox": {"type": "window", "title": title,
                     "style": {"border": "0px black solid"}},
        "watermark": {"imagePath": None, "style": {
            "position": "absolute", "right": "15px", "bottom": "15px",
            "width": "80px", "opacity": "0.8"}},
        "cursorStyle": "bar",
        "fontFamily": '"JetBrains Mono, Fira Code, Consolas, Monospace"',
        "fontSize": 13, "lineHeight": 1.2, "letterSpacing": 0,
        "theme": {
            "background": "#0d1117", "foreground": "#c9d1d9",
            "cursor": "#58a6ff", "black": "#161b22",
            "red": "#ff7b72", "green": "#3fb950", "yellow": "#e3b341",
            "blue": "#58a6ff", "magenta": "#bc8cff", "cyan": "#39c5cf",
            "white": "#b1bac4", "brightBlack": "#6e7681",
            "brightRed": "#ffa198", "brightGreen": "#56d364",
            "brightYellow": "#e3b341", "brightBlue": "#79c0ff",
            "brightMagenta": "#d2a8ff", "brightCyan": "#56d4dd",
            "brightWhite": "#f0f6fc",
        },
    }

def build(title, records):
    return {"config": make_config(title), "records": records}


# ─────────────────────────────────────────────────────────────────────────────
# UC 01 — Code Review Swarm
# ─────────────────────────────────────────────────────────────────────────────
def uc01_code_review_swarm():
    r = []
    r += section("KAOS Use Case 01 — Code Review Swarm")

    r += prompt()
    r += type_cmd("kaos init")
    r += out(f"{BG}✓{R} Database initialized: {CY}kaos.db{R}{CRLF}")

    r += prompt()
    r += type_cmd("cat examples/code_review_swarm.py")
    r += out(
        f"{CRLF}"
        f"{DG}# Spawn 4 agents to review auth.py from different angles{R}{CRLF}"
        f"{MG}results{R} = {CY}await{R} ccr.run_parallel([{CRLF}"
        f'    {{"name": {G}"security"{R},    "prompt": {G}"Find vulns in auth.py"{R}}},{CRLF}'
        f'    {{"name": {G}"performance"{R}, "prompt": {G}"Find perf bottlenecks"{R}}},{CRLF}'
        f'    {{"name": {G}"style"{R},       "prompt": {G}"Review style & best practices"{R}}},{CRLF}'
        f'    {{"name": {G}"test-gaps"{R},   "prompt": {G}"What test cases are missing?"{R}}},{CRLF}'
        f"]){CRLF}"
    )

    r += prompt()
    r += type_cmd("python examples/code_review_swarm.py")
    r += out(
        f"{CRLF}"
        f"{BL}GEPA{R} classifying tasks...{CRLF}"
        f"  security    → {MG}local_strong{R}  (complex){CRLF}"
        f"  performance → {MG}local_strong{R}  (complex){CRLF}"
        f"  style       → {CY}local_fast{R}   (standard){CRLF}"
        f"  test-gaps   → {CY}local_fast{R}   (standard){CRLF}"
        f"{CRLF}"
        f"Launching 4 agents in parallel...{CRLF}"
    )
    r += [{"delay": 800, "content": ""}]
    r += out(
        f"  {DG}[███████░░░]{R} security     {Y}running{R}  → tool_call: Read /src/auth.py{CRLF}"
        f"  {DG}[█████░░░░░]{R} performance  {Y}running{R}  → tool_call: Read /src/auth.py{CRLF}"
        f"  {DG}[██████████]{R} style        {BG}done{R}     ✓{CRLF}"
        f"  {DG}[█████████░]{R} test-gaps    {Y}running{R}  → writing /review.md{CRLF}"
    )
    r += [{"delay": 1200, "content": ""}]
    r += out(
        f"\r  {DG}[██████████]{R} security     {BG}done{R}     ✓{CRLF}"
        f"  {DG}[██████████]{R} performance  {BG}done{R}     ✓{CRLF}"
        f"  {DG}[██████████]{R} test-gaps    {BG}done{R}     ✓{CRLF}"
        f"{CRLF}"
        f"  {BG}All 4 agents completed in 47s{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos read $(kaos --json ls | python -c \"import sys,json;print([a['agent_id'] for a in json.load(sys.stdin) if a['name']=='security'][0])\") /review.md | head -20")
    r += out(
        f"{CRLF}"
        f"{B}# Security Review — auth.py{R}{CRLF}"
        f"{CRLF}"
        f"{RD}## CRITICAL: SQL Injection{R}{CRLF}"
        f"Line 47: `query = f\"SELECT * FROM users WHERE email='{{email}}'\"`{CRLF}"
        f"→ Unparameterized query. Use `db.execute('... WHERE email=?', [email])`.{CRLF}"
        f"{CRLF}"
        f"{Y}## HIGH: Timing Attack in password comparison{R}{CRLF}"
        f"Line 63: `if user.password == hash(password):`{CRLF}"
        f"→ Use `hmac.compare_digest()` for constant-time comparison.{CRLF}"
        f"{CRLF}"
        f"{G}## INFO: JWT expiry not validated{R}{CRLF}"
        f"Line 89: token decoded without checking `exp` claim.{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos query \"SELECT a.name, COUNT(tc.call_id) calls, SUM(tc.token_count) tokens FROM agents a JOIN tool_calls tc ON a.agent_id=tc.agent_id GROUP BY a.name\"")
    r += out(
        f"{CRLF}"
        f"  {B}name         calls  tokens{R}{CRLF}"
        f"  {'─'*12}  {'─'*5}  {'─'*7}{CRLF}"
        f"  security        18    5,240{CRLF}"
        f"  performance     14    4,180{CRLF}"
        f"  style            9    1,820{CRLF}"
        f"  test-gaps       11    2,340{CRLF}"
        f"  {'─'*12}  {'─'*5}  {'─'*7}{CRLF}"
        f"  {DG}TOTAL           52   13,580{R}{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1800, "content": ""}]
    return build("KAOS — Code Review Swarm", r)


# ─────────────────────────────────────────────────────────────────────────────
# UC 02 — Self-Healing Agent
# ─────────────────────────────────────────────────────────────────────────────
def uc02_self_healing():
    r = []
    r += section("KAOS Use Case 02 — Self-Healing Agent")

    r += prompt()
    r += type_cmd("cat examples/self_healing_agent.py")
    r += out(
        f"{CRLF}"
        f"{DG}# Checkpoint before risky work, auto-restore on failure{R}{CRLF}"
        f"{MG}cp{R} = db.{CY}checkpoint{R}(agent, label={G}\"pre-migration\"{R}){CRLF}"
        f"{MG}try{R}:{CRLF}"
        f"    result = {CY}await{R} ccr.run_agent(agent, {G}\"Migrate schema to v3\"{R}){CRLF}"
        f"{MG}except{R} Exception:{CRLF}"
        f"    db.{CY}restore{R}(agent, cp)  {DG}# roll back — others unaffected{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("python examples/self_healing_agent.py")
    r += out(f"{CRLF}Running migration agent...{CRLF}")
    r += [{"delay": 600, "content": ""}]
    r += out(
        f"  {BG}✓{R} checkpoint created: {CY}pre-migration{R}{CRLF}"
        f"  {Y}→{R} agent writing /migrations/v3.sql ...{CRLF}"
        f"  {Y}→{R} agent running: ALTER TABLE users ADD COLUMN ...{CRLF}"
        f"  {Y}→{R} agent running: UPDATE users SET ...{CRLF}"
    )
    r += [{"delay": 900, "content": ""}]
    r += out(
        f"  {RD}✗{R} Migration failed: constraint violation on users.email{CRLF}"
        f"  {Y}→{R} Restoring to checkpoint pre-migration ...{CRLF}"
    )
    r += [{"delay": 500, "content": ""}]
    r += out(
        f"  {BG}✓{R} Restored. Database is clean.{CRLF}"
        f"  {DG}Other agents: unaffected (running 3/3){R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos diff $(kaos --json ls | python -c \"import sys,json;d=json.load(sys.stdin);print(d[0]['agent_id'])\") --from pre-migration --to latest")
    r += out(
        f"{CRLF}"
        f"  {B}Diff: pre-migration → latest (restored){R}{CRLF}"
        f"  {DG}No differences — restore was clean.{R}{CRLF}"
        f"{CRLF}"
        f"  {BG}Agent state matches pre-migration checkpoint exactly.{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos logs $(kaos --json ls | python -c \"import sys,json;d=json.load(sys.stdin);print(d[0]['agent_id'])\") --tail 8")
    r += out(
        f"{CRLF}"
        f"  {DG}[14:02:01]{R} {CY}checkpoint{R}   pre-migration — 4 files, 3 state keys{CRLF}"
        f"  {DG}[14:02:04]{R} {CY}file_write{R}   /migrations/v3.sql{CRLF}"
        f"  {DG}[14:02:07]{R} {BL}tool_call {R}   bash: psql migrate.sql      {RD}exit 1{R}{CRLF}"
        f"  {DG}[14:02:07]{R} {Y}restore   {R}   → checkpoint pre-migration{CRLF}"
        f"  {DG}[14:02:07]{R} {BG}file_del  {R}   /migrations/v3.sql (rolled back){CRLF}"
        f"  {DG}[14:02:07]{R} {CY}state_set {R}   status=rolled_back{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1800, "content": ""}]
    return build("KAOS — Self-Healing Agent", r)


# ─────────────────────────────────────────────────────────────────────────────
# UC 03 — Post-Mortem Debugging
# ─────────────────────────────────────────────────────────────────────────────
def uc03_post_mortem():
    r = []
    r += section("KAOS Use Case 03 — Post-Mortem Debugging")

    r += prompt()
    r += type_cmd("# Agent broke something. Let's find out exactly what.")
    r += out(f"{CRLF}")

    r += prompt()
    r += type_cmd("kaos logs refactor-agent --tail 12")
    r += out(
        f"{CRLF}"
        f"  {DG}[10:41:55]{R} {CY}file_write{R}   /src/auth.py           1,240 bytes{CRLF}"
        f"  {DG}[10:42:01]{R} {BL}tool_call {R}   bash: pytest tests/     {BG}exit 0{R}{CRLF}"
        f"  {DG}[10:42:08]{R} {CY}file_write{R}   /src/database.py        2,108 bytes{CRLF}"
        f"  {DG}[10:42:11]{R} {BL}tool_call {R}   bash: pytest tests/     {RD}exit 1{R}{CRLF}"
        f"  {DG}[10:42:12]{R} {CY}file_write{R}   /src/database.py        2,894 bytes  {Y}← modified again{R}{CRLF}"
        f"  {DG}[10:42:19]{R} {BL}tool_call {R}   bash: python migrate.py {RD}exit 2{R}{CRLF}"
        f"  {DG}[10:42:20]{R} {RD}agent_fail{R}   uncaught exception{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos query \"SELECT tool_name, json_extract(payload,'$.command') cmd, json_extract(payload,'$.exit_code') rc FROM tool_calls WHERE agent_id=(SELECT agent_id FROM agents WHERE name='refactor-agent') AND json_extract(payload,'$.exit_code') != 0\"")
    r += out(
        f"{CRLF}"
        f"  {B}tool_name  cmd                  rc{R}{CRLF}"
        f"  {'─'*10}  {'─'*20}  {'─'*3}{CRLF}"
        f"  bash       pytest tests/         {RD}1{R}{CRLF}"
        f"  bash       python migrate.py     {RD}2{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos search \"DROP TABLE\" --agent refactor-agent")
    r += out(
        f"{CRLF}"
        f"  {RD}1{R} match:{CRLF}"
        f"  {CY}refactor-agent/src/database.py{R}:{Y}3{R}    {RD}DROP TABLE IF EXISTS sessions;{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos diff refactor-agent --from pre-iter-2 --to post-iter-2")
    r += out(
        f"{CRLF}"
        f"  {B}Files changed:{R}{CRLF}"
        f"  {Y}MODIFIED{R}  /src/database.py{CRLF}"
        f"  {RD}  -{R} {DG}# create sessions table{R}{CRLF}"
        f"  {RD}  -{R} CREATE TABLE IF NOT EXISTS sessions ({CRLF}"
        f"  {RD}  -{R}     id TEXT PRIMARY KEY, user_id TEXT, expires_at TEXT{CRLF}"
        f"  {RD}  -{R} );{CRLF}"
        f"  {BG}  +{R} DROP TABLE IF EXISTS sessions;  {RD}← here's the bug{R}{CRLF}"
        f"{CRLF}"
        f"  {B}Root cause identified.{R} Restore to pre-iter-2 and retry.{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos restore refactor-agent --checkpoint pre-iter-2")
    r += out(f"{CRLF}{BG}✓{R} Restored. Clean state. Ready to retry.{CRLF}")
    r += prompt()
    r += [{"delay": 1800, "content": ""}]
    return build("KAOS — Post-Mortem Debugging", r)


# ─────────────────────────────────────────────────────────────────────────────
# UC 04 — Meta-Harness: Support Ticket Classifier 45% → 87%
# ─────────────────────────────────────────────────────────────────────────────
def uc04_meta_harness_classifier():
    r = []
    r += section("KAOS Use Case 04 — Meta-Harness: 45% → 87% Accuracy")

    r += prompt()
    r += type_cmd("# Start: our support ticket classifier gets 45% accuracy.")
    r += out(f"{CRLF}")

    r += prompt()
    r += type_cmd("kaos mh search --benchmark text_classify --iterations 10 --background")
    r += out(
        f"{CRLF}"
        f"{BG}✓{R} Search started  {CY}01JQMHS...{R}{CRLF}"
        f"  Evaluating 3 seed harnesses...{CRLF}"
    )
    r += [{"delay": 700, "content": ""}]
    r += out(
        f"  Seed 1 (zero-shot):    acc={Y}0.45{R}  cost=0.28  {DG}← baseline{R}{CRLF}"
        f"  Seed 2 (few-shot-3):   acc={Y}0.61{R}  cost=0.54{CRLF}"
        f"  Seed 3 (cot-prompt):   acc={Y}0.68{R}  cost=0.71{CRLF}"
        f"  {DG}Initial frontier: 2 points{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("# Watch iterations run...")
    r += out(f"{CRLF}")

    r += prompt()
    r += type_cmd("kaos mh status 01JQMHS...")
    r += out(
        f"{CRLF}"
        f"  Iter 3: acc={BG}0.74{R}  {BG}↑ new frontier point{R}{CRLF}"
        f"          Proposer insight: {DG}\"Traces show confusion on compound tickets\"{R}{CRLF}"
        f"          Applied: two-stage verification prompt{CRLF}"
        f"{CRLF}"
        f"  Iter 5: acc={BG}0.81{R}  {BG}↑ new frontier point{R}{CRLF}"
        f"          Proposer insight: {DG}\"Ambiguous tickets need contrastive examples\"{R}{CRLF}"
        f"          Applied: 5 contrastive examples + explicit uncertainty flag{CRLF}"
        f"{CRLF}"
        f"  Iter 8: acc={BG}0.87{R}  {BG}↑ best so far{R}{CRLF}"
        f"          Proposer insight: {DG}\"Domain keyword pre-filter reduces noise{R}{DG}\"{R}{CRLF}"
        f"          Applied: keyword routing → specialized sub-prompt per category{CRLF}"
        f"{CRLF}"
        f"  Iter 10: search complete.{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos mh frontier 01JQMHS...")
    r += out(
        f"{CRLF}"
        f"  {B}Pareto Frontier — 3 optimal harnesses:{R}{CRLF}"
        f"  {'─'*54}{CRLF}"
        f"  {BL}★{R} {BG}Best accuracy{R}:  acc={BG}0.8700{R}  cost=0.63  iter=8{CRLF}"
        f"     strategy: keyword-routing + specialized sub-prompts{CRLF}"
        f"  {BL}★{R} {G}Best cost{R}:     acc=0.8100  cost={BG}0.31{R}  iter=5{CRLF}"
        f"     strategy: contrastive examples + confidence gate{CRLF}"
        f"  {BL}★{R} {Y}Balanced{R}:      acc=0.8400  cost=0.44  iter=7{CRLF}"
        f"     strategy: CoT + 3 domain examples{CRLF}"
        f"{CRLF}"
        f"  {DG}Improvement: 45% → 87% (+42 points, 10 iterations){R}{CRLF}"
        f"  {DG}Search archived to knowledge base for next run.{R}{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1800, "content": ""}]
    return build("KAOS — Meta-Harness: 45%→87% Accuracy", r)


# ─────────────────────────────────────────────────────────────────────────────
# UC 05 — Parallel Refactor: Tests + Impl + Docs simultaneously
# ─────────────────────────────────────────────────────────────────────────────
def uc05_parallel_refactor():
    r = []
    r += section("KAOS Use Case 05 — Parallel Refactor: 3 agents, 1 PR")

    r += prompt()
    r += type_cmd("kaos parallel \\")
    r += [{"delay": 60, "content": ""}]
    r += type_cmd("  -t tests    \"Write pytest unit tests for the payments module\" \\")
    r += [{"delay": 60, "content": ""}]
    r += type_cmd("  -t refactor \"Refactor payments.py to use Stripe SDK v3. Keep the same public API.\" \\")
    r += [{"delay": 60, "content": ""}]
    r += type_cmd("  -t docs     \"Update API docs: new Stripe v3 endpoints and response shapes\"")
    r += out(
        f"{CRLF}"
        f"{BL}GEPA routing:{R}{CRLF}"
        f"  tests    → {MG}local_strong{R}  (code generation, complex){CRLF}"
        f"  refactor → {MG}local_strong{R}  (refactoring, complex){CRLF}"
        f"  docs     → {CY}local_fast{R}   (documentation, standard){CRLF}"
        f"{CRLF}"
    )
    r += [{"delay": 500, "content": ""}]
    r += out(
        f"  {DG}[░░░░░░░░░░]{R} tests    {Y}running{R}  reading payments.py ...{CRLF}"
        f"  {DG}[░░░░░░░░░░]{R} refactor {Y}running{R}  reading payments.py ...{CRLF}"
        f"  {DG}[░░░░░░░░░░]{R} docs     {Y}running{R}  reading payments.py ...{CRLF}"
    )
    r += [{"delay": 1000, "content": ""}]
    r += out(
        f"\r  {DG}[████░░░░░░]{R} tests    {Y}running{R}  writing test_payments.py{CRLF}"
        f"  {DG}[██████░░░░]{R} refactor {Y}running{R}  rewriting charge() method{CRLF}"
        f"  {DG}[██████████]{R} docs     {BG}done ✓{R}   wrote /docs/payments_api.md{CRLF}"
    )
    r += [{"delay": 1200, "content": ""}]
    r += out(
        f"\r  {DG}[██████████]{R} tests    {BG}done ✓{R}   wrote /tests/test_payments.py (22 tests){CRLF}"
        f"  {DG}[██████████]{R} refactor {BG}done ✓{R}   wrote /src/payments.py{CRLF}"
        f"{CRLF}"
        f"  {BG}All 3 completed in 1m 12s{R}  (vs ~3m 36s sequential){CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos read $(kaos --json ls | python -c \"import sys,json;d=json.load(sys.stdin);print([a['agent_id'] for a in d if a['name']=='tests'][0])\") /tests/test_payments.py | head -25")
    r += out(
        f"{CRLF}"
        f"{DG}import pytest{R}{CRLF}"
        f"{DG}from payments import PaymentsClient{R}{CRLF}"
        f"{CRLF}"
        f"{MG}class{R} {BG}TestChargeCard{R}:{CRLF}"
        f"    {MG}def{R} {BG}test_successful_charge{R}(self, mock_stripe):{CRLF}"
        f"        client = PaymentsClient(){CRLF}"
        f"        result = client.charge({G}\"tok_visa\"{R}, amount={Y}2000{R}){CRLF}"
        f"        {MG}assert{R} result.status == {G}\"succeeded\"{R}{CRLF}"
        f"        {MG}assert{R} result.amount == {Y}2000{R}{CRLF}"
        f"{CRLF}"
        f"    {MG}def{R} {BG}test_declined_card{R}(self, mock_stripe):{CRLF}"
        f"        mock_stripe.raises = stripe.CardError({G}\"declined\"{R}){CRLF}"
        f"        {MG}with{R} pytest.raises(PaymentDeclined):{CRLF}"
        f"            client.charge({G}\"tok_fail\"{R}, amount={Y}100{R}){CRLF}"
    )

    r += prompt()
    r += [{"delay": 1800, "content": ""}]
    return build("KAOS — Parallel Refactor: 3 Agents, 1 PR", r)


# ─────────────────────────────────────────────────────────────────────────────
# UC 06 — Fraud Detection Meta-Harness
# ─────────────────────────────────────────────────────────────────────────────
def uc06_fraud_detection():
    r = []
    r += section("KAOS Use Case 06 — Meta-Harness: Fraud Detection F1 +20pts")

    r += prompt()
    r += type_cmd("# Fraud classifier: 65% recall, 30% false positives. Let KAOS find better.")
    r += out(f"{CRLF}")

    r += prompt()
    r += type_cmd("kaos mh search --benchmark fraud_detection --iterations 8")
    r += out(
        f"{CRLF}"
        f"Seed evaluation:{CRLF}"
        f"  seed_1 (binary_classify):    f1={Y}0.58{R}  recall={Y}0.65{R}  fpr=0.30{CRLF}"
        f"  seed_2 (red_flag_list):      f1={Y}0.61{R}  recall={Y}0.70{R}  fpr=0.27{CRLF}"
        f"  {DG}Initial frontier established.{R}{CRLF}"
    )
    r += [{"delay": 700, "content": ""}]
    r += out(
        f"{CRLF}"
        f"Iter 2: Proposer reads traces — {DG}\"high FPR on small merchants\"{R}{CRLF}"
        f"  → tests: merchant_size segmentation + threshold tuning{CRLF}"
        f"  f1={BG}0.67{R}  {BG}↑ frontier{R}{CRLF}"
        f"{CRLF}"
        f"Iter 4: Proposer reads traces — {DG}\"misses velocity pattern across accounts\"{R}{CRLF}"
        f"  → adds: contrastive fraud/legit examples + velocity check prompt{CRLF}"
        f"  f1={BG}0.71{R}  {BG}↑ frontier{R}{CRLF}"
        f"{CRLF}"
        f"Iter 6: Pivot prompt fired — {Y}3 stagnant iterations{R}{CRLF}"
        f"  → structural change: two-stage (flag candidates → confirm){CRLF}"
        f"  f1={BG}0.78{R}  {BG}↑ best{R}{CRLF}"
        f"{CRLF}"
        f"Iter 8: skills applied from knowledge base{CRLF}"
        f"  → adds: transaction graph context summary{CRLF}"
        f"  f1={BG}0.81{R}  {BG}↑ best  recall={BG}0.84{R}  fpr={BG}0.14{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos mh frontier $(kaos --json mh list | python -c \"import sys,json;print(json.load(sys.stdin)[0]['search_agent_id'])\")")
    r += out(
        f"{CRLF}"
        f"  {B}Pareto Frontier:{R}{CRLF}"
        f"  {BL}★{R} {BG}Best F1{R}:      f1={BG}0.81{R}  recall=0.84  fpr=0.14  iter=8{CRLF}"
        f"     strategy: two-stage + velocity + graph context{CRLF}"
        f"  {BL}★{R} {G}Best recall{R}:  f1=0.76  recall={BG}0.91{R}  fpr=0.22  iter=7{CRLF}"
        f"     strategy: aggressive flagging + human review threshold{CRLF}"
        f"{CRLF}"
        f"  {DG}F1 improvement: 0.58 → 0.81 (+23 points){R}{CRLF}"
        f"  {DG}FPR reduction:  30%  → 14%  (saved ~80k false alerts/month){R}{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1800, "content": ""}]
    return build("KAOS — Fraud Detection Meta-Harness", r)


# ─────────────────────────────────────────────────────────────────────────────
# UC 07 — Autonomous Research Lab
# ─────────────────────────────────────────────────────────────────────────────
def uc07_autonomous_research():
    r = []
    r += section("KAOS Use Case 07 — Autonomous Research Lab")

    r += prompt()
    r += type_cmd("# 4 agents explore different ML hypotheses in parallel.")
    r += out(f"{CRLF}")

    r += prompt()
    r += type_cmd("python examples/autonomous_research_lab.py")
    r += out(
        f"{CRLF}"
        f"Spawning 4 research agents...{CRLF}"
        f"  Each gets its own copy of train.py + checkpoint baseline{CRLF}"
        f"{CRLF}"
        f"  {CY}architecture-explorer{R}  → exploring: ResNet variants, attention{CRLF}"
        f"  {CY}optimizer-explorer{R}     → exploring: AdamW, LAMB, Lion{CRLF}"
        f"  {CY}scaling-explorer{R}       → exploring: width/depth tradeoffs{CRLF}"
        f"  {CY}regularization-explorer{R} → exploring: dropout, weight decay, mixup{CRLF}"
        f"{CRLF}"
        f"Running in parallel... (each agent: modify → train 5 epochs → evaluate){CRLF}"
    )
    r += [{"delay": 1400, "content": ""}]
    r += out(
        f"  {BG}architecture-explorer{R}:   val_acc=0.847  {BG}↑ best{R}{CRLF}"
        f"  {Y}optimizer-explorer{R}:      val_acc=0.831{CRLF}"
        f"  {BG}scaling-explorer{R}:        val_acc=0.852  {BG}↑ new best{R}{CRLF}"
        f"  {Y}regularization-explorer{R}: val_acc=0.829{CRLF}"
        f"{CRLF}"
        f"  {BG}All 4 agents completed.{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos query \"SELECT a.name, json_extract(s.value,'$.val_acc') acc, json_extract(s.value,'$.experiments') exps FROM agents a JOIN state s ON a.agent_id=s.agent_id WHERE s.key='best_result' ORDER BY CAST(json_extract(s.value,'$.val_acc') AS REAL) DESC\"")
    r += out(
        f"{CRLF}"
        f"  {B}name                     acc    exps{R}{CRLF}"
        f"  {'─'*25}  {'─'*5}  {'─'*4}{CRLF}"
        f"  scaling-explorer          0.852  14{CRLF}"
        f"  architecture-explorer     0.847  11{CRLF}"
        f"  optimizer-explorer        0.831   9{CRLF}"
        f"  regularization-explorer   0.829   8{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos read scaling-explorer /findings.md | head -15")
    r += out(
        f"{CRLF}"
        f"{B}# Scaling Explorer — Best Findings{R}{CRLF}"
        f"{CRLF}"
        f"**Winner: width=512, depth=8, expansion=4** (val_acc=0.852){CRLF}"
        f"{CRLF}"
        f"Key insight: depth beyond 10 layers doesn't help with this dataset{CRLF}"
        f"size (12K samples). Width matters more — 512 hidden beats 256 by +3pts.{CRLF}"
        f"{CRLF}"
        f"Tried 14 configurations. Best emerged at iteration 9.{CRLF}"
        f"Checkpoint baseline: 0.791 | Final: 0.852 | Δ +0.061{CRLF}"
    )

    r += prompt()
    r += [{"delay": 1800, "content": ""}]
    return build("KAOS — Autonomous Research Lab", r)


# ─────────────────────────────────────────────────────────────────────────────
# UC 08 — CORAL Co-Evolution End-to-End
# ─────────────────────────────────────────────────────────────────────────────
def uc08_coevolution():
    r = []
    r += section("KAOS Use Case 08 — CORAL Co-Evolution: 3 Agents, Shared Skills")

    r += prompt()
    r += type_cmd("# 3 agents co-evolve on text_classify, sharing skills via a hub.")
    r += out(f"{CRLF}")

    r += prompt()
    r += type_cmd("# From Claude Code via MCP: mh_spawn_coevolution('text_classify', n_agents=3)")
    r += out(
        f"{CRLF}"
        f"{BG}✓{R} Co-evolution started{CRLF}"
        f"  Hub:    {CY}01JQHUB...{R}{CRLF}"
        f"  Agent A {DG}01JQAG1...{R}  strategy: chain-of-thought{CRLF}"
        f"  Agent B {DG}01JQAG2...{R}  strategy: few-shot examples{CRLF}"
        f"  Agent C {DG}01JQAG3...{R}  strategy: structured output parsing{CRLF}"
        f"  Hub sync every: 2 iterations{CRLF}"
    )
    r += [{"delay": 700, "content": ""}]

    r += out(f"{CRLF}--- Iterations 1-2 ---{CRLF}")
    r += out(
        f"  A: acc=0.72  {DG}chain-of-thought helps +7pts vs seed{R}{CRLF}"
        f"  B: acc=0.69  {DG}few-shot stable{R}{CRLF}"
        f"  C: acc=0.74  {DG}structured output best so far{R}{CRLF}"
        f"  {BG}→ Hub sync: A writes skill 'chain_of_thought_cls'{R}{CRLF}"
    )

    r += out(f"{CRLF}--- Iterations 3-4 ---{CRLF}")
    r += out(
        f"  A: acc={BG}0.81{R}  {BG}↑ applies B's few-shot skill from hub{R}{CRLF}"
        f"  B: acc={BG}0.79{R}  {BG}↑ applies A's CoT skill from hub{R}{CRLF}"
        f"  C: acc=0.77  still exploring{CRLF}"
        f"  {BG}→ Hub sync: 4 skills total, all agents updated{R}{CRLF}"
    )

    r += out(f"{CRLF}--- Iterations 7-8 ---{CRLF}")
    r += out(
        f"  A: acc={BG}0.87{R}  {BG}↑ best across all agents{R}{CRLF}"
        f"  B: acc=0.84{CRLF}"
        f"  C: acc={BG}0.85{R}  pivot fired iter 6 → structural change{CRLF}"
        f"  {BG}→ Co-evolution complete.{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos mh knowledge")
    r += out(
        f"{CRLF}"
        f"  {B}Knowledge Base — text_classify{R}{CRLF}"
        f"  {'─'*42}{CRLF}"
        f"  Best acc:   {BG}0.87{R}  (Agent A, iter 8){CRLF}"
        f"  Frontier:   4 Pareto-optimal harnesses{CRLF}"
        f"{CRLF}"
        f"  {B}Shared Skills (4){R}:{CRLF}"
        f"  {BG}chain_of_thought_cls{R}          contributed: Agent A iter 2{CRLF}"
        f"  {BG}few_shot_domain_examples{R}      contributed: Agent B iter 1{CRLF}"
        f"  {BG}structured_output_parsing{R}     contributed: Agent C iter 1{CRLF}"
        f"  {BG}confidence_threshold_gate{R}     contributed: Agent A iter 5{CRLF}"
        f"{CRLF}"
        f"  {DG}Skills will seed the next search automatically.{R}{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1800, "content": ""}]
    return build("KAOS — CORAL Co-Evolution", r)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

USECASES = [
    ("uc01_code_review_swarm",      uc01_code_review_swarm),
    ("uc02_self_healing_agent",     uc02_self_healing),
    ("uc03_post_mortem_debug",      uc03_post_mortem),
    ("uc04_meta_harness_classifier",uc04_meta_harness_classifier),
    ("uc05_parallel_refactor",      uc05_parallel_refactor),
    ("uc06_fraud_detection",        uc06_fraud_detection),
    ("uc07_autonomous_research",    uc07_autonomous_research),
    ("uc08_coevolution_coral",      uc08_coevolution),
]

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    for slug, fn in USECASES:
        data = fn()
        path = os.path.join(OUT_DIR, f"kaos_{slug}.yml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, width=200)
        print(f"OK  {path}")
    print(f"\nDone. {len(USECASES)} use-case recordings written.")
    print("Render with:  python render_gif.py kaos_uc*.yml")
