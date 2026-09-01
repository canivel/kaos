"""WMP probe runner — executes the frozen 18-search grid, then the verdict.

Usage (from the repo root):
  uv run python -m demo_wmp_bench.run --smoke          # pipeline shakeout (not counted)
  uv run python -m demo_wmp_bench.run --all            # the 18 pre-registered searches
  uv run python -m demo_wmp_bench.run --verdict        # aggregate + self-test + verdict

Each search runs in its own directory under demo_wmp_bench/runs/ with a fresh
kaos.db (no skills/memory carryover between arms) and writes result.json on
completion — the grid is resumable; completed cells are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))

from demo_wmp_bench import wiki as wmp_wiki                     # noqa: E402
from demo_wmp_bench.gates import (                              # noqa: E402
    ARMS, BENCHMARKS, RUNS_PER_CELL, WMPStats, compute_gates, falsify, load,
)
from demo_wmp_bench.wiki import WMPContext, WMPProposer         # noqa: E402
from kaos.eval.harness.verdict import compute_verdict           # noqa: E402

CONFIG = str(HERE / "probe.kaos.yaml")
RUNS_DIR = HERE / "runs"

# Frozen by the lock (workload_invariants.search_budget_frozen)
ITERATIONS = 3
CANDIDATES = 2
EVAL_SUBSET = 10
MAX_PARALLEL = 2


def _search_once(arm: str, benchmark: str, out_dir: Path,
                 *, iterations: int = ITERATIONS,
                 eval_subset: int = EVAL_SUBSET) -> dict:
    """One search, one fresh workspace, ProposerAgent swapped per arm."""
    import kaos.metaharness.benchmarks.math_rag        # noqa: F401
    import kaos.metaharness.benchmarks.text_classify   # noqa: F401
    from kaos.core import Kaos
    from kaos.metaharness import search as search_mod
    from kaos.metaharness.benchmarks import get_benchmark
    from kaos.metaharness.harness import SearchConfig
    from kaos.router.gepa import GEPARouter

    out_dir.mkdir(parents=True, exist_ok=True)
    afs = Kaos(db_path=str(out_dir / "kaos.db"))
    router = GEPARouter.from_config(CONFIG)
    bench = get_benchmark(benchmark)
    config = SearchConfig(
        benchmark=benchmark,
        max_iterations=iterations,
        candidates_per_iteration=CANDIDATES,
        max_parallel_evals=MAX_PARALLEL,
        eval_subset_size=eval_subset,
    )

    ctx = WMPContext(arm)
    wmp_wiki.CTX = ctx
    original = search_mod.ProposerAgent
    search_mod.ProposerAgent = WMPProposer          # all arms: char accounting
    t0 = time.time()
    try:
        search = search_mod.MetaHarnessSearch(afs, router, bench, config)
        result = asyncio.run(search.run())
    finally:
        search_mod.ProposerAgent = original
        wmp_wiki.CTX = None
        afs.close()

    best = 0.0
    try:
        point = result.frontier.best_by_objective.get("accuracy")
        if point:
            best = float(point.scores.get("accuracy", 0.0))
    except Exception:
        pass
    if not best and result.all_results:
        best = max(float(r.scores.get("accuracy", 0.0))
                   for r in result.all_results)

    row = {
        "arm": arm, "benchmark": benchmark,
        "best_accuracy": best,
        "iterations_completed": result.iterations_completed,
        "harnesses_evaluated": result.total_harnesses_evaluated,
        "duration_s": round(time.time() - t0, 1),
        "wmp": ctx.to_dict(),
    }
    (out_dir / "result.json").write_text(json.dumps(row, indent=2))
    return row


def run_grid() -> None:
    cells = [(arm, bm, i)
             for bm in BENCHMARKS for arm in ARMS
             for i in range(RUNS_PER_CELL)]
    for arm, bm, i in cells:
        out = RUNS_DIR / f"{arm}-{bm}-{i}"
        if (out / "result.json").exists():
            print(f"[skip] {out.name} (done)")
            continue
        print(f"[run ] {out.name} ...", flush=True)
        try:
            row = _search_once(arm, bm, out)
            print(f"[done] {out.name}: best={row['best_accuracy']:.3f} "
                  f"in {row['duration_s']}s", flush=True)
        except Exception as e:  # noqa: BLE001 — a crashed cell is a G0 fact
            print(f"[FAIL] {out.name}: {e}", flush=True)
            (out / "error.txt").write_text(str(e))


def collect() -> WMPStats:
    stats = WMPStats(accuracy={a: {b: [] for b in BENCHMARKS} for a in ARMS},
                     chars={a: [] for a in ARMS})
    for p in sorted(RUNS_DIR.glob("*/result.json")):
        row = json.loads(p.read_text())
        if row["arm"] in ARMS and row["benchmark"] in BENCHMARKS:
            stats.accuracy[row["arm"]][row["benchmark"]].append(row["best_accuracy"])
            stats.chars[row["arm"]].extend(row["wmp"]["iter_chars"])
    return stats


def verdict() -> int:
    lock = load()
    stats = collect()
    can_kill, self_test = falsify(stats)
    outcomes = compute_gates(stats)
    v = ("VOID: harness cannot kill (falsification self-test failed)"
         if not can_kill else compute_verdict(outcomes, judge_kappa=None))
    results = {
        "lock_name": lock["name"],
        "self_test_passed": can_kill, "self_test_detail": self_test,
        "cells": {f"{a}/{b}": stats.cell(a, b)
                  for a in ARMS for b in BENCHMARKS},
        "means": {f"{a}/{b}": round(stats.arm_mean(a, b), 4)
                  for a in ARMS for b in BENCHMARKS},
        "gates": [g.__dict__ for g in outcomes],
        "judge_kappa": None,
        "verdict": v,
    }
    (HERE / "results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    return 0 if v == "ACCEPT" else 1


def smoke() -> None:
    """Tiny uncounted pipeline shakeout: 1 iteration, 6 problems, FULL arm
    (exercises maintainer + injection + char ledger end to end)."""
    out = HERE / "smoke" / f"smoke-{int(time.time())}"
    row = _search_once("FULL", "text_classify", out,
                       iterations=1, eval_subset=6)
    print(json.dumps(row, indent=2))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--verdict", action="store_true")
    args = ap.parse_args()
    if args.smoke:
        smoke()
    elif args.all:
        run_grid()
    elif args.verdict:
        raise SystemExit(verdict())
    else:
        ap.print_help()
