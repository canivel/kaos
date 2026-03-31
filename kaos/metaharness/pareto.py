"""Pareto frontier computation for multi-objective harness optimization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kaos.metaharness.harness import EvaluationResult


@dataclass
class ParetoPoint:
    """A single point on the Pareto frontier."""

    harness_id: str
    scores: dict[str, float]
    iteration: int = 0


@dataclass
class ParetoFrontier:
    """The current Pareto frontier of harness candidates."""

    points: list[ParetoPoint] = field(default_factory=list)
    objectives: dict[str, str] = field(default_factory=dict)  # {name: maximize|minimize}

    def to_dict(self) -> dict:
        return {
            "objectives": self.objectives,
            "points": [
                {"harness_id": p.harness_id, "scores": p.scores, "iteration": p.iteration}
                for p in self.points
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> ParetoFrontier:
        return cls(
            objectives=data.get("objectives", {}),
            points=[
                ParetoPoint(
                    harness_id=p["harness_id"],
                    scores=p["scores"],
                    iteration=p.get("iteration", 0),
                )
                for p in data.get("points", [])
            ],
        )

    @property
    def best_by_objective(self) -> dict[str, ParetoPoint]:
        """Return the best point for each objective."""
        best = {}
        for obj_name, direction in self.objectives.items():
            if not self.points:
                continue
            if direction == "maximize":
                best[obj_name] = max(self.points, key=lambda p: p.scores.get(obj_name, 0))
            else:
                best[obj_name] = min(self.points, key=lambda p: p.scores.get(obj_name, float("inf")))
        return best


def dominates(
    a: dict[str, float],
    b: dict[str, float],
    objectives: dict[str, str],
) -> bool:
    """Check if point a dominates point b.

    a dominates b if a is at least as good in all objectives and
    strictly better in at least one.
    """
    at_least_as_good = True
    strictly_better = False

    for obj_name, direction in objectives.items():
        a_val = a.get(obj_name, 0)
        b_val = b.get(obj_name, 0)

        if direction == "maximize":
            if a_val < b_val:
                at_least_as_good = False
                break
            if a_val > b_val:
                strictly_better = True
        else:  # minimize
            if a_val > b_val:
                at_least_as_good = False
                break
            if a_val < b_val:
                strictly_better = True

    return at_least_as_good and strictly_better


def compute_pareto(
    results: list[EvaluationResult],
    objectives: dict[str, str],
    iterations: dict[str, int] | None = None,
) -> ParetoFrontier:
    """Compute the Pareto frontier from evaluation results.

    Args:
        results: List of evaluation results (only successful ones are considered).
        objectives: {name: "maximize"|"minimize"} for each objective.
        iterations: Optional {harness_id: iteration} mapping.

    Returns:
        ParetoFrontier with non-dominated points.
    """
    iterations = iterations or {}
    successful = [r for r in results if r.is_success]

    if not successful:
        return ParetoFrontier(objectives=objectives)

    frontier_points = []

    for candidate in successful:
        is_dominated = False
        for other in successful:
            if other.harness_id == candidate.harness_id:
                continue
            if dominates(other.scores, candidate.scores, objectives):
                is_dominated = True
                break

        if not is_dominated:
            frontier_points.append(
                ParetoPoint(
                    harness_id=candidate.harness_id,
                    scores=candidate.scores,
                    iteration=iterations.get(candidate.harness_id, 0),
                )
            )

    # Sort by first objective for consistent ordering
    first_obj = next(iter(objectives))
    reverse = objectives[first_obj] == "maximize"
    frontier_points.sort(key=lambda p: p.scores.get(first_obj, 0), reverse=reverse)

    return ParetoFrontier(points=frontier_points, objectives=objectives)
