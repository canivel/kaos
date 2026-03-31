"""
Autonomous Research Lab — Multi-Agent ML Experiment Orchestration
=================================================================

Inspired by Karpathy's autoresearch (https://github.com/karpathy/autoresearch):
one agent, one GPU, modify train.py, run 5-min experiments, keep or discard.

This example scales that pattern with KAOS: run N research agents in parallel,
each isolated in its own VFS, each exploring a different research direction,
with centralized experiment tracking via SQL.

What autoresearch does with git commit/reset, KAOS does with formal checkpoints.
What autoresearch tracks in a TSV file, KAOS tracks in a SQL-queryable database.
What autoresearch runs as one agent, KAOS runs as many — isolated, auditable,
portable.

The pattern:
  1. Define a base training script (train.py)
  2. Spawn N research agents, each with a different research direction
  3. Each agent modifies the script, runs an experiment, evaluates the result
  4. If the metric improves → checkpoint and keep. If not → restore and try again.
  5. Query all agents' results with SQL to find the best experiment across all directions.

Usage:
    uv run python examples/autonomous_research_lab.py

See also:
    - Karpathy's autoresearch: https://github.com/karpathy/autoresearch
    - KAOS docs: docs/tutorial-autoresearch.md
"""

from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any

from kaos import Kaos
from kaos.ccr.runner import ClaudeCodeRunner
from kaos.router.gepa import GEPARouter


# ── The base training script (simplified for demo) ───────────────

BASE_TRAIN_PY = """\
import math
import time
import random

# === Model Configuration ===
CONFIG = {
    "n_layers": 6,
    "n_heads": 6,
    "d_model": 384,
    "d_ff": 1536,          # feed-forward inner dim
    "dropout": 0.1,
    "learning_rate": 3e-4,
    "weight_decay": 0.1,
    "batch_size": 64,
    "max_seq_len": 256,
    "warmup_steps": 100,
    "optimizer": "adamw",   # adamw | muon | sgd
    "activation": "gelu",   # gelu | swiglu | relu
    "norm": "rmsnorm",      # rmsnorm | layernorm
    "pos_encoding": "rope", # rope | learned | sinusoidal
}

def simulate_training(config, time_budget=5.0):
    \"\"\"Simulate a training run and return validation loss.

    In a real setup this would call PyTorch. Here we use a synthetic
    loss function that responds realistically to hyperparameter changes.
    \"\"\"
    random.seed(hash(json.dumps(config, sort_keys=True)) % 2**32)

    # Base loss from architecture choices
    base = 1.8
    base -= config["n_layers"] * 0.05
    base -= config["n_heads"] * 0.03
    base -= config["d_model"] * 0.001

    # Optimizer impact
    opt_bonus = {"adamw": 0.1, "muon": 0.15, "sgd": 0.0}
    base -= opt_bonus.get(config["optimizer"], 0)

    # Activation impact
    act_bonus = {"swiglu": 0.08, "gelu": 0.05, "relu": 0.0}
    base -= act_bonus.get(config["activation"], 0)

    # Learning rate sweet spot (too high or too low hurts)
    lr = config["learning_rate"]
    lr_penalty = abs(math.log10(lr) - math.log10(3e-4)) * 0.2
    base += lr_penalty

    # Noise
    base += random.gauss(0, 0.03)

    # Simulate time
    time.sleep(min(time_budget, 0.1))  # Fast for demo

    val_bpb = max(0.5, base)
    return {"val_bpb": round(val_bpb, 4), "train_bpb": round(val_bpb - 0.05, 4)}

if __name__ == "__main__":
    import json
    result = simulate_training(CONFIG)
    print(json.dumps({"config": CONFIG, **result}))
"""

# ── Research directions ──────────────────────────────────────────

RESEARCH_DIRECTIONS = [
    {
        "name": "architecture-explorer",
        "prompt": (
            "You are an ML researcher exploring architecture improvements. "
            "Read /train.py, understand the CONFIG, then propose changes to "
            "n_layers, n_heads, d_model, d_ff, activation, norm, or pos_encoding. "
            "Try one change at a time. Run the experiment, check val_bpb. "
            "Lower is better. If it improves, keep the change and try another. "
            "If it regresses, revert and try something different. "
            "Log each experiment to /experiments.jsonl."
        ),
    },
    {
        "name": "optimizer-explorer",
        "prompt": (
            "You are an ML researcher exploring optimizer improvements. "
            "Read /train.py, focus on optimizer, learning_rate, weight_decay, "
            "warmup_steps, and batch_size. Try different optimizers (adamw, muon, sgd), "
            "learning rate schedules, and regularization strategies. "
            "Run the experiment, check val_bpb. Lower is better. "
            "Keep improvements, revert regressions. "
            "Log each experiment to /experiments.jsonl."
        ),
    },
    {
        "name": "scaling-explorer",
        "prompt": (
            "You are an ML researcher exploring scaling laws. "
            "Read /train.py and systematically vary model size: "
            "try larger d_model with fewer layers, more heads with smaller dim, "
            "wider FFN ratios. Find the best parameter allocation for fixed "
            "compute budget. Run experiments, check val_bpb. Lower is better. "
            "Log each experiment to /experiments.jsonl."
        ),
    },
    {
        "name": "regularization-explorer",
        "prompt": (
            "You are an ML researcher exploring regularization. "
            "Read /train.py and experiment with dropout rates, weight decay, "
            "and batch size interactions. Try dropout 0.0 to 0.3, "
            "weight_decay 0.01 to 1.0, batch sizes 32 to 256. "
            "Run experiments, check val_bpb. Lower is better. "
            "Log each experiment to /experiments.jsonl."
        ),
    },
]


async def run_research_lab():
    """Run an autonomous research lab with N parallel agents."""

    db = Kaos("research-lab.db")
    router = GEPARouter.from_config("kaos.yaml")
    ccr = ClaudeCodeRunner(
        db, router,
        max_iterations=30,       # Each agent gets 30 iterations
        checkpoint_interval=5,   # Auto-checkpoint every 5 iterations
        max_parallel_agents=4,
    )

    print("=" * 60)
    print("KAOS Autonomous Research Lab")
    print("=" * 60)
    print(f"Agents: {len(RESEARCH_DIRECTIONS)}")
    print(f"Directions: {', '.join(d['name'] for d in RESEARCH_DIRECTIONS)}")
    print(f"Pattern: autoresearch (Karpathy) × KAOS orchestration")
    print()

    # Spawn agents, each with the base training script
    agent_ids = []
    for direction in RESEARCH_DIRECTIONS:
        agent_id = db.spawn(direction["name"], config={"role": "researcher"})
        agent_ids.append(agent_id)

        # Write the base training script to each agent's VFS
        db.write(agent_id, "/train.py", BASE_TRAIN_PY.encode())
        db.write(agent_id, "/experiments.jsonl", b"")

        # Create a baseline checkpoint
        db.checkpoint(agent_id, label="baseline")

        print(f"  Spawned: {direction['name']} ({agent_id[:12]}...)")

    print(f"\nRunning {len(agent_ids)} agents in parallel...")
    start = time.time()

    # Run all agents in parallel — each explores its own direction
    # Each agent is isolated: can't see or modify other agents' train.py
    results = await ccr.run_parallel([
        {"name": d["name"], "prompt": d["prompt"]}
        for d in RESEARCH_DIRECTIONS
    ])

    duration = time.time() - start
    print(f"\nAll agents finished in {duration:.1f}s")

    # ── Analyze results across all agents ─────────────────────────

    print("\n" + "=" * 60)
    print("RESEARCH LAB RESULTS")
    print("=" * 60)

    # Per-agent summary
    for direction, result in zip(RESEARCH_DIRECTIONS, results):
        print(f"\n[{direction['name']}]")
        print(f"  Result: {result[:200]}")

    # Query all experiments across all agents with SQL
    print("\n--- Cross-Agent Analysis (SQL) ---")

    # How many experiments did each agent run?
    agent_stats = db.query("""
        SELECT a.name,
               COUNT(tc.call_id) as tool_calls,
               COALESCE(SUM(tc.token_count), 0) as tokens
        FROM agents a
        LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
        WHERE a.name LIKE '%-explorer'
        GROUP BY a.agent_id
        ORDER BY tokens DESC
    """)
    print("\nAgent workload:")
    for row in agent_stats:
        print(f"  {row['name']:30s} {row['tool_calls']:>4} calls  {row['tokens']:>8,} tokens")

    # What files did each agent modify?
    files = db.query("""
        SELECT a.name, f.path, f.version
        FROM files f
        JOIN agents a ON f.agent_id = a.agent_id
        WHERE f.deleted = 0 AND a.name LIKE '%-explorer'
        ORDER BY a.name, f.path
    """)
    print("\nFiles per agent:")
    for row in files:
        print(f"  [{row['name']}] {row['path']} (v{row['version']})")

    # How many checkpoints (including auto-checkpoints)?
    checkpoints = db.query("""
        SELECT a.name, COUNT(c.checkpoint_id) as checkpoints
        FROM agents a
        LEFT JOIN checkpoints c ON a.agent_id = c.agent_id
        WHERE a.name LIKE '%-explorer'
        GROUP BY a.agent_id
    """)
    print("\nCheckpoints per agent:")
    for row in checkpoints:
        print(f"  {row['name']:30s} {row['checkpoints']} checkpoints")

    # Total events
    events = db.query("SELECT COUNT(*) as n FROM events")
    print(f"\nTotal events logged: {events[0]['n']}")

    # Full event breakdown
    event_types = db.query("""
        SELECT event_type, COUNT(*) as count
        FROM events GROUP BY event_type ORDER BY count DESC
    """)
    print("Event breakdown:")
    for row in event_types:
        print(f"  {row['event_type']:25s} {row['count']:>6}")

    db.close()
    print(f"\n--- All data saved to research-lab.db ---")
    print(f"Query with: sqlite3 research-lab.db 'SELECT * FROM events LIMIT 20'")
    print(f"Or:         kaos query 'SELECT * FROM tool_calls' --db research-lab.db")


if __name__ == "__main__":
    asyncio.run(run_research_lab())
