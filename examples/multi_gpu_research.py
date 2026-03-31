"""
Multi-GPU Autonomous Research Orchestration
=============================================

Scales the autoresearch pattern (Karpathy) across multiple GPUs using KAOS.
Each GPU runs a different model or research direction, all orchestrated
with isolated VFS, checkpoints, and centralized SQL-queryable results.

Architecture:
    GPU 0 (port 8000): Qwen 7B  — fast experiments, hyperparameter sweeps
    GPU 1 (port 8001): Qwen 32B — moderate complexity, architecture changes
    GPU 2 (port 8002): DS-R1 70B — complex experiments, novel architectures

Each GPU gets its own research agent routed by GEPA based on task complexity.
Simple hyperparameter tweaks → GPU 0 (fast). Architecture redesigns → GPU 2
(powerful). All results flow into one SQLite database.

Usage:
    # Start 3 vLLM instances on 3 GPUs:
    CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-Coder-7B-Instruct --port 8000
    CUDA_VISIBLE_DEVICES=1 vllm serve Qwen/Qwen2.5-Coder-32B-Instruct --port 8001
    CUDA_VISIBLE_DEVICES=2 vllm serve deepseek-ai/DeepSeek-R1-70B --port 8002

    # Then run:
    uv run python examples/multi_gpu_research.py

    # Or with kaos.yaml configured for 3 models:
    uv run python examples/multi_gpu_research.py --config kaos.yaml

See also:
    - Single-GPU version: examples/autonomous_research_lab.py
    - Karpathy's autoresearch: https://github.com/karpathy/autoresearch
    - KAOS docs: docs/tutorial-autoresearch.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from kaos import Kaos
from kaos.ccr.runner import ClaudeCodeRunner
from kaos.router.gepa import GEPARouter


BASE_TRAIN_PY = """\
import math
import time
import random
import json

CONFIG = {
    "n_layers": 6,
    "n_heads": 6,
    "d_model": 384,
    "d_ff": 1536,
    "dropout": 0.1,
    "learning_rate": 3e-4,
    "weight_decay": 0.1,
    "batch_size": 64,
    "max_seq_len": 256,
    "warmup_steps": 100,
    "optimizer": "adamw",
    "activation": "gelu",
    "norm": "rmsnorm",
    "pos_encoding": "rope",
}

def simulate_training(config, time_budget=5.0):
    random.seed(hash(json.dumps(config, sort_keys=True)) % 2**32)
    base = 1.8
    base -= config["n_layers"] * 0.05
    base -= config["n_heads"] * 0.03
    base -= config["d_model"] * 0.001
    opt_bonus = {"adamw": 0.1, "muon": 0.15, "sgd": 0.0}
    base -= opt_bonus.get(config["optimizer"], 0)
    act_bonus = {"swiglu": 0.08, "gelu": 0.05, "relu": 0.0}
    base -= act_bonus.get(config["activation"], 0)
    lr = config["learning_rate"]
    lr_penalty = abs(math.log10(lr) - math.log10(3e-4)) * 0.2
    base += lr_penalty
    base += random.gauss(0, 0.03)
    time.sleep(min(time_budget, 0.1))
    val_bpb = max(0.5, base)
    return {"val_bpb": round(val_bpb, 4), "train_bpb": round(val_bpb - 0.05, 4)}

if __name__ == "__main__":
    result = simulate_training(CONFIG)
    print(json.dumps({"config": CONFIG, **result}))
"""

# Research directions with explicit GPU/model routing
MULTI_GPU_DIRECTIONS = [
    # GPU 0 — Small model, fast experiments (hyperparameter sweeps)
    {
        "name": "lr-sweep",
        "prompt": (
            "You are exploring learning rate schedules. Read /train.py. "
            "Try learning_rate values: 1e-4, 3e-4, 1e-3, 3e-3. "
            "For each, run the experiment and record val_bpb. "
            "Keep the best. Then try warmup_steps: 50, 100, 200, 500. "
            "Log results to /experiments.jsonl."
        ),
        "config": {"force_model": "qwen2.5-coder-7b"},
    },
    {
        "name": "dropout-sweep",
        "prompt": (
            "You are exploring regularization. Read /train.py. "
            "Try dropout: 0.0, 0.05, 0.1, 0.15, 0.2, 0.3. "
            "For each, run and record val_bpb. Keep the best. "
            "Then try weight_decay: 0.01, 0.05, 0.1, 0.5, 1.0. "
            "Log results to /experiments.jsonl."
        ),
        "config": {"force_model": "qwen2.5-coder-7b"},
    },
    {
        "name": "batch-sweep",
        "prompt": (
            "You are exploring batch size effects. Read /train.py. "
            "Try batch_size: 16, 32, 64, 128, 256. "
            "For each, run and record val_bpb. Keep the best. "
            "Log results to /experiments.jsonl."
        ),
        "config": {"force_model": "qwen2.5-coder-7b"},
    },
    # GPU 1 — Medium model, architecture exploration
    {
        "name": "activation-explorer",
        "prompt": (
            "You are exploring activation functions and norms. Read /train.py. "
            "Try activations: gelu, swiglu, relu. Try norms: rmsnorm, layernorm. "
            "Try position encodings: rope, learned, sinusoidal. "
            "Try one change at a time, keep improvements. "
            "Log results to /experiments.jsonl."
        ),
        "config": {"force_model": "qwen2.5-coder-32b"},
    },
    {
        "name": "width-depth-explorer",
        "prompt": (
            "You are exploring width vs depth tradeoffs. Read /train.py. "
            "Try: 4 layers x 512 dim, 6 layers x 384 dim, 8 layers x 256 dim, "
            "12 layers x 192 dim. Keep n_heads proportional. "
            "Find the best parameter allocation. "
            "Log results to /experiments.jsonl."
        ),
        "config": {"force_model": "qwen2.5-coder-32b"},
    },
    # GPU 2 — Large model, novel architecture research
    {
        "name": "architecture-innovator",
        "prompt": (
            "You are a senior ML researcher. Read /train.py deeply. "
            "Propose novel architecture modifications beyond simple sweeps: "
            "FFN ratio changes (d_ff/d_model), head dimension experiments, "
            "combining the best activation + norm + position encoding. "
            "Think carefully about each change before running it. "
            "Log results to /experiments.jsonl."
        ),
        "config": {"force_model": "deepseek-r1-70b"},
    },
]


async def main(config_path: str):
    db = Kaos("multi-gpu-research.db")
    router = GEPARouter.from_config(config_path)
    ccr = ClaudeCodeRunner(
        db, router,
        max_iterations=20,
        checkpoint_interval=5,
        max_parallel_agents=len(MULTI_GPU_DIRECTIONS),
    )

    print("=" * 60)
    print("Multi-GPU Autonomous Research Lab")
    print("=" * 60)
    print(f"  Agents: {len(MULTI_GPU_DIRECTIONS)}")
    print(f"  GPU 0 (7B):  lr-sweep, dropout-sweep, batch-sweep")
    print(f"  GPU 1 (32B): activation-explorer, width-depth-explorer")
    print(f"  GPU 2 (70B): architecture-innovator")
    print()

    # Seed all agents with the base training script
    for d in MULTI_GPU_DIRECTIONS:
        agent_id = db.spawn(d["name"], config=d.get("config", {}))
        db.write(agent_id, "/train.py", BASE_TRAIN_PY.encode())
        db.write(agent_id, "/experiments.jsonl", b"")
        db.checkpoint(agent_id, label="baseline")
        print(f"  Spawned: {d['name']} → {d.get('config', {}).get('force_model', 'auto')}")

    print(f"\nRunning {len(MULTI_GPU_DIRECTIONS)} agents across 3 GPUs...")
    start = time.time()

    results = await ccr.run_parallel(MULTI_GPU_DIRECTIONS)

    duration = time.time() - start
    print(f"\nAll agents finished in {duration:.1f}s")

    # Cross-GPU analysis
    print("\n" + "=" * 60)
    print("CROSS-GPU RESEARCH RESULTS")
    print("=" * 60)

    # Per-agent summary with model routing
    agent_stats = db.query("""
        SELECT a.name, a.config, a.status,
               COUNT(tc.call_id) as calls,
               COALESCE(SUM(tc.token_count), 0) as tokens
        FROM agents a
        LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
        GROUP BY a.agent_id
        ORDER BY tokens DESC
    """)
    print("\nAgent workload by GPU:")
    for row in agent_stats:
        config = json.loads(row["config"]) if row["config"] else {}
        model = config.get("force_model", "auto")
        gpu = {"qwen2.5-coder-7b": "GPU 0", "qwen2.5-coder-32b": "GPU 1",
               "deepseek-r1-70b": "GPU 2"}.get(model, "auto")
        print(f"  [{gpu}] {row['name']:25s} {row['calls']:>4} calls  {row['tokens']:>8,} tokens  {row['status']}")

    # Total compute
    totals = db.query("""
        SELECT COUNT(*) as calls, COALESCE(SUM(token_count), 0) as tokens,
               COALESCE(SUM(duration_ms), 0) as ms
        FROM tool_calls
    """)
    if totals:
        t = totals[0]
        print(f"\nTotal compute: {t['calls']} calls, {t['tokens']:,} tokens, {t['ms']/1000:.1f}s")

    # Files created
    files = db.query("""
        SELECT a.name, COUNT(f.path) as n_files, MAX(f.version) as max_version
        FROM files f JOIN agents a ON f.agent_id = a.agent_id
        WHERE f.deleted = 0
        GROUP BY a.agent_id
    """)
    print(f"\nFiles per agent:")
    for row in files:
        print(f"  {row['name']:25s} {row['n_files']} files (max v{row['max_version']})")

    db.close()
    print(f"\nAll data in multi-gpu-research.db")
    print(f"  kaos query 'SELECT * FROM agents' --db multi-gpu-research.db")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="kaos.yaml")
    args = parser.parse_args()
    asyncio.run(main(args.config))
