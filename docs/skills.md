# Cross-Agent Skill Library

> **Source:** "Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering" — Zhou et al. 2026, [arXiv:2604.08224](https://arxiv.org/abs/2604.08224)

---

## What is a skill?

A skill is a **parameterized prompt template** that encodes a reliable solution strategy. Skills are *procedural* — they tell agents *how* to do something. This distinguishes them from memory entries, which are *factual* (what happened, what was found).

| | Memory | Skill |
|---|---|---|
| **What it stores** | Facts, observations, results | Procedures, strategies, templates |
| **Example** | "Accuracy improved to 87% with ensemble voting" | "To improve accuracy: try {n} models with {voting} voting" |
| **When to use** | After an agent finishes work | When an agent discovers a reusable pattern |
| **Retrieval** | FTS5 search by content | FTS5 search by name, description, tags, template |
| **Table** | `memory` | `agent_skills` |

---

## Why skills?

Agents repeatedly reinvent solutions. An agent that discovers a reliable pattern for classifying text, debugging async code, or structuring API responses has no way to share that procedure with future agents — unless it's explicitly stored as a skill.

KAOS's skill library solves this. Any agent can save a skill. Any agent, in any future session, can search for relevant skills before starting a task.

The self-improving loop:
1. Agent solves a hard problem and identifies a reliable pattern
2. Agent calls `skill_save` (or `kaos skills save`) to store the template
3. Future agents call `skill_search "task description"` to find it
4. Agent renders the skill with `skill_apply`, fills in parameters, uses it
5. Agent records the outcome — success or failure — so reliability accumulates over time

---

## Schema

```sql
CREATE TABLE agent_skills (
    skill_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT NOT NULL,
    template        TEXT NOT NULL,          -- {param} placeholders
    tags            TEXT NOT NULL DEFAULT '[]',  -- JSON array
    source_agent_id TEXT,
    use_count       INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- FTS5 index over name, description, tags, template
CREATE VIRTUAL TABLE agent_skills_fts USING fts5(
    name, description, tags, template,
    tokenize = 'porter unicode61'
);
```

---

## Python API

```python
from kaos import Kaos
from kaos.skills import SkillStore

kaos = Kaos("project.db")
sk   = SkillStore(kaos.conn)

# Save a skill after discovering a reliable pattern
sid = sk.save(
    name="ensemble_classifier",
    description="Improve classification accuracy with ensemble voting",
    template=(
        "Implement a {n_models}-model ensemble for {task}. "
        "Use {voting} voting. Tune the decision threshold to {threshold}."
    ),
    tags=["classification", "ensemble", "accuracy"],
    source_agent_id="agent-01",
)

# Search before starting a similar task
hits = sk.search("classification accuracy")
for s in hits:
    print(s.name, s.params())  # → ['n_models', 'task', 'voting', 'threshold']

# Render the skill with parameters
skill = sk.get(sid)
prompt = skill.apply(
    n_models="3",
    task="sentiment analysis",
    voting="majority",
    threshold="0.5",
)

# Track outcomes so reliability accumulates
sk.record_outcome(sid, success=True)

# List skills — order by reliability
reliable = sk.list(order_by="success_count")
```

---

## CLI

```bash
# Save a skill
kaos skills save \
  --name ensemble_classifier \
  --description "Improve classification accuracy with ensemble voting" \
  --template "Use {n_models} models with {voting} voting on {task}." \
  --tags classification,ensemble

# Search before starting work
kaos skills search "classification accuracy"
kaos skills search "async error handling" --tag python

# List all skills — sorted by most used
kaos skills ls --order use_count

# Render a skill with parameters
kaos skills apply 3 -p n_models=3 -p voting=majority -p task="sentiment"

# Delete
kaos skills delete 3
```

---

## MCP tools (for Claude Code / Cursor)

| Tool | Description |
|---|---|
| `skill_save` | Save a new skill with name, description, template, and tags |
| `skill_search` | BM25 full-text search across all skills |
| `skill_apply` | Render a skill template with parameters |
| `skill_list` | List skills with optional tag/agent/sort filters |
| `skill_outcome` | Record success or failure for a used skill |

### Example workflow in Claude Code

```
# Before starting a refactoring task:
skill_search("refactoring async python")

# → finds skill #7: "async_refactor"
# → template: "Refactor {module} to use {pattern}. Key steps: {steps}"

skill_apply(skill_id=7, params={
    "module": "auth.py",
    "pattern": "async/await",
    "steps": "1. replace callbacks, 2. add error boundaries, 3. update tests"
})

# After completing the task:
skill_outcome(skill_id=7, success=True)
```

---

## How FTS5 search works

Skills are indexed using SQLite FTS5 with porter stemming over four fields:

- `name` — snake_case identifier
- `description` — what the skill does and when to use it
- `tags` — JSON array stored as text (tokenized)
- `template` — the full prompt template including placeholder names

Results are ranked by BM25 relevance. The search supports full FTS5 syntax:

```bash
kaos skills search "ensemble accuracy"        # stemmed phrase
kaos skills search '"gradient clipping"'      # exact phrase
kaos skills search "classification NOT naive" # negation
kaos skills search "classif*"                 # prefix wildcard
```

---

## Skills vs. memory — when to use each

Use **memory** when:
- You want to record what happened: "model achieved 87% on dataset X"
- You want to record a finding or error for future agents to know about
- The value is in the *fact*, not in reusing the *procedure*

Use **skills** when:
- You've identified a reliable strategy that should be reused
- The value is in the *template* — a parameterized procedure
- Future agents tackling similar tasks should find and apply this pattern

Both are searchable via FTS5. Both are shared across all agents in the project. They complement each other in the agent's externalized knowledge base.

---

## Credits

The skill library design is informed by the *externalization* framework in:

> "Externalization in LLM Agents: A Unified Review of Memory, Skills, Protocols and Harness Engineering"
> Zhou, Chai, Chen, et al. (2026)
> [arXiv:2604.08224](https://arxiv.org/abs/2604.08224)

The paper identifies four axes of externalization in LLM agent systems — memory, skills, protocols, and harness engineering. KAOS now implements all four:

| Axis | KAOS component |
|---|---|
| Memory | `MemoryStore` — FTS5 cross-agent episodic memory |
| **Skills** | **`SkillStore` — FTS5 cross-agent procedural templates** |
| Protocols | `SharedLog` — LogAct intent/vote/decide |
| Harness | `MetaHarness` — evolutionary strategy optimization |
