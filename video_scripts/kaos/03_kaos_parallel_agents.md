# Tutorial 03 — Running Agents in Parallel: GEPA Router & CCR
**Duration:** 5 minutes  
**Level:** Intermediate  
**Goal:** Run multiple agents concurrently with the CCR runner, let GEPA auto-route tasks to the right model, query aggregate results.

---

## SCENE 1 — Hook [0:00–0:25]

**[VISUAL: Timeline — sequential: 3 tasks taking 4 minutes each = 12 minutes. Parallel: 3 tasks at once = 4 minutes.]**

> "You have three tasks: write tests, refactor the code, and update the docs. Run them one after another and you wait twelve minutes. Run them in parallel with KAOS and you're done in four — with full isolation between all three, and a complete audit trail of what each one did."

---

## SCENE 2 — The GEPA Router [0:25–1:15]

**[VISUAL: Diagram — task comes in, GEPA classifies, routes to appropriate model]**

> "GEPA stands for Grounded Efficient Prompt Allocation. It's KAOS's model router — it classifies every task and automatically picks the right LLM.

Four tiers: trivial tasks like summarization and formatting go to a fast 7B local model. Standard tasks go to a mid-tier model. Complex reasoning and code generation go to a 70B model. Critical or long-horizon tasks go to Claude or GPT-4."

```yaml
# kaos.yaml — simplified
router:
  providers:
    local_fast:    { type: vllm, model: Qwen2.5-7B,  port: 8000 }
    local_strong:  { type: vllm, model: Qwen2.5-70B, port: 8002 }
    claude:        { type: anthropic, model: claude-sonnet-4-6 }
  
  routing:
    trivial:  local_fast
    standard: local_fast
    complex:  local_strong
    critical: claude
```

> "GEPA classifies based on a fast heuristic — keyword signals, task length, tool requirements — before the main LLM ever runs. You get the right model for the job without manually specifying it per task."

---

## SCENE 3 — CCR: Parallel Agents [1:15–2:20]

**[VISUAL: Code — `ccr.run_parallel`, three tasks launch simultaneously]**

> "The CCR — Claude Code Runner — is the agent execution engine. Pass it a list of tasks and it runs them all in parallel, each in its own isolated KAOS agent."

```python
import asyncio
from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter

db     = Kaos("project.db")
router = GEPARouter.from_config("kaos.yaml")
ccr    = ClaudeCodeRunner(db, router)

results = asyncio.run(ccr.run_parallel([
    {
        "name":   "tests",
        "prompt": "Write unit tests for the payments module. Cover happy path, empty cart, and payment failure.",
    },
    {
        "name":   "refactor",
        "prompt": "Refactor the payments module to use Stripe SDK v3. Keep the existing interface.",
    },
    {
        "name":   "docs",
        "prompt": "Update the payment API documentation with the new Stripe endpoints.",
    },
]))
```

> "Three agents launch simultaneously. GEPA classifies each prompt — test writing goes to local_strong, refactoring goes to local_strong, docs go to local_fast. All three run in parallel, each with their own VFS."

---

## SCENE 4 — Inspecting Results [2:20–3:20]

**[VISUAL: Print results, then query the DB]**

> "Each result has the agent ID, final status, and output. But the real data lives in the database."

```python
for r in results:
    print(r["name"], r["status"], r["agent_id"][:12])
# tests    completed  01JQXYZ...
# refactor completed  01JQABC...
# docs     completed  01JQDEF...

# Read what each agent produced
tests_output = db.read(results[0]["agent_id"], "/tests.py")
print(tests_output.decode()[:500])
```

> "Now query across all three agents with SQL — how many tokens did each use? How many tool calls?"

```python
stats = db.query("""
    SELECT a.name,
           COUNT(tc.call_id)  AS tool_calls,
           SUM(tc.token_count) AS tokens_used
    FROM agents a
    LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
    WHERE a.name IN ('tests', 'refactor', 'docs')
    GROUP BY a.agent_id
""")

for row in stats:
    print(f"{row['name']:10} {row['tool_calls']} calls  {row['tokens_used']} tokens")
```

**[VISUAL: Table showing per-agent stats]**

---

## SCENE 5 — CLI Parallel Run [3:20–3:55]

**[VISUAL: Terminal — kaos parallel command]**

> "The CLI has a `parallel` command for running agents without writing Python."

```bash
kaos parallel \
  -t tests    "Write unit tests for the payments module" \
  -t refactor "Refactor payments to use Stripe SDK v3" \
  -t docs     "Update payment API documentation"
```

> "Each `-t` flag is a task name and prompt. KAOS spawns all agents, runs them in parallel, and prints a summary table when they finish."

**[VISUAL: Live progress indicator — three agent names, each with a spinner, then checkmarks as they complete]**

---

## SCENE 6 — The Live Dashboard [3:55–4:30]

**[VISUAL: `kaos dashboard` TUI with all three agents visible]**

> "While agents are running, open the dashboard in a second terminal."

```bash
kaos dashboard
```

> "You get a live TUI showing every agent's status, file count, tool call count, token usage, and a streaming event log. When three agents are running in parallel you see all three simultaneously — which one is active, which tool it just called, how far along it is."

**[VISUAL: TUI with three panels, each updating in real time]**

---

## SCENE 7 — Summary [4:30–5:00]

**[VISUAL: Architecture diagram — GEPA routing, CCR, three agents, SQLite]**

> "GEPA classifies tasks and routes to the right model automatically — you don't pick the model per task, you configure tiers once. CCR runs agents in parallel with full isolation. SQL queries give you aggregate stats across all agents after the run. The CLI parallel command handles simple cases without code. And the dashboard shows everything live.

Next tutorial: the MCP server — connecting KAOS to Claude Code so Claude can spawn and manage agents directly from a conversation."

---

## AI VIDEO GENERATION NOTES
- **Voice tone:** Energetic. The performance comparison in Scene 1 is the core hook.
- **Diagram (Scene 2):** GEPA classification should animate as a decision tree: task arrives → classifier runs → branch to model tier → model icon lights up.
- **Scene 3:** Show all three agent progress bars appearing simultaneously, not sequentially — this visualizes the parallelism.
- **Terminal (Scene 6):** Show a real-looking TUI with box borders, color-coded status columns (green = running, blue = completed).
