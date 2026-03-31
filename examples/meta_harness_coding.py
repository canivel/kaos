"""
Meta-Harness: Optimize an Agentic Coding Harness
=================================================

Your coding agent solves 60% of tasks. Can Meta-Harness find a better
harness? The paper's key finding: gathering an environment snapshot before
the agent loop (available languages, tools, memory) eliminates 2-4 wasted
exploratory turns and improves pass rate.

The discovered harness was only ~80 lines of additive code on top of the
baseline — no existing code modified. This is the pattern Meta-Harness
converges to after learning from regressions: make purely additive changes.

Usage:
    # With synthetic tasks (for testing):
    uv run python examples/meta_harness_coding.py

    # With real tasks (JSONL with task/language/expected_output):
    uv run python examples/meta_harness_coding.py --tasks coding_tasks.jsonl
"""

from __future__ import annotations

import argparse
import asyncio

from kaos import Kaos
from kaos.metaharness.harness import SearchConfig
from kaos.metaharness.search import MetaHarnessSearch
from kaos.metaharness.benchmarks import get_benchmark
import kaos.metaharness.benchmarks.agentic_coding  # noqa: F401 — register
from kaos.router.gepa import GEPARouter


async def main(tasks_path: str | None):
    db = Kaos("coding-search.db")
    router = GEPARouter.from_config("kaos.yaml")

    kwargs = {}
    if tasks_path:
        kwargs["tasks_path"] = tasks_path

    bench = get_benchmark("agentic_coding", **kwargs)

    config = SearchConfig(
        benchmark="agentic_coding",
        max_iterations=8,
        candidates_per_iteration=2,
        objectives=["+pass_rate"],
        max_parallel_evals=2,
    )

    print("Meta-Harness: Agentic Coding Optimization")
    print(f"  Search set: {len(bench.get_search_set())} tasks")
    print(f"  Seed harnesses: {len(bench.get_seed_harnesses())}")
    print(f"  Objective: pass_rate (maximize)")
    print()

    search = MetaHarnessSearch(db, router, bench, config)
    result = await search.run()

    print("\n" + "=" * 60)
    print(result.summary())
    print("=" * 60)

    # Show the best harness source
    if result.frontier.points:
        best = result.frontier.points[0]
        print(f"\nBest harness: {best.harness_id[:14]}...")
        print(f"  Pass rate: {best.scores.get('pass_rate', 0):.2%}")

        try:
            source = db.read(
                result.search_agent_id,
                f"/harnesses/{best.harness_id}/source.py",
            ).decode()
            print(f"\n--- Source ({len(source)} bytes) ---")
            print(source[:800])
            if len(source) > 800:
                print(f"  ... ({len(source) - 800} more bytes)")
        except FileNotFoundError:
            pass

    # Show search efficiency
    success_count = sum(1 for r in result.all_results if r.is_success)
    fail_count = sum(1 for r in result.all_results if not r.is_success)
    print(f"\nSearch efficiency:")
    print(f"  Evaluated: {result.total_harnesses_evaluated}")
    print(f"  Succeeded: {success_count}")
    print(f"  Failed:    {fail_count}")
    print(f"  Duration:  {result.total_duration_seconds:.1f}s")

    db.close()
    print(f"\nAll data in coding-search.db")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", default=None)
    args = parser.parse_args()
    asyncio.run(main(args.tasks))
