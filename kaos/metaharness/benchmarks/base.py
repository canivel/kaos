"""Abstract benchmark interface for meta-harness evaluation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass
class Problem:
    """A single benchmark problem."""

    problem_id: str
    input: dict[str, Any]
    expected: Any  # Ground truth for scoring
    metadata: dict[str, Any] | None = None


class Benchmark(ABC):
    """Base class for meta-harness benchmarks.

    A benchmark provides:
    - A set of problems for evaluation
    - Seed harnesses to initialize the search
    - A scoring function for harness outputs
    - Objective definitions for Pareto optimization
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Benchmark identifier."""

    @property
    @abstractmethod
    def objectives(self) -> list[str]:
        """Objective definitions, e.g. ['+accuracy', '-context_cost']."""

    @abstractmethod
    def get_search_set(self) -> list[Problem]:
        """Return problems used during search (harnesses are optimized on these)."""

    @abstractmethod
    def get_test_set(self) -> list[Problem]:
        """Return held-out problems for final evaluation."""

    @abstractmethod
    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        """Score a harness's output on a single problem.

        Returns a dict matching the objective names, e.g.:
            {"accuracy": 1.0, "context_cost": 1234}
        """

    @abstractmethod
    def get_seed_harnesses(self) -> list[str]:
        """Return source code strings for seed harnesses."""

    def aggregate_scores(self, per_problem: list[dict[str, float]]) -> dict[str, float]:
        """Aggregate per-problem scores into overall scores.

        Default: mean of each objective. Override for custom aggregation.
        """
        if not per_problem:
            return {}
        keys = per_problem[0].keys()
        return {
            k: sum(s[k] for s in per_problem) / len(per_problem)
            for k in keys
        }

    def get_subset(self, problems: list[Problem], n: int) -> list[Problem]:
        """Return a deterministic subset of problems for faster evaluation."""
        import hashlib
        # Deterministic shuffle by hashing problem IDs
        sorted_problems = sorted(
            problems,
            key=lambda p: hashlib.sha256(p.problem_id.encode()).hexdigest(),
        )
        return sorted_problems[:n]
