"""
Generate a security audit swarm demo recording.

Story: A new PR arrives ("feat: add user search endpoint"). 4 security agents
review it in parallel from different angles: SQL injection, secrets/API keys,
authentication bypass, unsafe deserialization. All isolated VFS. After they
complete, SQL aggregation reveals findings — Agent 1 found a critical SQLi,
Agent 3 found a hardcoded API key.

Usage:
    cd video_scripts/kaos/recordings
    uv run python generate_uc_security.py
    uv run python render_gif.py kaos_uc_security.yml
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
    f += out(f"  {B}{CY}KAOS — Security Audit Swarm{R}")
    f += out(f"  {DG}4 parallel agents · isolated VFS · SQL aggregation · zero conflicts{R}")
    f += blank()
    f += out(f"  {DG}PR:{R}     {BY}PR-2847{R}  {DG}—{R}  {WH}feat: add user search endpoint{R}")
    f += out(f"  {DG}Author:{R} dev@company.com   {DG}opened 2026-04-10 09:30 UTC{R}")
    f += out(f"  {DG}Files:{R}  routes/users.py  config.py  middleware/auth.py  models/user.py")
    f += blank()
    f += out(f"  {DG}Audit plan:{R}")
    f += out(f"  {DG}  Agent 1 {R}{RD}sqli-agent{R}    {DG}— SQL injection vectors{R}")
    f += out(f"  {DG}  Agent 2 {R}{Y}ssrf-agent{R}     {DG}— secrets, SSRF, unvalidated URLs{R}")
    f += out(f"  {DG}  Agent 3 {R}{BR}auth-agent{R}     {DG}— hardcoded credentials, token hygiene{R}")
    f += out(f"  {DG}  Agent 4 {R}{BL}deser-agent{R}    {DG}— unsafe deserialization, schema gaps{R}")
    f += blank()
    f += out(f"  {DG}All agents get isolated VFS copies of the PR.  No shared state.{R}")
    f += blank()
    f += [pause(3200)]
    f += [pause(2000)]

    # ── Scene 2: Spawn 4 agents in parallel ──────────────────────────────────
    f += section("STEP 1 — Spawn 4 specialized security agents in parallel")
    f += blank()
    f += prompt_line()
    f += type_cmd('kaos parallel --run-id audit-pr-2847 "sqli-agent" "ssrf-agent" "auth-agent" "deser-agent"')
    f += blank()
    f += out(f"  {G}✓{R}  Parallel run  {DG}audit-pr-2847{R}  initialized")
    f += out(f"  {DG}  Snapshotting PR-2847 code into 4 isolated VFS namespaces...{R}")
    f += blank()
    f += out(f"  {G}✓{R}  {RD}sqli-agent{R}   spawned  {DG}[01JSEC-SQLI-a3f1]  VFS: 6 files, 18.4 KB{R}", 70)
    f += out(f"  {G}✓{R}  {Y}ssrf-agent{R}    spawned  {DG}[01JSEC-SSRF-b7c2]  VFS: 6 files, 18.4 KB{R}", 70)
    f += out(f"  {G}✓{R}  {BR}auth-agent{R}    spawned  {DG}[01JSEC-AUTH-c9d4]  VFS: 6 files, 18.4 KB{R}", 70)
    f += out(f"  {G}✓{R}  {BL}deser-agent{R}   spawned  {DG}[01JSEC-DESR-e2f6]  VFS: 6 files, 18.4 KB{R}", 70)
    f += blank()
    f += out(f"  {DG}4 agents running.  Isolation: logical VFS (separate key namespaces).{R}")
    f += out(f"  {DG}Each agent writes findings to its own /findings/ directory in VFS.{R}")
    f += blank()
    f += [pause(1600)]

    # ── Scene 3: Agents working in parallel ──────────────────────────────────
    f += section("STEP 2 — Agents working in parallel")
    f += blank()
    f += out(f"  {DG}[streaming interleaved output from all 4 agents]{R}")
    f += blank()
    f += out(f"  {RD}[sqli ]{R}  {DG}scanning routes/users.py ...{R}", 80)
    f += out(f"  {Y}[ssrf ]{R}  {DG}scanning config.py — checking string literals ...{R}", 80)
    f += out(f"  {BR}[auth ]{R}  {DG}scanning middleware/auth.py — checking token flow ...{R}", 80)
    f += out(f"  {BL}[deser]{R}  {DG}scanning models/user.py — checking input parsing ...{R}", 80)
    f += blank()
    f += [pause(500)]
    f += out(f"  {RD}[sqli ]{R}  {DG}analyzing query construction in search_users() ...{R}", 80)
    f += out(f"  {Y}[ssrf ]{R}  {DG}found requests.get() call — checking URL source ...{R}", 90)
    f += out(f"  {BR}[auth ]{R}  {DG}validating JWT middleware — checking secret storage ...{R}", 80)
    f += out(f"  {BL}[deser]{R}  {DG}inspecting pickle / yaml.load / json.loads usage ...{R}", 80)
    f += blank()
    f += [pause(500)]
    f += out(f"  {RD}[sqli ]{R}  {DG}checking parameterization on line 34 ...{R}", 80)
    f += out(f"  {Y}[ssrf ]{R}  {DG}URL source: user-controlled parameter — flagging ...{R}", 90)
    f += out(f"  {BR}[auth ]{R}  {DG}found string literal matching key pattern in config.py ...{R}", 80)
    f += out(f"  {BL}[deser]{R}  {DG}schema validation present — checking completeness ...{R}", 80)
    f += blank()
    f += [pause(600)]
    f += out(f"  {RD}[sqli ]{R}  {BR}raw f-string interpolated directly into SQL query — flagging{R}")
    f += out(f"  {BL}[deser]{R}  {G}pydantic schema covers all input fields — no gaps found{R}", 80)
    f += out(f"  {BR}[auth ]{R}  {BR}hardcoded API key confirmed: sk-prod-...  config.py:47{R}")
    f += out(f"  {Y}[ssrf ]{R}  {Y}unvalidated URL passed to requests.get() — SSRF risk{R}", 80)
    f += blank()
    f += [pause(500)]
    f += out(f"  {RD}[sqli ]{R}  {G}writing finding to /findings/sqli_001.md{R}", 70)
    f += out(f"  {Y}[ssrf ]{R}  {G}writing finding to /findings/ssrf_001.md{R}", 70)
    f += out(f"  {BR}[auth ]{R}  {G}writing finding to /findings/hardcoded_key_001.md{R}", 70)
    f += out(f"  {BL}[deser]{R}  {G}writing report to /findings/deser_clean.md{R}", 70)
    f += blank()
    f += out(f"  {G}✓{R}  All 4 agents complete  {DG}in ~43s{R}")
    f += blank()
    f += [pause(2200)]

    # ── Scene 4: Findings emerge ──────────────────────────────────────────────
    f += section("STEP 3 — Findings emerge")
    f += blank()
    f += separator(500)
    f += out(f"  {BR}[CRITICAL]{R}  {RD}sqli-agent{R}  {DG}—{R}  SQL injection in {BY}/users/search?q={R}")
    f += separator()
    f += blank()
    f += out(f"  {DG}Vulnerable code in routes/users.py:{R}")
    f += blank()
    f += out(f"  {DG}  32│{R}  {CY}def{R} {BG}search_users{R}(q: str):")
    f += out(f"  {DG}  33│{R}      {DG}# TODO: add auth later{R}")
    f += out(f"  {RD}  34│{R}      query = {BR}f\"SELECT * FROM users WHERE name LIKE '%{{q}}%'\"{R}")
    f += out(f"  {RD}  35│{R}      result = db.execute({BR}query{R})")
    f += out(f"  {DG}  36│{R}      {CY}return{R} jsonify(result.fetchall())")
    f += blank()
    f += out(f"  {BR}  Attack: GET /users/search?q=' OR 1=1 --{R}")
    f += out(f"  {BR}  Impact: full users table dump, no authentication required{R}")
    f += blank()
    f += [pause(1000)]
    f += separator(500)
    f += out(f"  {Y}[MEDIUM]   {Y}ssrf-agent{R}   {DG}—{R}  Unvalidated URL  {DG}(SSRF risk){R}")
    f += separator()
    f += blank()
    f += out(f"  {DG}  routes/users.py:71{R}")
    f += out(f"  {Y}  avatar_url = request.json.get('avatar_url'){R}")
    f += out(f"  {Y}  resp = requests.get(avatar_url)   {DG}# user-supplied, no allowlist{R}")
    f += out(f"  {DG}  Impact: attacker can probe internal services via the server{R}")
    f += blank()
    f += [pause(900)]
    f += separator(500)
    f += out(f"  {BR}[CRITICAL]{R}  {BR}auth-agent{R}  {DG}—{R}  Hardcoded API key in config.py")
    f += separator()
    f += blank()
    f += out(f"  {DG}  config.py:47{R}")
    f += out(f"  {BR}  ANALYTICS_KEY = \"sk-prod-a8f3d2c1b9e4f7a0d6c3b2e1f4a7d9c0\"{R}")
    f += out(f"  {DG}  Key is valid and active — production analytics service{R}")
    f += out(f"  {DG}  Exposed via PR diff — rotate immediately{R}")
    f += blank()
    f += [pause(1600)]
    f += separator(500)
    f += out(f"  {G}[CLEAN]    {BL}deser-agent{R}  {DG}—{R}  No unsafe deserialization found")
    f += separator()
    f += blank()
    f += out(f"  {DG}  Pydantic schemas cover all input fields.  json.loads used throughout.{R}")
    f += out(f"  {DG}  No pickle, no yaml.load, no eval.  Input handling is safe.{R}")
    f += blank()
    f += [pause(1600)]

    # ── Scene 5: SQL aggregation ──────────────────────────────────────────────
    f += section("STEP 4 — Aggregate via SQL")
    f += blank()
    f += prompt_line()
    f += type_cmd('kaos --json query "SELECT agent_name, severity, finding FROM vfs_findings WHERE pr=\'PR-2847\' ORDER BY severity"')
    f += blank()
    f += out(f"  {B}agent_name{R}    {B}severity{R}   {B}finding{R}")
    f += out(f"  {DG}────────────  ─────────  ─────────────────────────────────────────────────{R}")
    f += out(f"  {RD}sqli-agent{R}    {BR}CRITICAL{R}   SQL injection: raw f-string in SELECT query  {DG}(routes/users.py:34){R}", 60)
    f += out(f"  {BR}auth-agent{R}    {BR}CRITICAL{R}   Hardcoded API key in config.py:47  {DG}(sk-prod-...){R}", 60)
    f += out(f"  {Y}ssrf-agent{R}    {Y}MEDIUM{R}     Unvalidated URL passed to requests.get()  {DG}(routes/users.py:71){R}", 60)
    f += out(f"  {BL}deser-agent{R}   {G}CLEAN{R}      No unsafe deserialization found", 60)
    f += blank()
    f += out(f"  {DG}4 rows  │  2 CRITICAL  │  1 MEDIUM  │  1 CLEAN{R}")
    f += blank()
    f += [pause(2000)]

    # ── Scene 6: Deep dive on SQLi ────────────────────────────────────────────
    f += section("STEP 5 — Deep dive: the SQLi (agent 1 VFS)")
    f += blank()
    f += prompt_line()
    f += type_cmd("kaos read sqli-agent /findings/sqli_001.md")
    f += blank()
    f += out(f"  {B}{CY}Finding: SQL Injection — sqli_001{R}")
    f += out(f"  {DG}─────────────────────────────────────────────────────────────────────{R}")
    f += blank()
    f += out(f"  {BY}Severity:{R}  {BR}CRITICAL{R}")
    f += out(f"  {BY}File:{R}      routes/users.py  line 34")
    f += out(f"  {BY}PR:{R}        PR-2847  feat: add user search endpoint")
    f += blank()
    f += out(f"  {BY}Vulnerable code:{R}")
    f += out(f"  {DG}  query = {R}{BR}f\"SELECT * FROM users WHERE name LIKE '%{{q}}%'\"{R}")
    f += out(f"  {DG}  result = db.execute({R}{BR}query{R}{DG}){R}")
    f += blank()
    f += out(f"  {BY}Attack vector:{R}")
    f += out(f"  {DG}  GET /users/search?q={R}{BR}' OR '1'='1{R}")
    f += out(f"  {DG}  Resulting query: SELECT * FROM users WHERE name LIKE '%{R}{BR}' OR '1'='1{R}{DG}%'{R}")
    f += out(f"  {DG}  Returns all rows.  No auth check.  Full table exposure.{R}")
    f += blank()
    f += out(f"  {BY}Recommended fix:{R}")
    f += out(f"  {BG}  query = \"SELECT * FROM users WHERE name LIKE ?\"{R}")
    f += out(f"  {BG}  result = db.execute(query, (f\"%{{q}}%\",)){R}")
    f += out(f"  {DG}  Use parameterized queries. Never interpolate user input into SQL.{R}")
    f += blank()
    f += [pause(2200)]

    # ── Scene 7: Verify isolation ─────────────────────────────────────────────
    f += section("STEP 6 — Verify isolation (other agents unaffected)")
    f += blank()
    f += prompt_line()
    f += type_cmd('kaos --json query "SELECT agent_id, file_count, status FROM agents WHERE run_id=\'audit-pr-2847\'"')
    f += blank()
    f += out(f"  {B}agent_id{R}      {B}file_count{R}   {B}status{R}    {B}run_id{R}")
    f += out(f"  {DG}────────────  ──────────   ────────  ─────────────────{R}")
    f += out(f"  {RD}sqli-agent{R}     {BY}7{R}            {G}complete{R}  audit-pr-2847", 60)
    f += out(f"  {Y}ssrf-agent{R}      {BY}7{R}            {G}complete{R}  audit-pr-2847", 60)
    f += out(f"  {BR}auth-agent{R}      {BY}7{R}            {G}complete{R}  audit-pr-2847", 60)
    f += out(f"  {BL}deser-agent{R}     {BY}7{R}            {G}complete{R}  audit-pr-2847", 60)
    f += blank()
    f += out(f"  {DG}4 rows  │  all complete  │  no shared state  │  VFS namespaces isolated{R}")
    f += blank()
    f += out(f"  {DG}Each agent started from the same snapshot.  Writes by sqli-agent{R}")
    f += out(f"  {DG}(its findings) are invisible to auth-agent and vice versa.{R}")
    f += out(f"  {DG}Isolation tier: logical (separate key namespaces in kaos.db){R}")
    f += blank()
    f += [pause(1200)]

    # ── Scene 8: Summary ──────────────────────────────────────────────────────
    f += section("Result — Security audit complete")
    f += blank()
    f += out(f"  {DG}PR-2847  {R}{WH}feat: add user search endpoint{R}  {DG}— audit results:{R}")
    f += blank()
    f += out(f"  {BR}[CRITICAL]{R}  SQL injection in /users/search — raw f-string in SQL  {DG}routes/users.py:34{R}")
    f += out(f"  {BR}[CRITICAL]{R}  Hardcoded production API key exposed in PR diff         {DG}config.py:47{R}")
    f += out(f"  {Y}[MEDIUM]  {R}  Unvalidated user URL passed to requests.get()          {DG}routes/users.py:71{R}")
    f += out(f"  {G}[CLEAN]   {R}  Deserialization: all inputs schema-validated            {DG}no action needed{R}")
    f += blank()
    f += out(f"  {DG}──────────────────────────────────────────────────────────────────{R}")
    f += blank()
    f += out(f"  {DG}Agents:{R}         {BY}4{R}  {DG}(sqli, ssrf, auth, deser){R}")
    f += out(f"  {DG}Scan time:{R}      {BY}~43 seconds{R}  {DG}(parallel){R}")
    f += out(f"  {DG}CRITICAL:{R}       {BR}2{R}")
    f += out(f"  {DG}MEDIUM:{R}         {Y}1{R}")
    f += out(f"  {DG}CLEAN:{R}          {G}1{R}")
    f += out(f"  {DG}Conflicts:{R}      {G}0{R}  {DG}(VFS isolation — agents never touch each other's data){R}")
    f += blank()
    f += out(f"  {DG}Verdict:{R}  {BR}Block PR-2847.{R}  Rotate ANALYTICS_KEY before anything else.")
    f += out(f"          {DG}Fix SQLi with parameterized query.  Add URL allowlist for avatar fetch.{R}")
    f += blank()
    f += [pause(3000)]
    f += [pause(2000)]

    return f


# ── YAML output ────────────────────────────────────────────────────────────────

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    out_yml = os.path.join(script_dir, "kaos_uc_security.yml")

    records = build()
    config  = make_config("KAOS — Security Audit: 4 Parallel Agents, 1 PR, Zero Conflicts")

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
    print(f"  uv run python render_gif.py kaos_uc_security.yml")


if __name__ == "__main__":
    main()


