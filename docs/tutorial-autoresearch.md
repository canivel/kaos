# Tutorial: Autonomous Research Lab with KAOS

> Run N research agents in parallel, each exploring a different ML hypothesis, all isolated and auditable. Inspired by [Karpathy's autoresearch](https://github.com/karpathy/autoresearch).

---

## The Idea

Andrej Karpathy's [autoresearch](https://github.com/karpathy/autoresearch) showed that a single AI agent can autonomously run ML experiments overnight — modifying `train.py`, running 5-minute training runs, keeping improvements, discarding regressions, repeating forever.

But autoresearch is one agent, one GPU, one direction. What if you could run **4 agents in parallel** — one exploring architectures, one exploring optimizers, one exploring scaling laws, one exploring regularization — all at the same time, all isolated, all trackable?

That's what KAOS enables.

## What autoresearch Does vs. What KAOS Adds

| autoresearch | KAOS Research Lab |
|---|---|
| 1 agent, 1 GPU | N agents, N directions, parallel |
| Git commit/reset for checkpoints | Formal checkpoints with diff |
| results.tsv for tracking | SQL-queryable event journal |
| Git log for audit trail | 14-event-type append-only journal |
| One train.py, modified in place | Each agent has its own isolated copy |
| Manual inspection | `kaos query "SELECT ..."` |
| One direction at a time | Explore architecture, optimizer, scaling, regularization simultaneously |

## How It Works

### Step 1: Define Your Training Script

```python
# Your base train.py — each agent gets its own isolated copy
BASE_TRAIN_PY = """
CONFIG = {
    "n_layers": 6,
    "n_heads": 6,
    "d_model": 384,
    "learning_rate": 3e-4,
    "optimizer": "adamw",
    "activation": "gelu",
}

def train(config):
    # ... your PyTorch training loop ...
    return {"val_bpb": val_loss}
"""
```

### Step 2: Define Research Directions

Each direction becomes a KAOS agent with a specific research mandate:

```python
DIRECTIONS = [
    {
        "name": "architecture-explorer",
        "prompt": "Explore architecture changes: layers, heads, dimensions, "
                  "activations. Try one change at a time. Keep improvements.",
    },
    {
        "name": "optimizer-explorer",
        "prompt": "Explore optimizer changes: AdamW vs Muon, learning rates, "
                  "weight decay, warmup schedules. Keep improvements.",
    },
    {
        "name": "scaling-explorer",
        "prompt": "Explore scaling laws: more layers vs wider model, "
                  "FFN ratio, head count vs head dim. Find optimal allocation.",
    },
    {
        "name": "regularization-explorer",
        "prompt": "Explore regularization: dropout rates, weight decay, "
                  "batch size interactions. Keep improvements.",
    },
]
```

### Step 3: Spawn and Run

```python
db = Kaos("research-lab.db")
router = GEPARouter.from_config("kaos.yaml")
ccr = ClaudeCodeRunner(db, router, checkpoint_interval=5)

# Each agent gets its own isolated copy of train.py
for direction in DIRECTIONS:
    agent_id = db.spawn(direction["name"])
    db.write(agent_id, "/train.py", BASE_TRAIN_PY.encode())
    db.checkpoint(agent_id, label="baseline")

# Run all 4 in parallel — fully isolated, auto-checkpointed
results = await ccr.run_parallel(DIRECTIONS)
```

### Step 4: What Happens Inside

Each agent runs an autonomous experiment loop:

```
Agent: architecture-explorer
  ├── Reads /train.py
  ├── Changes CONFIG["activation"] = "swiglu"
  ├── Runs experiment → val_bpb = 1.12 (improved from 1.18)
  ├── Keeps the change ✓
  ├── Changes CONFIG["n_layers"] = 8
  ├── Runs experiment → val_bpb = 1.25 (regressed!)
  ├── Reverts the change ✗
  ├── Changes CONFIG["pos_encoding"] = "learned"
  ├── Runs experiment → val_bpb = 1.10 (improved!)
  ├── Keeps the change ✓
  └── ... continues ...

Agent: optimizer-explorer (running simultaneously, isolated)
  ├── Reads /train.py (its own copy, unaffected by architecture-explorer)
  ├── Changes CONFIG["optimizer"] = "muon"
  ├── Runs experiment → val_bpb = 1.05 (big improvement!)
  ├── Keeps the change ✓
  └── ... continues ...
```

The key: **both agents modified `train.py`, but they can't see each other's changes.** Each has its own VFS. No conflicts. No coordination needed.

KAOS auto-checkpoints every 5 iterations, so if an agent crashes at iteration 23, you restore to iteration 20 and lose at most 3 experiments — not all of them.

### Step 5: Query Results Across All Agents

This is where KAOS shines over autoresearch's TSV file:

```sql
-- Which agent found the best result?
SELECT a.name, s.value as best_val_bpb
FROM state s JOIN agents a ON s.agent_id = a.agent_id
WHERE s.key = 'best_val_bpb'
ORDER BY CAST(s.value AS REAL);

-- How many experiments did each agent run?
SELECT a.name, COUNT(tc.call_id) as experiments
FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id
WHERE tc.tool_name = 'shell_exec'
GROUP BY a.agent_id;

-- Total compute across all agents
SELECT SUM(token_count) as total_tokens,
       SUM(duration_ms) / 1000.0 as total_seconds
FROM tool_calls;

-- Which agent's train.py changed the most?
SELECT a.name, f.version as modifications
FROM files f JOIN agents a ON f.agent_id = a.agent_id
WHERE f.path = '/train.py'
ORDER BY f.version DESC;

-- What did the best agent actually change?
-- (read its final train.py)
SELECT content FROM files f
JOIN agents a ON f.agent_id = a.agent_id
WHERE a.name = 'optimizer-explorer' AND f.path = '/train.py';
```

### Step 6: Combine the Best Findings

After all agents finish, you can read each agent's final `train.py` and manually combine the best changes. Or run a new agent that reads all four results and proposes a merged configuration.

```python
# Read each agent's best config
for agent_name in ["architecture-explorer", "optimizer-explorer", "scaling-explorer", "regularization-explorer"]:
    agents = db.query(f"SELECT agent_id FROM agents WHERE name = '{agent_name}'")
    if agents:
        train_py = db.read(agents[0]["agent_id"], "/train.py")
        print(f"\n[{agent_name}]")
        print(train_py.decode()[:500])
```

## Running the Demo

```bash
# With vLLM running locally:
uv run python examples/autonomous_research_lab.py

# Or via CLI:
kaos parallel \
    -t arch-explorer "Explore architecture changes to /train.py" \
    -t opt-explorer "Explore optimizer changes to /train.py" \
    -t scale-explorer "Explore scaling laws in /train.py" \
    -t reg-explorer "Explore regularization in /train.py"
```

## Multi-GPU Orchestration

For larger-scale research, KAOS supports distributing agents across multiple GPUs, each running a different model tier. The GEPA router assigns agents to specific models via `force_model`.

### 3-GPU Setup

```
GPU 0 — Qwen2.5-Coder-7B   (port 8000) → 2 sweep agents (fast hyperparameter scans)
GPU 1 — Qwen2.5-Coder-32B  (port 8001) → 2 architecture agents (design exploration)
GPU 2 — DeepSeek-R1-70B     (port 8002) → 2 novel research agents (creative hypothesis)
```

### Configuration

```yaml
# kaos.yaml
models:
  qwen2.5-coder-7b:
    vllm_endpoint: http://localhost:8000/v1
    max_context: 32768
    use_for: [trivial, sweep]
  qwen2.5-coder-32b:
    vllm_endpoint: http://localhost:8001/v1
    max_context: 131072
    use_for: [moderate, architecture]
  deepseek-r1-70b:
    vllm_endpoint: http://localhost:8002/v1
    max_context: 131072
    use_for: [complex, novel_research]
```

### Running 6 Agents Across 3 GPUs

```python
# examples/multi_gpu_research.py
from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter

db = Kaos("multi-gpu-research.db")
router = GEPARouter.from_config("kaos.yaml")
ccr = ClaudeCodeRunner(db, router, checkpoint_interval=5)

DIRECTIONS = [
    # GPU 0 — 7B: fast sweeps
    {"name": "lr-sweep",    "prompt": "Sweep learning rates 1e-5 to 1e-2",
     "config": {"force_model": "qwen2.5-coder-7b"}},
    {"name": "batch-sweep", "prompt": "Sweep batch sizes 16 to 256",
     "config": {"force_model": "qwen2.5-coder-7b"}},

    # GPU 1 — 32B: architecture exploration
    {"name": "arch-depth",  "prompt": "Explore deeper architectures (12-24 layers)",
     "config": {"force_model": "qwen2.5-coder-32b"}},
    {"name": "arch-width",  "prompt": "Explore wider architectures (512-2048 d_model)",
     "config": {"force_model": "qwen2.5-coder-32b"}},

    # GPU 2 — 70B: novel research ideas
    {"name": "novel-loss",  "prompt": "Design a novel loss function combining contrastive and generative objectives",
     "config": {"force_model": "deepseek-r1-70b"}},
    {"name": "novel-arch",  "prompt": "Propose a novel attention mechanism for long sequences",
     "config": {"force_model": "deepseek-r1-70b"}},
]

# Each agent gets its own isolated train.py
for d in DIRECTIONS:
    agent_id = db.spawn(d["name"])
    db.write(agent_id, "/train.py", BASE_TRAIN_PY.encode())
    db.checkpoint(agent_id, label="baseline")

# Run all 6 in parallel — GEPA routes each to the correct GPU/model
results = await ccr.run_parallel(DIRECTIONS)
```

Each agent is fully isolated. The 7B agents on GPU 0 churn through hyperparameter sweeps quickly, while the 70B on GPU 2 takes longer but produces more creative research directions. All results are in one `.db` file, queryable with SQL.

## Why KAOS for Autonomous Research?

**Isolation that matters.** In autoresearch, there's one `train.py` — the agent modifies it in place. If you want multiple research directions, you need multiple git worktrees or separate directories. KAOS gives each agent its own virtual filesystem with zero setup.

**Checkpoints that aren't git hacks.** autoresearch uses `git commit` and `git reset`. KAOS checkpoints capture files + state + event watermarks, and you can diff two checkpoints to see exactly what changed. Restore any agent to any point without affecting others.

**SQL-queryable everything.** Instead of parsing a TSV file, query all experiments across all agents with SQL. "Which agent found the best loss?" "How many experiments total?" "What did the failing agent do wrong?" One query, one answer.

**Portability.** The entire research lab — all agents, all experiments, all results — is one `.db` file. Send it to a colleague. Open it on another machine. Back it up with `cp`.

**Scale.** autoresearch runs 12 experiments/hour on one GPU. With KAOS orchestrating 4 agents across 4 GPUs, you run 48 experiments/hour — each exploring a different direction, all isolated and tracked.

## References

- [Karpathy's autoresearch](https://github.com/karpathy/autoresearch) — the original pattern
- [Example script](../examples/autonomous_research_lab.py) — full runnable demo
- [KAOS docs](./tutorial-local-agents.md) — setting up vLLM + KAOS locally
