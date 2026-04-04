"""Detached worker process for meta-harness search.

Runs as a separate process so the MCP server / CLI parent can exit
without killing the search. Progress is written to the KAOS DB and
can be polled via `kaos mh status <search_agent_id>`.

Usage:
    python -m kaos.metaharness.worker \
        --db kaos.db --config-file kaos.yaml \
        --benchmark text_classify --iterations 5
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description="KAOS Meta-Harness search worker")
    parser.add_argument("--db", default="./kaos.db", help="Database file path")
    parser.add_argument("--config-file", required=True, help="Config YAML path")
    parser.add_argument("--benchmark", required=True, help="Benchmark name")
    parser.add_argument("--iterations", type=int, default=20)
    parser.add_argument("--candidates", type=int, default=2)
    parser.add_argument("--max-parallel", type=int, default=4)
    parser.add_argument("--eval-subset", type=int, default=None)
    parser.add_argument("--proposer-model", default=None)
    parser.add_argument("--seed", action="append", default=[])
    parser.add_argument("--search-agent-id", default=None,
                        help="Resume an existing search agent instead of creating new")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("kaos.worker")

    from kaos.core import Kaos
    from kaos.router.gepa import GEPARouter
    from kaos.metaharness.search import MetaHarnessSearch
    from kaos.metaharness.harness import SearchConfig
    from kaos.metaharness.benchmarks import get_benchmark
    import kaos.metaharness.benchmarks.text_classify  # noqa: F401
    import kaos.metaharness.benchmarks.math_rag  # noqa: F401
    import kaos.metaharness.benchmarks.agentic_coding  # noqa: F401
    try:
        import kaos.metaharness.benchmarks.arc_agi3  # noqa: F401
    except ImportError:
        pass

    afs = Kaos(db_path=args.db)
    router = GEPARouter.from_config(args.config_file)
    bench = get_benchmark(args.benchmark)

    config = SearchConfig(
        benchmark=args.benchmark,
        max_iterations=args.iterations,
        candidates_per_iteration=args.candidates,
        seed_harnesses=args.seed,
        proposer_model=args.proposer_model,
        max_parallel_evals=args.max_parallel,
        eval_subset_size=args.eval_subset,
    )

    search = MetaHarnessSearch(afs, router, bench, config)

    try:
        if args.search_agent_id:
            logger.info("Resuming search %s", args.search_agent_id)
            result = asyncio.run(search.resume(args.search_agent_id))
        else:
            logger.info("Starting new search: benchmark=%s iters=%d", args.benchmark, args.iterations)
            result = asyncio.run(search.run())

        logger.info("Search complete: %s", result.summary())
    except Exception as e:
        logger.exception("Worker failed: %s", e)
        if search.search_agent_id:
            try:
                afs.fail(search.search_agent_id, error=str(e))
            except Exception:
                pass
        sys.exit(1)
    finally:
        afs.close()


if __name__ == "__main__":
    main()
