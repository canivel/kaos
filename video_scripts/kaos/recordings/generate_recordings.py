"""
Generate terminalizer YAML recording files for all 8 KAOS tutorials.
Each file simulates the key commands from that tutorial with realistic
ANSI-colored output. Run this script then `terminalizer render` each file.

Usage:
    python generate_recordings.py
    # Then render each:
    for f in *.yml; do terminalizer render "$f" -o "${f%.yml}.gif"; done
"""
import random
import yaml
import os

# ── ANSI helpers ──────────────────────────────────────────────────────────────

R  = "\u001b[0m"      # reset
B  = "\u001b[1m"      # bold
G  = "\u001b[32m"     # green
Y  = "\u001b[33m"     # yellow
BL = "\u001b[34m"     # blue
MG = "\u001b[35m"     # magenta
CY = "\u001b[36m"     # cyan
WH = "\u001b[37m"     # white
DG = "\u001b[90m"     # dark grey
BG = "\u001b[92m"     # bright green
BY = "\u001b[93m"     # bright yellow
BC = "\u001b[96m"     # bright cyan
BB = "\u001b[94m"     # bright blue

PROMPT = f"{G}❯{R} "
CRLF   = "\r\n"

# ── Frame builders ────────────────────────────────────────────────────────────

def pause(ms: int = 500) -> dict:
    return {"delay": ms, "content": ""}

def prompt() -> list[dict]:
    return [{"delay": 400, "content": CRLF + PROMPT}]

def type_cmd(cmd: str, wpm: int = 220) -> list[dict]:
    """Simulate typing a command character by character."""
    frames = []
    for ch in cmd:
        delay = int(60000 / (wpm * 5)) + random.randint(-10, 20)
        frames.append({"delay": max(30, delay), "content": ch})
    frames.append({"delay": 180, "content": CRLF})
    return frames

def output(text: str, delay: int = 60) -> list[dict]:
    """Show output text as a single frame."""
    return [{"delay": delay, "content": text}]

def blank_line() -> list[dict]:
    return [{"delay": 80, "content": CRLF}]

# ── Shared config ─────────────────────────────────────────────────────────────

def make_config(title: str) -> dict:
    return {
        "command": "bash",
        "cwd":     None,
        "env":     {"recording": True},
        "cols":    110,
        "rows":    32,
        "repeat":  0,
        "quality": 100,
        "frameDelay":  "auto",
        "maxIdleTime": 1800,
        "frameBox": {
            "type":  "window",
            "title": title,
            "style": {"border": "0px black solid"},
        },
        "watermark": {"imagePath": None, "style": {
            "position": "absolute", "right": "15px", "bottom": "15px",
            "width": "100px", "opacity": "0.9",
        }},
        "cursorStyle":   "bar",
        "fontFamily":    "\"JetBrains Mono, Fira Code, Monaco, Monospace\"",
        "fontSize":      13,
        "lineHeight":    1.2,
        "letterSpacing": 0,
        "theme": {
            "background":    "#0d1117",
            "foreground":    "#c9d1d9",
            "cursor":        "#58a6ff",
            "black":         "#161b22",
            "red":           "#ff7b72",
            "green":         "#3fb950",
            "yellow":        "#e3b341",
            "blue":          "#58a6ff",
            "magenta":       "#bc8cff",
            "cyan":          "#39c5cf",
            "white":         "#b1bac4",
            "brightBlack":   "#6e7681",
            "brightRed":     "#ffa198",
            "brightGreen":   "#56d364",
            "brightYellow":  "#e3b341",
            "brightBlue":    "#79c0ff",
            "brightMagenta": "#d2a8ff",
            "brightCyan":    "#56d4dd",
            "brightWhite":   "#f0f6fc",
        },
    }

def build(title: str, records: list[dict]) -> dict:
    return {"config": make_config(title), "records": records}

# ── Tutorial recordings ───────────────────────────────────────────────────────

def tutorial_01():
    """Getting Started: install, spawn, isolate."""
    r = []
    r += prompt()
    r += type_cmd("kaos init")
    r += output(
        f"{CRLF}{BG}✓{R} Database initialized: {CY}kaos.db{R}{CRLF}"
        f"{DG}  Schema created, blob store ready, event journal started.{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos ls")
    r += output(
        f"{CRLF}{DG}No agents yet. Use 'kaos run' or the Python API to spawn agents.{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("python demo.py")
    r += output(
        f"{CRLF}{DG}# Spawning two agents writing to the same path...{R}{CRLF}"
        f"{CRLF}researcher  → {CY}/findings.md{R}  \"{B}# Bug Report\\nSQL injection in auth.py{R}\"{CRLF}"
        f"doc-writer  → {CY}/findings.md{R}  \"{B}# Docs Draft\\nAPI v2 overview{R}\"{CRLF}"
        f"{CRLF}{DG}# Reading back — fully isolated:{R}{CRLF}"
        f"researcher  /findings.md → {G}# Bug Report\\nSQL injection in auth.py{R}{CRLF}"
        f"doc-writer  /findings.md → {G}# Docs Draft\\nAPI v2 overview{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos ls")
    r += output(
        f"{CRLF}"
        f"  {B}{BL}Agent ID{R}               {B}Name{R}          {B}Status{R}    {B}Files{R}  {B}Created{R}{CRLF}"
        f"  {'─'*22}  {'─'*12}  {'─'*8}  {'─'*5}  {'─'*16}{CRLF}"
        f"  {DG}01JQXYZ1234567890AB{R}  researcher    {BG}running{R}    2      just now{CRLF}"
        f"  {DG}01JQABC9876543210CD{R}  doc-writer    {BG}running{R}    1      just now{CRLF}"
        f"{CRLF}"
        f"  {DG}2 agents total{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos read 01JQXYZ1234567890AB /findings.md")
    r += output(
        f"{CRLF}"
        f"{G}# Bug Report{R}{CRLF}"
        f"SQL injection in auth.py{CRLF}"
    )

    r += prompt()
    r += [{"delay": 1500, "content": ""}]
    return build("KAOS 01 — Getting Started", r)


def tutorial_02():
    """Checkpoints & Restore."""
    r = []
    r += prompt()
    r += type_cmd("kaos checkpoint 01JQREF... --label before-migration")
    r += output(
        f"{CRLF}{BG}✓{R} Checkpoint created{CRLF}"
        f"  ID:    {CY}01JQCP1111111111AA{R}{CRLF}"
        f"  Label: {Y}before-migration{R}{CRLF}"
        f"  Files: 4  |  State keys: 2{CRLF}"
    )

    r += prompt()
    r += type_cmd("# Agent runs and modifies files...")
    r += output(f"{CRLF}")

    r += prompt()
    r += type_cmd("kaos diff 01JQREF... --from 01JQCP111... --to 01JQCP222...")
    r += output(
        f"{CRLF}"
        f"  {B}Files changed:{R}{CRLF}"
        f"  {Y}MODIFIED{R}  /src/auth.py{CRLF}"
        f"            {DG}before:{R} def login(user, pw): ...{CRLF}"
        f"            {DG}after: {R} {Y}def login(): broken_migration(){R}{CRLF}"
        f"  {G}ADDED   {R}  /src/database.py{CRLF}{CRLF}"
        f"  {B}State changed:{R}{CRLF}"
        f"  progress: {DG}40{R} → {Y}90{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos restore 01JQREF... --checkpoint 01JQCP111...")
    r += output(
        f"{CRLF}{BG}✓{R} Restored to checkpoint {CY}01JQCP1111111111AA{R} ({Y}before-migration{R}){CRLF}"
        f"  Files restored: 4{CRLF}"
        f"  State restored: progress=40{CRLF}"
        f"  Other agents: {G}unaffected{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos read 01JQREF... /src/auth.py")
    r += output(
        f"{CRLF}"
        f"{G}def login(user, pw):{R}{CRLF}"
        f"    ...{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1500, "content": ""}]
    return build("KAOS 02 — Checkpoints & Restore", r)


def tutorial_03():
    """Parallel Agents + GEPA."""
    r = []
    r += prompt()
    r += type_cmd("kaos parallel \\")
    r += output(f"{CRLF}")
    r += type_cmd("  -t tests    \"Write unit tests for the payments module\" \\")
    r += output(f"{CRLF}")
    r += type_cmd("  -t refactor \"Refactor payments to use Stripe SDK v3\" \\")
    r += output(f"{CRLF}")
    r += type_cmd("  -t docs     \"Update payment API documentation\"")
    r += output(
        f"{CRLF}"
        f"{BL}GEPA Router{R} — classifying tasks:{CRLF}"
        f"  tests    → {MG}local_strong{R}  (complex: code generation){CRLF}"
        f"  refactor → {MG}local_strong{R}  (complex: refactoring){CRLF}"
        f"  docs     → {CY}local_fast{R}   (standard: documentation){CRLF}"
        f"{CRLF}"
        f"Launching 3 agents in parallel...{CRLF}"
        f"{CRLF}"
        f"  {DG}[████░░░░░░]{R} tests     {Y}running{R}   iter 3/8{CRLF}"
        f"  {DG}[██████░░░░]{R} refactor  {Y}running{R}   iter 5/8{CRLF}"
        f"  {DG}[██████████]{R} docs      {BG}done{R}      8/8 ✓{CRLF}"
    )
    r += [{"delay": 1400, "content": ""}]
    r += output(
        f"\r  {DG}[██████████]{R} tests     {BG}done{R}      8/8 ✓{CRLF}"
        f"  {DG}[██████████]{R} refactor  {BG}done{R}      8/8 ✓{CRLF}"
        f"{CRLF}"
        f"  {BG}✓ All 3 agents completed{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos query \"SELECT name, tool_calls, tokens FROM v_agent_stats WHERE name IN ('tests','refactor','docs')\"")
    r += output(
        f"{CRLF}"
        f"  {B}name       {R}  {B}tool_calls{R}  {B}tokens{R}{CRLF}"
        f"  {'─'*10}  {'─'*10}  {'─'*7}{CRLF}"
        f"  tests        23           4820{CRLF}"
        f"  refactor     31           6104{CRLF}"
        f"  docs         12           1937{CRLF}"
        f"{CRLF}"
        f"  {DG}Total: 66 tool calls, 12861 tokens{R}{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1500, "content": ""}]
    return build("KAOS 03 — Parallel Agents + GEPA Router", r)


def tutorial_04():
    """MCP Server + Claude integration."""
    r = []
    r += prompt()
    r += type_cmd("kaos setup")
    r += output(
        f"{CRLF}"
        f"  {B}KAOS Setup Wizard{R}{CRLF}"
        f"  {'─'*40}{CRLF}"
        f"  {DG}Select a preset:{R}{CRLF}"
        f"  {BG}›{R} 1. Claude Code (recommended){CRLF}"
        f"    2. Local vLLM (Qwen 7B+70B){CRLF}"
        f"    3. Hybrid (local + Claude fallback){CRLF}"
        f"    4. OpenAI GPT-4o{CRLF}"
        f"{CRLF}"
        f"  {Y}1{R}{CRLF}"
        f"{CRLF}"
        f"  {BG}✓{R} Config written:     {CY}kaos.yaml{R}{CRLF}"
        f"  {BG}✓{R} Database created:   {CY}kaos.db{R}{CRLF}"
        f"  {BG}✓{R} MCP server wired:   {CY}~/.claude/settings.json{R}{CRLF}"
        f"{CRLF}"
        f"  {BG}Restart Claude Code — 18 KAOS tools are now available.{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos serve --transport stdio")
    r += output(
        f"{CRLF}"
        f"{BG}✓{R} KAOS MCP server started{CRLF}"
        f"  Transport: {CY}stdio{R}{CRLF}"
        f"  Tools:     {B}18{R} tools registered{CRLF}"
        f"  Database:  {CY}kaos.db{R}{CRLF}"
        f"{CRLF}"
        f"  {DG}agent_spawn    agent_status   agent_read     agent_write{R}{CRLF}"
        f"  {DG}agent_ls       agent_kill     agent_query    agent_parallel{R}{CRLF}"
        f"  {DG}agent_checkpoint  agent_restore  agent_diff  agent_pause{R}{CRLF}"
        f"  {DG}mh_start_search   mh_next_iter   mh_submit   mh_frontier{R}{CRLF}"
        f"{CRLF}"
        f"  {DG}Waiting for MCP client connection...{R}{CRLF}"
    )
    r += [{"delay": 1500, "content": ""}]
    r += output(f"  {BL}→{R} Claude Code connected{CRLF}")
    r += prompt()
    r += [{"delay": 1500, "content": ""}]
    return build("KAOS 04 — MCP Server + Claude Code", r)


def tutorial_05():
    """Audit trail & SQL queries."""
    r = []
    r += prompt()
    r += type_cmd("kaos logs 01JQREF... --tail 10")
    r += output(
        f"{CRLF}"
        f"  {DG}[10:42:01]{R} {CY}file_write{R}   /src/auth.py           {DG}1240 bytes{R}{CRLF}"
        f"  {DG}[10:42:04]{R} {BL}tool_call {R}   bash: pytest tests/     {BG}exit 0{R}{CRLF}"
        f"  {DG}[10:42:11]{R} {CY}file_write{R}   /tests/test_auth.py     {DG}890 bytes{R}{CRLF}"
        f"  {DG}[10:42:12]{R} {MG}state_set {R}   progress=75{CRLF}"
        f"  {DG}[10:42:15]{R} {Y}checkpoint{R}   pre-migration{CRLF}"
        f"  {DG}[10:42:20]{R} {CY}file_write{R}   /src/database.py        {DG}42 bytes{R}  {Y}← ⚠{R}{CRLF}"
        f"  {DG}[10:42:21]{R} {BL}tool_call {R}   bash: python migrate.py {Y}exit 1{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos query \"SELECT name, SUM(token_count) tokens FROM agents JOIN tool_calls USING(agent_id) GROUP BY name\"")
    r += output(
        f"{CRLF}"
        f"  {B}name          {R}  {B}tokens{R}{CRLF}"
        f"  {'─'*14}  {'─'*7}{CRLF}"
        f"  researcher      4820{CRLF}"
        f"  refactor-agent  6301{CRLF}"
        f"  doc-writer      1937{CRLF}"
        f"{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos search \"broken_migration\"")
    r += output(
        f"{CRLF}"
        f"  {BG}2{R} matches across {BG}2{R} agents:{CRLF}"
        f"{CRLF}"
        f"  {CY}01JQREF.../src/database.py{R}:{Y}1{R}   DROP TABLE users;{CRLF}"
        f"  {CY}01JQREF.../src/auth.py{R}:{Y}3{R}      {Y}broken_migration(){R}{CRLF}"
    )

    r += prompt()
    r += [{"delay": 1500, "content": ""}]
    return build("KAOS 05 — Audit Trail & SQL Queries", r)


def tutorial_06():
    """Meta-Harness Search."""
    r = []
    r += prompt()
    r += type_cmd("kaos mh search --benchmark text_classify --iterations 10 --background")
    r += output(
        f"{CRLF}"
        f"{BG}✓{R} Meta-Harness search started{CRLF}"
        f"  Search agent: {CY}01JQMHS1234567890XY{R}{CRLF}"
        f"  Benchmark:    {B}text_classify{R}{CRLF}"
        f"  Iterations:   10{CRLF}"
        f"  Candidates/iter: 2{CRLF}"
        f"  Running in background — use 'kaos mh status' to monitor.{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos mh status 01JQMHS...")
    r += output(
        f"{CRLF}"
        f"  {B}Meta-Harness Search{R}  {CY}01JQMHS...{R}{CRLF}"
        f"  {'─'*44}{CRLF}"
        f"  Benchmark:    {B}text_classify{R}{CRLF}"
        f"  Iteration:    {BG}7{R} / 10{CRLF}"
        f"  Harnesses:    {B}14{R} evaluated{CRLF}"
        f"  Stagnant:     {BG}0{R} iterations{CRLF}"
        f"{CRLF}"
        f"  {B}Pareto Frontier{R} ({BG}3{R} points):{CRLF}"
        f"  {BL}★{R} accuracy={BG}0.89{R}  cost=0.41  iter=6   {CY}01JQBEST...{R}{CRLF}"
        f"  {BL}★{R} accuracy=0.84  cost={BG}0.12{R}  iter=5   {CY}01JQCHEAP..{R}{CRLF}"
        f"  {BL}★{R} accuracy=0.87  cost=0.22  iter=7   {CY}01JQBAL...{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos mh knowledge")
    r += output(
        f"{CRLF}"
        f"  {B}Knowledge Base{R}{CRLF}"
        f"  {'─'*44}{CRLF}"
        f"  {Y}text_classify{R}  3 frontier harnesses  best=0.89{CRLF}"
        f"  {Y}arc_agi3{R}       2 frontier harnesses  best=0.41{CRLF}"
        f"{CRLF}"
        f"  Skills:{CRLF}"
        f"  • {BG}chain_of_thought_classification{R}  +12 accuracy pts{CRLF}"
        f"  • {BG}confidence_threshold_fallback{R}     -8% cost{CRLF}"
        f"  • {BG}few_shot_domain_examples{R}          +7 accuracy pts{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1500, "content": ""}]
    return build("KAOS 06 — Meta-Harness Search", r)


def tutorial_07():
    """CORAL Co-Evolution."""
    r = []
    r += prompt()
    r += type_cmd("# Spawn 3 co-evolving agents via MCP from Claude...")
    r += output(f"{CRLF}")

    r += prompt()
    r += type_cmd("kaos mh status --all")
    r += output(
        f"{CRLF}"
        f"  {B}Co-Evolution Hub{R}  {CY}01JQHUB...{R}{CRLF}"
        f"  {'─'*50}{CRLF}"
        f"  {B}Agent A{R}  {DG}01JQAG1...{R}  iter {BG}8{R}/10  acc={BG}0.87{R}  {BG}↑ improved{R}{CRLF}"
        f"  {B}Agent B{R}  {DG}01JQAG2...{R}  iter {Y}8{R}/10  acc={Y}0.84{R}  {DG}  neutral{R}{CRLF}"
        f"  {B}Agent C{R}  {DG}01JQAG3...{R}  iter {BG}8{R}/10  acc={BG}0.89{R}  {BG}↑ improved{R}{CRLF}"
        f"{CRLF}"
        f"  {B}Shared Skills{R} ({BG}4{R} total from hub):{CRLF}"
        f"  • {BG}chain_of_thought_classification{R}  {DG}contributed by: Agent A iter 3{R}{CRLF}"
        f"  • {BG}few_shot_domain_examples{R}          {DG}contributed by: Agent C iter 5{R}{CRLF}"
        f"  • {BG}structured_output_parsing{R}         {DG}contributed by: Agent B iter 4{R}{CRLF}"
        f"  • {BG}confidence_threshold_fallback{R}     {DG}contributed by: Agent A iter 6{R}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos read 01JQAG1... /notes/iter_8.md")
    r += output(
        f"{CRLF}"
        f"{G}## Reflect (iteration 8){R}{CRLF}"
        f"{CRLF}"
        f"Chain-of-thought continues to help (+4pts over baseline).{CRLF}"
        f"Attempted ensemble voting — regression (-2pts), likely due to{CRLF}"
        f"inconsistent formatting between model calls. Will isolate the{CRLF}"
        f"voting aggregation logic next iteration.{CRLF}"
        f"{CRLF}"
        f"Next hypothesis: structured JSON output + confidence score{CRLF}"
        f"before final label decision.{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1500, "content": ""}]
    return build("KAOS 07 — CORAL Co-Evolution", r)


def tutorial_08():
    """Custom Benchmark."""
    r = []
    r += prompt()
    r += type_cmd("cat benchmarks/intent_classify.py | head -40")
    r += output(
        f"{CRLF}"
        f"{DG}# kaos/metaharness/benchmarks/intent_classify.py{R}{CRLF}"
        f"{CRLF}"
        f"{MG}class{R} {BG}IntentClassifyBenchmark{R}({BL}Benchmark{R}):{CRLF}"
        f"    {MG}name{R}       = {Y}\"intent_classify\"{R}{CRLF}"
        f"    {MG}objectives{R} = [{Y}\"+accuracy\"{R}, {Y}\"-context_cost\"{R}]{CRLF}"
        f"{CRLF}"
        f"    {MG}def{R} {BG}get_seed_harnesses{R}(self) -> list[str]:{CRLF}"
        f"        {MG}return{R} [SEED_HARNESS]{CRLF}"
        f"{CRLF}"
        f"    {MG}def{R} {BG}get_search_set{R}(self) -> list[dict]:{CRLF}"
        f"        {MG}return{R} PROBLEMS{CRLF}"
        f"{CRLF}"
        f"    {MG}def{R} {BG}score{R}(self, problem, output) -> dict:{CRLF}"
        f"        correct = output.get({Y}\"prediction\"{R}) == problem[{Y}\"label\"{R}]{CRLF}"
        f"        {MG}return{R} {{{CRLF}"
        f"            {Y}\"accuracy\"{R}:     {BG}1.0{R} {MG}if{R} correct {MG}else{R} {Y}0.0{R},{CRLF}"
        f"            {Y}\"context_cost\"{R}: output.get({Y}\"context_tokens\"{R}, 0) / 1000,{CRLF}"
        f"        }}{CRLF}"
    )

    r += prompt()
    r += type_cmd("kaos mh search --benchmark intent_classify --iterations 8")
    r += output(
        f"{CRLF}"
        f"{BG}✓{R} Search started  {CY}01JQCUSTOM...{R}{CRLF}"
        f"{CRLF}"
        f"  Iteration 1/8 ...{CRLF}"
        f"  {DG}Seed acc=0.61  cost=0.31{R}{CRLF}"
        f"  Iteration 2/8 ...{CRLF}"
        f"  {BG}↑{R} New frontier: acc={BG}0.72{R}  cost=0.28{CRLF}"
        f"  Iteration 3/8 ...{CRLF}"
        f"  {BG}↑{R} New frontier: acc={BG}0.79{R}  cost=0.25{CRLF}"
        f"  Iteration 4/8 ...{CRLF}"
        f"  {DG}  neutral{R}{CRLF}"
        f"  Iteration 5/8 ...{CRLF}"
        f"  {BG}↑{R} New frontier: acc={BG}0.85{R}  cost=0.19{CRLF}"
        f"  Iteration 6-8 ...{CRLF}"
        f"  {BG}↑{R} Final best: acc={BG}0.89{R}  cost=0.17{CRLF}"
        f"{CRLF}"
        f"  {BG}Search complete.{R} 3 Pareto-optimal harnesses found.{CRLF}"
        f"  {DG}Discoveries filed to knowledge base.{R}{CRLF}"
    )
    r += prompt()
    r += [{"delay": 1500, "content": ""}]
    return build("KAOS 08 — Custom Benchmark", r)


# ── Main ──────────────────────────────────────────────────────────────────────

TUTORIALS = [
    ("01_getting_started",   tutorial_01),
    ("02_checkpoints",       tutorial_02),
    ("03_parallel_agents",   tutorial_03),
    ("04_mcp_server",        tutorial_04),
    ("05_audit_trail",       tutorial_05),
    ("06_meta_harness",      tutorial_06),
    ("07_coral_coevolution", tutorial_07),
    ("08_custom_benchmark",  tutorial_08),
]

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

if __name__ == "__main__":
    for slug, fn in TUTORIALS:
        data = fn()
        path = os.path.join(OUT_DIR, f"kaos_{slug}.yml")
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(data, f, allow_unicode=True, default_flow_style=False, width=200)
        print(f"OK  {path}")
    print(f"\nDone. {len(TUTORIALS)} recording files written.")
    print("Render all with:")
    print("  for f in kaos_*.yml; do terminalizer render \"$f\" -o \"${f%.yml}.gif\"; done")
