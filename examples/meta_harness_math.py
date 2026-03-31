"""
Meta-Harness: Optimize a Math Retrieval Strategy
=================================================

You have a corpus of solved math problems. When a new problem comes in, which
solved problems should you retrieve to help the LLM? BM25? Dense retrieval?
Domain-specific routing?

Meta-Harness finds out by trying different retrieval harnesses, measuring
accuracy on a search set, and learning from execution traces to propose
better strategies.

The paper found that the discovered harness uses a 4-route BM25 program:
different retrieval strategies per math domain (geometry, combinatorics,
number theory, algebra), with a math-aware tokenizer and adaptive K.

Usage:
    # With synthetic data (for testing):
    uv run python examples/meta_harness_math.py

    # With real data:
    uv run python examples/meta_harness_math.py \
        --problems olympiad_problems.jsonl \
        --corpus solved_problems.jsonl

    # Inspect results:
    kaos mh frontier <search-agent-id> --db math-search.db
"""

from __future__ import annotations

import argparse
import asyncio

from kaos import Kaos
from kaos.metaharness.harness import SearchConfig
from kaos.metaharness.search import MetaHarnessSearch
from kaos.metaharness.benchmarks import get_benchmark
import kaos.metaharness.benchmarks.math_rag  # noqa: F401 — register
from kaos.router.gepa import GEPARouter


async def main(problems_path: str | None, corpus_path: str | None):
    db = Kaos("math-search.db")
    router = GEPARouter.from_config("kaos.yaml")

    kwargs = {}
    if problems_path:
        kwargs["problems_path"] = problems_path
    if corpus_path:
        kwargs["corpus_path"] = corpus_path

    bench = get_benchmark("math_rag", **kwargs)

    config = SearchConfig(
        benchmark="math_rag",
        max_iterations=10,
        candidates_per_iteration=2,
        objectives=["+accuracy", "-context_cost"],
        max_parallel_evals=2,
    )

    print("Meta-Harness: Math Retrieval Optimization")
    print(f"  Search set: {len(bench.get_search_set())} problems")
    print(f"  Seed harnesses: {len(bench.get_seed_harnesses())}")
    print(f"  Objectives: accuracy (maximize), context_cost (minimize)")
    print()

    search = MetaHarnessSearch(db, router, bench, config)
    result = await search.run()

    print("\n" + "=" * 60)
    print(result.summary())
    print("=" * 60)

    print("\nPareto Frontier:")
    for point in result.frontier.points:
        scores = ", ".join(f"{k}={v:.4f}" for k, v in point.scores.items())
        print(f"  {point.harness_id[:12]}... (iter {point.iteration}): {scores}")

    # What retrieval strategies were tried?
    agents = db.query("""
        SELECT a.name, a.status, COUNT(tc.call_id) as calls,
               COALESCE(SUM(tc.token_count), 0) as tokens
        FROM agents a
        LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
        GROUP BY a.agent_id ORDER BY tokens DESC
    """)
    print(f"\nAll agents ({len(agents)} total):")
    for a in agents[:15]:
        print(f"  {a['name']:35s} {a['status']:12s} {a['tokens']:>8,} tokens")

    db.close()
    print(f"\nAll data in math-search.db")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--problems", default=None)
    parser.add_argument("--corpus", default=None)
    args = parser.parse_args()
    asyncio.run(main(args.problems, args.corpus))
