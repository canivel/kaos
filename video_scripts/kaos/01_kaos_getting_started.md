# Tutorial 01 — KAOS Getting Started: Your First Isolated Agent
**Duration:** 5 minutes  
**Level:** Beginner  
**Goal:** Install KAOS, initialize a database, spawn an agent, write and read files in its isolated VFS, and inspect state.

---

## SCENE 1 — Hook [0:00–0:20]

**[VISUAL: Two agents both writing to `/src/auth.py` — one overwrites the other. Files corrupted. Terminal shows error.]**

> "You're running two AI agents in parallel. Both think they're working in isolation. But they're writing to the same files. One overwrites the other. You find out at deployment. This is the problem KAOS was built to eliminate — every agent gets its own virtual filesystem, enforced at the database level. Let's set it up."

---

## SCENE 2 — Install [0:20–0:50]

**[VISUAL: Terminal window, dark theme]**

> "Install KAOS with uv — it's a single package."

```bash
git clone https://github.com/canivel/kaos.git
cd kaos
uv sync
```

> "Then run the setup wizard. It walks you through picking a preset — local models, Claude Code, or a hybrid — and creates your config file and database in one step."

```bash
kaos setup
```

**[VISUAL: Interactive wizard prompts with preset options highlighted]**

> "Pick a preset, confirm the config, and you're ready. The wizard also auto-installs the MCP server into Claude Code if you have it."

---

## SCENE 3 — The Core Concept [0:50–1:30]

**[VISUAL: Diagram — one `.db` file, multiple agents each with their own VFS slice]**

> "KAOS stores everything in a single SQLite `.db` file. Every agent gets an isolated virtual filesystem inside that file — scoped by agent ID at the SQL level. Agents literally cannot see each other's files. Not by convention. By enforcement.

The same file holds the event journal, checkpoints, key-value state, and tool call history. Copy it to back up. Query it with any SQLite client. Send it to a teammate to replay what happened."

---

## SCENE 4 — Spawn an Agent and Write Files [1:30–2:40]

**[VISUAL: Python REPL or file `demo.py`]**

> "Let's use KAOS as a Python library. Import Kaos, open a database, and spawn two agents."

```python
from kaos import Kaos

db = Kaos("project.db")

# Spawn two agents — each gets its own isolated filesystem
researcher = db.spawn("researcher", config={"team": "backend"})
writer     = db.spawn("doc-writer",  config={"team": "docs"})

print(researcher)  # 01JQXYZ...  (a ULID)
```

> "Now write to both agents — using the same path."

```python
db.write(researcher, "/findings.md", b"# Bug Report\nSQL injection in auth.py")
db.write(writer,     "/findings.md", b"# Docs Draft\nAPI v2 overview...")

# Read back — each agent sees only its own version
print(db.read(researcher, "/findings.md").decode())
# → "# Bug Report\nSQL injection in auth.py"

print(db.read(writer, "/findings.md").decode())
# → "# Docs Draft\nAPI v2 overview..."
```

**[VISUAL: Side-by-side — same path, two completely different contents]**

> "Same path. Two different files. Neither agent can see the other's. This is enforced — if you try to read across agents without explicit cross-agent tools, you get a FileNotFoundError."

---

## SCENE 5 — Key-Value State [2:40–3:20]

**[VISUAL: set_state / get_state calls]**

> "Agents also have persistent key-value state — separate from files. Use it for progress tracking, config, or anything that doesn't need to be a file."

```python
db.set_state(researcher, "progress", 75)
db.set_state(researcher, "findings", ["SQL injection", "missing rate limit"])

# State survives crashes — it's in SQLite
progress = db.get_state(researcher, "progress")
print(progress)  # 75

findings = db.get_state(researcher, "findings")
print(findings)  # ["SQL injection", "missing rate limit"]
```

> "Because everything is in SQLite, state survives process crashes. No in-memory state, no lost progress."

---

## SCENE 6 — CLI Inspection [3:20–4:20]

**[VISUAL: Terminal — running CLI commands, output shown]**

> "Everything you do through the Python API is also accessible from the CLI. Let's inspect what we just created."

```bash
# List all agents
kaos ls
```

**[VISUAL: Table output showing researcher and doc-writer with status "running"]**

```bash
# Read a file from a specific agent's VFS
kaos read <researcher-id> /findings.md
```

**[VISUAL: File contents displayed in terminal]**

```bash
# Status shows agent config, state keys, file count
kaos status <researcher-id>
```

> "The CLI is useful for quick inspection during development, or for automation — every command supports `--json` for structured output you can pipe to jq or pass to another agent."

```bash
kaos --json ls | jq '.[0].agent_id'
```

---

## SCENE 7 — Summary [4:20–5:00]

**[VISUAL: Architecture diagram — db file, agents, VFS isolation]**

> "What you learned: KAOS stores everything — files, state, events — in one SQLite `.db` file. Every agent gets an isolated VFS at the SQL level. Same path in two agents means two different files. Key-value state persists across crashes. The Python API and CLI are two views onto the same data.

In the next tutorial: checkpoints and restore — how to snapshot an agent's full state before risky operations and roll back in one command without touching other agents."

---

## AI VIDEO GENERATION NOTES
- **Voice tone:** Confident, problem-solution. The opening hook should feel like a real incident.
- **Diagram (Scene 3):** Animate the `.db` file like a container opening to reveal agent slices. Each slice has a name badge.
- **Code (Scene 4):** Highlight the two identical paths (`/findings.md`) in contrasting colors, then show the different outputs side by side.
- **Terminal (Scene 6):** Show real-looking tabular output — agent IDs truncated to 12 chars, status column green for "running."
