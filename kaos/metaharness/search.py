"""Meta-Harness search loop — the core orchestrator.

Implements Algorithm 1 from the Meta-Harness paper (arXiv:2603.28052):
  1. Initialize seed population and filesystem D
  2. Evaluate seeds
  3. For N iterations:
     a. Proposer inspects D, proposes k new harnesses
     b. Validate each harness interface (AST check)
     c. Evaluate valid harnesses (parallel, each gets a KAOS agent)
     d. Store results (code + scores + traces) in D
  4. Return Pareto frontier
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import asdict
from typing import TYPE_CHECKING

from kaos.metaharness.evaluator import HarnessEvaluator
from kaos.metaharness.harness import HarnessCandidate, EvaluationResult, SearchConfig
from kaos.metaharness.pareto import compute_pareto, ParetoFrontier
from kaos.metaharness.prompts import build_pivot_prompt
from kaos.metaharness.proposer import ProposerAgent

if TYPE_CHECKING:
    from kaos.core import Kaos
    from kaos.metaharness.benchmarks.base import Benchmark
    from kaos.router.gepa import GEPARouter

logger = logging.getLogger(__name__)


class MetaHarnessSearch:
    """Orchestrates the meta-harness search loop.

    Uses KAOS agents for isolation:
    - A "search" agent owns the shared archive (filesystem D)
    - Each harness evaluation gets its own agent
    - The proposer agent reads the archive via cross-agent tools
    """

    def __init__(
        self,
        afs: Kaos,
        router: GEPARouter,
        benchmark: Benchmark,
        config: SearchConfig,
    ):
        self.afs = afs
        self.router = router
        self.benchmark = benchmark
        self.config = config

        # Inherit objectives from benchmark if not explicitly set
        if config.objectives is None:
            config.objectives = benchmark.objectives

        self.evaluator = HarnessEvaluator(
            afs, router, benchmark,
            timeout_seconds=config.harness_timeout_seconds,
        )
        self.search_agent_id: str | None = None
        self._all_results: list[EvaluationResult] = []
        self._iterations_map: dict[str, int] = {}  # harness_id → iteration

    async def run(self) -> SearchResult:
        """Execute the full meta-harness search loop.

        Returns a SearchResult with the final Pareto frontier, all evaluated
        harnesses, and aggregate statistics.
        """
        start_time = time.time()

        # Step 1: Initialize the search agent and archive filesystem
        self.search_agent_id = self._init_archive()

        # Step 2: Evaluate seed harnesses
        seeds = self._load_seeds()
        logger.info("Evaluating %d seed harnesses...", len(seeds))
        seed_results = await self.evaluator.evaluate_parallel(
            seeds,
            max_parallel=self.config.max_parallel_evals,
        )
        for harness, result in zip(seeds, seed_results):
            self._store_result(harness, result, iteration=0)

        # Compute initial frontier
        frontier = self._compute_frontier()
        self._store_frontier(frontier, iteration=0)
        logger.info(
            "Seed evaluation complete. Frontier: %d points",
            len(frontier.points),
        )

        # Step 3: Main search loop
        proposer = ProposerAgent(
            self.afs, self.router,
            search_agent_id=self.search_agent_id,
            proposer_model=self.config.proposer_model,
        )

        for iteration in range(1, self.config.max_iterations + 1):
            iter_start = time.time()
            logger.info("=== Iteration %d / %d ===", iteration, self.config.max_iterations)

            # Checkpoint the search state
            self.afs.checkpoint(
                self.search_agent_id,
                label=f"pre-iter-{iteration}",
            )

            # 3a. Proposer inspects archive and proposes candidates
            stagnant = self.afs.get_state_or(self.search_agent_id, "stagnant_iterations") or 0
            try:
                candidates = await asyncio.wait_for(
                    proposer.propose(
                        iteration=iteration,
                        n_candidates=self.config.candidates_per_iteration,
                        benchmark_name=self.benchmark.name,
                        frontier=frontier,
                        compaction_level=self.config.compaction_level,
                        stagnant_iterations=stagnant,
                        stagnation_threshold=self.config.stagnation_threshold,
                    ),
                    timeout=self.config.proposer_timeout_seconds,
                )
            except asyncio.TimeoutError:
                logger.error(
                    "Iteration %d: proposer timed out after %ds, skipping",
                    iteration, self.config.proposer_timeout_seconds,
                )
                self._store_iteration_error(iteration, "proposer_timeout")
                continue
            except Exception as e:
                logger.error(
                    "Iteration %d: proposer failed: %s, skipping",
                    iteration, e,
                )
                self._store_iteration_error(iteration, str(e))
                continue

            if not candidates:
                logger.warning("Iteration %d: no candidates proposed, skipping", iteration)
                continue

            # 3b. Interface validation (already done in proposer._submit_harness)
            valid_candidates = []
            for c in candidates:
                ok, err = c.validate_interface()
                if ok:
                    valid_candidates.append(c)
                else:
                    logger.warning(
                        "Harness %s failed validation: %s",
                        c.harness_id[:12], err,
                    )

            if not valid_candidates:
                logger.warning("Iteration %d: no valid candidates after validation", iteration)
                continue

            # 3c. Evaluate valid harnesses in parallel
            problems = self.benchmark.get_search_set()
            if self.config.eval_subset_size:
                problems = self.benchmark.get_subset(problems, self.config.eval_subset_size)

            try:
                results = await self.evaluator.evaluate_parallel(
                    valid_candidates,
                    problems=problems,
                    max_parallel=self.config.max_parallel_evals,
                )
            except Exception as e:
                logger.error("Iteration %d: evaluation failed: %s", iteration, e)
                self._store_iteration_error(iteration, f"eval_error: {e}")
                continue

            # 3d. Store results in archive
            for harness, result in zip(valid_candidates, results):
                self._store_result(harness, result, iteration=iteration)

            # Update frontier + stagnation tracking (CORAL Tier 1)
            frontier = self._compute_frontier()
            self._store_frontier(frontier, iteration=iteration)
            stagnant = self._update_stagnation(frontier, iteration)

            # Store iteration metadata
            self.afs.write(
                self.search_agent_id,
                f"/iterations/{iteration}/proposed.json",
                json.dumps({
                    "harness_ids": [c.harness_id for c in candidates],
                    "valid_ids": [c.harness_id for c in valid_candidates],
                    "results": [
                        {
                            "harness_id": r.harness_id,
                            "scores": r.scores,
                            "is_success": r.is_success,
                            "error": r.error,
                        }
                        for r in results
                    ],
                }, indent=2).encode(),
            )

            iter_duration = time.time() - iter_start
            logger.info(
                "Iteration %d complete: %d evaluated, frontier=%d, %.1fs",
                iteration, len(results), len(frontier.points), iter_duration,
            )

            # Update search state
            self.afs.set_state(self.search_agent_id, "current_iteration", iteration)
            self.afs.set_state(
                self.search_agent_id, "frontier",
                frontier.to_dict(),
            )

        # Step 4: File discoveries to persistent knowledge agent
        self._file_to_knowledge(frontier)

        # Step 5: Final results
        total_duration = time.time() - start_time
        self.afs.complete(self.search_agent_id)

        return SearchResult(
            search_agent_id=self.search_agent_id,
            frontier=frontier,
            all_results=self._all_results,
            total_harnesses_evaluated=len(self._all_results),
            total_duration_seconds=total_duration,
            iterations_completed=self.config.max_iterations,
        )

    async def run_seeds_only(self) -> SearchResult:
        """Evaluate seed harnesses only — no proposer iterations (dry-run mode)."""
        start_time = time.time()
        self.search_agent_id = self._init_archive()

        seeds = self._load_seeds()
        logger.info("Dry-run: evaluating %d seed harnesses...", len(seeds))

        problems = self.benchmark.get_search_set()
        if self.config.eval_subset_size:
            problems = self.benchmark.get_subset(problems, self.config.eval_subset_size)

        seed_results = await self.evaluator.evaluate_parallel(
            seeds, problems=problems,
            max_parallel=self.config.max_parallel_evals,
        )
        for harness, result in zip(seeds, seed_results):
            self._store_result(harness, result, iteration=0)

        frontier = self._compute_frontier()
        self._store_frontier(frontier, iteration=0)

        total_duration = time.time() - start_time
        self.afs.complete(self.search_agent_id)

        return SearchResult(
            search_agent_id=self.search_agent_id,
            frontier=frontier,
            all_results=self._all_results,
            total_harnesses_evaluated=len(self._all_results),
            total_duration_seconds=total_duration,
            iterations_completed=0,
        )

    async def resume(self, search_agent_id: str) -> SearchResult:
        """Resume an interrupted Meta-Harness search.

        Restores the search state from the archive and continues from
        the last completed iteration.
        """
        self.search_agent_id = search_agent_id
        start_time = time.time()

        # Restore config from archive
        config_data = json.loads(
            self.afs.read(search_agent_id, "/config.json").decode()
        )
        self.config = SearchConfig.from_dict(config_data)

        # Restore iteration counter
        last_iteration = self.afs.get_state(search_agent_id, "current_iteration") or 0
        logger.info("Resuming search from iteration %d", last_iteration)

        # Restore all prior results from archive
        self._all_results = []
        self._iterations_map = {}
        harness_dirs = self.afs.ls(search_agent_id, "/harnesses")
        for entry in harness_dirs:
            hid = entry.get("name", "")
            if not hid:
                continue
            try:
                scores_data = json.loads(
                    self.afs.read(search_agent_id, f"/harnesses/{hid}/scores.json").decode()
                )
                meta_data = json.loads(
                    self.afs.read(search_agent_id, f"/harnesses/{hid}/metadata.json").decode()
                )
                result = EvaluationResult(
                    harness_id=hid,
                    scores=scores_data,
                    duration_ms=meta_data.get("duration_ms", 0),
                    error=meta_data.get("error"),
                )
                self._all_results.append(result)
                self._iterations_map[hid] = meta_data.get("iteration", 0)
            except (FileNotFoundError, json.JSONDecodeError):
                continue

        frontier = self._compute_frontier()
        logger.info(
            "Restored %d prior results, frontier=%d, resuming from iteration %d",
            len(self._all_results), len(frontier.points), last_iteration + 1,
        )

        # Set agent back to running
        self.afs.set_status(search_agent_id, "running")

        # Continue the search loop from last_iteration + 1
        proposer = ProposerAgent(
            self.afs, self.router,
            search_agent_id=self.search_agent_id,
            proposer_model=self.config.proposer_model,
        )

        for iteration in range(last_iteration + 1, self.config.max_iterations + 1):
            iter_start = time.time()
            logger.info("=== Iteration %d / %d (resumed) ===", iteration, self.config.max_iterations)

            self.afs.checkpoint(search_agent_id, label=f"pre-iter-{iteration}")

            stagnant_r = self.afs.get_state_or(search_agent_id, "stagnant_iterations") or 0
            try:
                candidates = await asyncio.wait_for(
                    proposer.propose(
                        iteration=iteration,
                        n_candidates=self.config.candidates_per_iteration,
                        benchmark_name=self.benchmark.name,
                        frontier=frontier,
                        compaction_level=self.config.compaction_level,
                        stagnant_iterations=stagnant_r,
                        stagnation_threshold=self.config.stagnation_threshold,
                    ),
                    timeout=self.config.proposer_timeout_seconds,
                )
            except (asyncio.TimeoutError, Exception) as e:
                logger.error("Iteration %d: proposer failed: %s, skipping", iteration, e)
                self._store_iteration_error(iteration, str(e))
                continue

            if not candidates:
                continue

            valid_candidates = [c for c in candidates if c.validate_interface()[0]]
            if not valid_candidates:
                continue

            problems = self.benchmark.get_search_set()
            if self.config.eval_subset_size:
                problems = self.benchmark.get_subset(problems, self.config.eval_subset_size)

            try:
                results = await self.evaluator.evaluate_parallel(
                    valid_candidates, problems=problems,
                    max_parallel=self.config.max_parallel_evals,
                )
            except Exception as e:
                logger.error("Iteration %d: evaluation failed: %s", iteration, e)
                self._store_iteration_error(iteration, f"eval_error: {e}")
                continue

            for harness, result in zip(valid_candidates, results):
                self._store_result(harness, result, iteration=iteration)

            frontier = self._compute_frontier()
            self._store_frontier(frontier, iteration=iteration)
            self._update_stagnation(frontier, iteration)

            self.afs.set_state(search_agent_id, "current_iteration", iteration)
            self.afs.set_state(search_agent_id, "frontier", frontier.to_dict())

            iter_duration = time.time() - iter_start
            logger.info(
                "Iteration %d complete: %d evaluated, frontier=%d, %.1fs",
                iteration, len(results), len(frontier.points), iter_duration,
            )

        total_duration = time.time() - start_time
        self.afs.complete(search_agent_id)

        return SearchResult(
            search_agent_id=search_agent_id,
            frontier=frontier,
            all_results=self._all_results,
            total_harnesses_evaluated=len(self._all_results),
            total_duration_seconds=total_duration,
            iterations_completed=self.config.max_iterations,
        )

    def _update_stagnation(self, frontier: ParetoFrontier, iteration: int) -> int:
        """CORAL Tier 1: track consecutive non-improving iterations.

        Returns the current stagnant_iterations count (after update).
        Writes stagnant_iterations and prev_best_scores to VFS state.
        """
        prev_best: dict = self.afs.get_state_or(self.search_agent_id, "prev_best_scores") or {}
        stagnant: int = self.afs.get_state_or(self.search_agent_id, "stagnant_iterations") or 0

        curr_best: dict[str, float] = {}
        for obj in self.config.objective_directions():
            vals = [p.scores.get(obj, 0.0) for p in frontier.points]
            curr_best[obj] = max(vals) if vals else 0.0

        epsilon = 0.001
        improved = any(
            abs(curr_best.get(obj, 0.0) - prev_best.get(obj, 0.0)) > epsilon
            for obj in curr_best
        ) or (len(frontier.points) > (self.afs.get_state_or(self.search_agent_id, "prev_frontier_size") or 0))

        stagnant = 0 if improved else stagnant + 1
        self.afs.set_state(self.search_agent_id, "stagnant_iterations", stagnant)
        self.afs.set_state(self.search_agent_id, "prev_best_scores", curr_best)
        self.afs.set_state(self.search_agent_id, "prev_frontier_size", len(frontier.points))

        if stagnant >= self.config.stagnation_threshold:
            logger.warning(
                "Iteration %d: frontier stagnant for %d iterations — pivot prompt active",
                iteration, stagnant,
            )
        return stagnant

    def _init_archive(self) -> str:
        """Create the search agent and initialize the archive filesystem."""
        agent_id = self.afs.spawn(
            "meta-harness-search",
            config={"search_config": self.config.to_dict()},
        )
        self.afs.set_status(agent_id, "running")

        # Write config
        self.afs.write(
            agent_id,
            "/config.json",
            json.dumps(self.config.to_dict(), indent=2).encode(),
        )

        # Write seed harnesses
        seed_sources = self.benchmark.get_seed_harnesses()
        for i, source in enumerate(seed_sources):
            self.afs.write(
                agent_id,
                f"/seeds/seed_{i}.py",
                source.encode(),
            )

        # Initialize directories
        self.afs.mkdir(agent_id, "/harnesses")
        self.afs.mkdir(agent_id, "/iterations")
        self.afs.mkdir(agent_id, "/pareto")
        # CORAL Tier 2: three-tier memory
        self.afs.mkdir(agent_id, "/attempts")   # compact per-eval summaries
        self.afs.mkdir(agent_id, "/notes")      # proposer scratch space
        self.afs.mkdir(agent_id, "/skills")     # reusable patterns (persisted)

        # Pre-load skills from knowledge agent for this benchmark
        self._load_skills_from_knowledge(agent_id)

        logger.info("Search archive initialized: agent %s", agent_id[:12])
        return agent_id

    def _store_iteration_error(self, iteration: int, error: str) -> None:
        """Record that an iteration failed so it's visible in the archive."""
        self.afs.write(
            self.search_agent_id,
            f"/iterations/{iteration}/error.json",
            json.dumps({"iteration": iteration, "error": error}).encode(),
        )
        self.afs.set_state(self.search_agent_id, "current_iteration", iteration)

    def _load_seeds(self) -> list[HarnessCandidate]:
        """Load seed harnesses from config, benchmark defaults, and prior discoveries."""
        seeds = []

        # From config (file paths)
        for path in self.config.seed_harnesses:
            with open(path) as f:
                source = f.read()
            seeds.append(HarnessCandidate.create(
                source_code=source,
                metadata={"source": "seed_file", "path": path},
            ))

        # From prior searches (knowledge agent) — capped to avoid digest bloat
        priors = self._load_prior_discoveries()
        max_priors = self.config.max_prior_seeds
        if len(priors) > max_priors:
            logger.info(
                "Capping prior discoveries from %d to %d (max_prior_seeds)",
                len(priors), max_priors,
            )
            priors = priors[:max_priors]
        seeds.extend(priors)

        # From benchmark defaults (skip if we already have prior discoveries)
        if not priors:
            for source in self.benchmark.get_seed_harnesses():
                seeds.append(HarnessCandidate.create(
                    source_code=source,
                    metadata={"source": "benchmark_seed"},
                ))
        else:
            logger.info("Using %d prior discoveries instead of default seeds", len(priors))

        return seeds

    def _load_skills_from_knowledge(self, agent_id: str) -> None:
        """CORAL Tier 2: seed /skills/ from knowledge agent's prior discoveries."""
        try:
            knowledge_id = self.afs.get_or_create_singleton("kaos-knowledge")
            benchmark = self.config.benchmark
            skill_dir = f"/skills/{benchmark}"
            entries = self.afs.ls(knowledge_id, skill_dir)
            count = 0
            for entry in entries:
                if entry.get("is_dir") or not entry["path"].endswith(".json"):
                    continue
                try:
                    skill_data = self.afs.read(knowledge_id, entry["path"])
                    self.afs.write(agent_id, f"/skills/{entry['name']}", skill_data)
                    count += 1
                except Exception:
                    continue
            if count:
                logger.info("Loaded %d skills from knowledge agent for %s", count, benchmark)
        except Exception:
            pass

    def _store_result(
        self,
        harness: HarnessCandidate,
        result: EvaluationResult,
        iteration: int,
    ) -> None:
        """Store a harness evaluation result in the archive."""
        self._all_results.append(result)
        self._iterations_map[harness.harness_id] = iteration
        harness.iteration = iteration

        hid = harness.harness_id
        base = f"/harnesses/{hid}"

        self.afs.write(
            self.search_agent_id,
            f"{base}/source.py",
            harness.source_code.encode(),
        )
        self.afs.write(
            self.search_agent_id,
            f"{base}/scores.json",
            result.to_scores_json().encode(),
        )
        self.afs.write(
            self.search_agent_id,
            f"{base}/trace.jsonl",
            result.to_trace_jsonl().encode(),
        )
        # Per-problem results (separate from trace for easier proposer navigation)
        if result.per_problem:
            self.afs.write(
                self.search_agent_id,
                f"{base}/per_problem.jsonl",
                "\n".join(json.dumps(p) for p in result.per_problem).encode(),
            )
        self.afs.write(
            self.search_agent_id,
            f"{base}/metadata.json",
            json.dumps({
                "harness_id": hid,
                "parent_ids": harness.parent_ids,
                "iteration": iteration,
                "metadata": harness.metadata,
                "is_success": result.is_success,
                "error": result.error,
                "duration_ms": result.duration_ms,
            }, indent=2).encode(),
        )
        # CORAL Tier 2: compact summary in /attempts/ for fast proposer scanning
        self.afs.write(
            self.search_agent_id,
            f"/attempts/{hid}.json",
            json.dumps({
                "harness_id": hid,
                "iteration": iteration,
                "scores": result.scores,
                "is_success": result.is_success,
                "error": result.error,
                "approach": harness.source_code[:200],
                "rationale": harness.metadata.get("rationale", ""),
            }, indent=2).encode(),
        )

    def _compute_frontier(self) -> ParetoFrontier:
        """Compute the current Pareto frontier from all results."""
        objectives = self.config.objective_directions()
        return compute_pareto(
            self._all_results,
            objectives,
            iterations=self._iterations_map,
        )

    def _store_frontier(self, frontier: ParetoFrontier, iteration: int) -> None:
        """Store the current frontier in the archive."""
        self.afs.write(
            self.search_agent_id,
            "/pareto/frontier.json",
            json.dumps(frontier.to_dict(), indent=2).encode(),
        )

        # Append to history
        try:
            history = self.afs.read(self.search_agent_id, "/pareto/history.jsonl")
            history_text = history.decode() + "\n"
        except FileNotFoundError:
            history_text = ""

        history_text += json.dumps({
            "iteration": iteration,
            "frontier_size": len(frontier.points),
            "points": [
                {"harness_id": p.harness_id[:12], "scores": p.scores}
                for p in frontier.points
            ],
        })
        self.afs.write(
            self.search_agent_id,
            "/pareto/history.jsonl",
            history_text.encode(),
        )

    def _file_to_knowledge(self, frontier: ParetoFrontier) -> None:
        """File winning harnesses and insights to the persistent knowledge agent."""
        try:
            knowledge_id = self.afs.get_or_create_singleton("kaos-knowledge")
            benchmark = self.config.benchmark

            # Store frontier
            self.afs.write(
                knowledge_id,
                f"/discoveries/{benchmark}/frontier.json",
                json.dumps(frontier.to_dict(), indent=2).encode(),
            )

            # Store winning harness source code
            for point in frontier.points:
                try:
                    source = self.afs.read(
                        self.search_agent_id,
                        f"/harnesses/{point.harness_id}/source.py",
                    )
                    self.afs.write(
                        knowledge_id,
                        f"/discoveries/{benchmark}/harnesses/{point.harness_id[:12]}.py",
                        source,
                    )
                except FileNotFoundError:
                    pass

            # Store search summary
            summary = {
                "search_agent_id": self.search_agent_id,
                "benchmark": benchmark,
                "frontier_size": len(frontier.points),
                "best_scores": {
                    obj: max(
                        (p.scores.get(obj, 0) for p in frontier.points),
                        default=0,
                    )
                    for obj in self.config.objective_directions()
                },
                "iterations": self.config.max_iterations,
                "harnesses_evaluated": len(self._all_results),
            }
            self.afs.write(
                knowledge_id,
                f"/discoveries/{benchmark}/latest_search.json",
                json.dumps(summary, indent=2).encode(),
            )

            # CORAL Tier 2: persist skills discovered during this search
            try:
                skill_entries = self.afs.ls(self.search_agent_id, "/skills")
                for entry in skill_entries:
                    if entry.get("is_dir") or not entry["path"].endswith(".json"):
                        continue
                    try:
                        skill_data = self.afs.read(self.search_agent_id, entry["path"])
                        self.afs.write(
                            knowledge_id,
                            f"/skills/{benchmark}/{entry['name']}",
                            skill_data,
                        )
                    except Exception:
                        continue
            except Exception:
                pass

            logger.info("Filed discoveries to knowledge agent %s", knowledge_id[:12])
        except Exception as e:
            logger.warning("Failed to file discoveries to knowledge: %s", e)

    def _load_prior_discoveries(self) -> list[HarnessCandidate]:
        """Load winning harnesses from prior searches via the knowledge agent."""
        priors = []
        try:
            knowledge_id = self.afs.get_or_create_singleton("kaos-knowledge")
            benchmark = self.config.benchmark
            harness_dir = f"/discoveries/{benchmark}/harnesses"

            entries = self.afs.ls(knowledge_id, harness_dir)
            for entry in entries:
                if entry.get("is_dir") or not entry["path"].endswith(".py"):
                    continue
                try:
                    source = self.afs.read(knowledge_id, entry["path"]).decode()
                    priors.append(HarnessCandidate.create(
                        source_code=source,
                        metadata={"source": "prior_discovery", "path": entry["path"]},
                    ))
                except Exception:
                    continue

            if priors:
                logger.info(
                    "Loaded %d prior discoveries for %s from knowledge base",
                    len(priors), benchmark,
                )
        except Exception:
            pass
        return priors


class SearchResult:
    """Result of a complete meta-harness search run."""

    def __init__(
        self,
        search_agent_id: str,
        frontier: ParetoFrontier,
        all_results: list[EvaluationResult],
        total_harnesses_evaluated: int,
        total_duration_seconds: float,
        iterations_completed: int,
    ):
        self.search_agent_id = search_agent_id
        self.frontier = frontier
        self.all_results = all_results
        self.total_harnesses_evaluated = total_harnesses_evaluated
        self.total_duration_seconds = total_duration_seconds
        self.iterations_completed = iterations_completed

    def summary(self) -> str:
        """Human-readable summary of the search."""
        lines = [
            f"Meta-Harness Search Complete",
            f"  Search agent: {self.search_agent_id[:14]}...",
            f"  Iterations: {self.iterations_completed}",
            f"  Harnesses evaluated: {self.total_harnesses_evaluated}",
            f"  Duration: {self.total_duration_seconds:.1f}s",
            f"  Frontier size: {len(self.frontier.points)}",
        ]
        if self.frontier.points:
            best = self.frontier.best_by_objective
            for obj, point in best.items():
                lines.append(
                    f"  Best {obj}: {point.scores.get(obj, 0):.4f} "
                    f"(harness {point.harness_id[:12]}...)"
                )
        return "\n".join(lines)
