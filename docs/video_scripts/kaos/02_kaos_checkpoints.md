# Tutorial 02 — KAOS Checkpoints & Restore: Surgical Rollback
**Duration:** 5 minutes  
**Level:** Beginner–Intermediate  
**Goal:** Snapshot agent state before risky operations, restore a single agent without touching others, diff two checkpoints to see exactly what changed.

---

## SCENE 1 — Hook [0:00–0:20]

**[VISUAL: Four agents running. One breaks the codebase. Developer runs `git reset --hard` — ALL agent work is lost, not just the broken one.]**

> "A refactor agent goes rogue and breaks everything. You `git reset --hard` — and lose the work of the three other agents that were fine. With KAOS checkpoints you roll back exactly one agent. The others are untouched. Here's how."

---

## SCENE 2 — Creating a Checkpoint [0:20–1:15]

**[VISUAL: Python code, file `checkpoint_demo.py`]**

> "A checkpoint is a full snapshot of an agent's state at a point in time — its files, key-value state, and metadata. Create one before any operation you might want to undo."

```python
from kaos import Kaos

db = Kaos("project.db")
agent = db.spawn("refactorer")

# Write some initial work
db.write(agent, "/src/auth.py", b"def login(user, pw): ...")
db.set_state(agent, "progress", 40)

# Checkpoint before risky work — label it descriptively
cp_before = db.checkpoint(agent, label="before-database-migration")
print(cp_before)  # "01JQXYZ..."  (checkpoint ID)
```

> "Checkpoints are cheap — KAOS stores only the diff from the previous checkpoint, not a full copy of every file. You can checkpoint frequently without worrying about storage."

---

## SCENE 3 — The Risky Operation [1:15–1:50]

**[VISUAL: Agent modifies files — some good changes, some bad]**

> "The agent runs. It makes some good changes, then something goes wrong."

```python
# Agent does work — some files change
db.write(agent, "/src/auth.py",    b"def login(): broken_migration()")
db.write(agent, "/src/database.py", b"DROP TABLE users;")  # oops
db.set_state(agent, "progress", 90)

# Checkpoint the broken state — useful for diagnosis
cp_after = db.checkpoint(agent, label="post-migration-broken")
```

---

## SCENE 4 — Diff Two Checkpoints [1:50–2:50]

**[VISUAL: Diff output — files changed, state changes]**

> "Before restoring, inspect exactly what changed between the two checkpoints. The diff shows every file added, removed, or modified — and every state key that changed."

```python
diff = db.diff_checkpoints(agent, cp_before, cp_after)
print(diff)
```

**[VISUAL: Diff output]**
```
Files changed:
  MODIFIED  /src/auth.py
            before: b"def login(user, pw): ..."
            after:  b"def login(): broken_migration()"
  ADDED     /src/database.py

State changed:
  progress: 40 → 90
```

> "The diff is queryable — you can filter by file type, see only state changes, or get the raw before/after bytes of any modified file. This is your audit trail."

---

## SCENE 5 — Restore [2:50–3:40]

**[VISUAL: Restore command, then verify files are back]**

> "Roll back to the checkpoint before things went wrong."

```python
db.restore(agent, cp_before)

# Verify — auth.py is back to the original
content = db.read(agent, "/src/auth.py").decode()
print(content)
# → "def login(user, pw): ..."

# database.py is gone — it didn't exist at cp_before
try:
    db.read(agent, "/src/database.py")
except FileNotFoundError:
    print("Correctly removed")

# State is also restored
print(db.get_state(agent, "progress"))  # 40
```

> "One restore call undoes all file writes, all state changes, and all events that happened after the checkpoint. Other agents running in parallel are completely unaffected."

---

## SCENE 6 — CLI Checkpoints [3:40–4:20]

**[VISUAL: Terminal commands]**

> "The same operations are available from the CLI — useful for scripts or when you're inspecting a database someone else created."

```bash
# Create a checkpoint
kaos checkpoint <agent-id> --label "before-migration"

# List all checkpoints for an agent
kaos checkpoints <agent-id>
```

**[VISUAL: Table showing checkpoint IDs, labels, timestamps, file counts]**

```bash
# Diff two checkpoints
kaos diff <agent-id> --from <cp-before-id> --to <cp-after-id>

# Restore
kaos restore <agent-id> --checkpoint <cp-before-id>
```

> "With `--json` on any of these, you get structured output for automated pipelines — checkpoint before a deploy, capture the ID, restore programmatically if health checks fail."

---

## SCENE 7 — Auto-Checkpoint Pattern [4:20–5:00]

**[VISUAL: Pattern — checkpoint before every iteration in a loop]**

> "A practical pattern: checkpoint before every high-stakes step. Here's how the KAOS meta-harness search does it — checkpoint before each iteration so a failed proposer or evaluation can never corrupt the archive."

```python
for iteration in range(1, max_iterations + 1):
    db.checkpoint(agent, label=f"pre-iter-{iteration}")
    
    try:
        run_iteration(agent, iteration)
    except Exception as e:
        print(f"Iteration {iteration} failed: {e}")
        db.restore(agent, f"pre-iter-{iteration}")
        continue  # try next iteration cleanly
```

> "Checkpoints turn agent runs from fragile one-shots into resumable, recoverable processes. In the next tutorial: the live dashboard — how to monitor everything in real time."

---

## AI VIDEO GENERATION NOTES
- **Voice tone:** Practical, reassuring. Stress that rollback is surgical — one agent, not everything.
- **Scene 1 animation:** Show 4 agent progress bars. One turns red. `git reset` wipes all 4 bars (all go to zero). Then show KAOS restore — only 1 bar resets, others remain.
- **Diff output (Scene 4):** Use color coding — green for added, red for removed, yellow for modified. Match git diff conventions.
- **Key callout:** "Other agents running in parallel are completely unaffected" — put this as a text overlay on screen.
