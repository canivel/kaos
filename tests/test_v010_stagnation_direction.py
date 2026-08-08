"""v0.10 Tier-0 — CORAL stagnation ignores objective direction (RED-FIRST).

The Sara/lenz panel (2026-08-08) found in source that `_update_stagnation`
(search.py) computes `curr_best[obj] = max(vals)` for EVERY objective and tests
improvement with `abs(curr - prev) > epsilon`. Two stacked defects for a
`minimize` objective (e.g. `-context_cost`):

  1. `max(vals)` tracks the WORST cost on the frontier, not the best.
  2. `abs(...)` counts ANY movement — including a cost *regression* — as
     "improvement", resetting the stagnation counter and starving the pivot.

Consequence: a search whose accuracy has plateaued while its cost is getting
WORSE never triggers the CORAL pivot — the exact plateau the pivot exists for.

These tests drive the real state machine with NO LLM call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos import Kaos
from kaos.metaharness.search import MetaHarnessSearch
from kaos.metaharness.harness import SearchConfig
from kaos.metaharness.pareto import ParetoFrontier, ParetoPoint


class _FakeBenchmark:
    name = "fake"
    def get_seed_harnesses(self):
        return ["def run(problem):\n    return {'accuracy': 0.5}\n"]
    def get_search_set(self):
        return []
    def objectives(self):
        return {"accuracy": "maximize", "context_cost": "minimize"}


@pytest.fixture
def search(tmp_path: Path):
    afs = Kaos(db_path=str(tmp_path / "kaos.db"))
    cfg = SearchConfig(
        benchmark="fake",
        max_iterations=10,
        candidates_per_iteration=1,
        objectives=["+accuracy", "-context_cost"],
        stagnation_threshold=3,
    )
    s = MetaHarnessSearch(afs, router=None, benchmark=_FakeBenchmark(), config=cfg)
    s.search_agent_id = afs.spawn("meta-harness-search")
    yield s
    afs.close()


def _frontier(objectives, accuracy, cost):
    """Single-point frontier at the given accuracy / context_cost."""
    return ParetoFrontier(
        points=[ParetoPoint("h0", {"accuracy": accuracy, "context_cost": cost}, iteration=0)],
        objectives=objectives,
    )


class TestStagnationRespectsDirection:
    def test_regressing_cost_flat_accuracy_still_pivots(self, search):
        """Accuracy flat at 0.5, context_cost getting WORSE each iteration.
        This is a non-improving (regressing) sequence; the pivot MUST fire.
        Pre-fix, rising cost reads as improvement and the pivot never fires."""
        objectives = search.config.objective_directions()
        pending_seen = False
        for it in range(1, 7):
            fr = _frontier(objectives, accuracy=0.5, cost=1.0 + it)  # cost climbs
            search._update_stagnation(fr, iteration=it)
            if search.afs.get_state_or(search.search_agent_id, "pivot_pending"):
                pending_seen = True
                break
        assert pending_seen, (
            "pivot never fired despite flat accuracy and worsening cost — "
            "stagnation is ignoring the minimize direction"
        )

    def test_improving_cost_flat_accuracy_does_not_pivot(self, search):
        """Accuracy flat but context_cost genuinely IMPROVING (falling) each
        iteration is real progress; stagnation must NOT accrue. Guards the fix
        against over-correcting into 'everything is stagnation'."""
        objectives = search.config.objective_directions()
        for it in range(1, 7):
            fr = _frontier(objectives, accuracy=0.5, cost=10.0 - it)  # cost falls
            search._update_stagnation(fr, iteration=it)
        assert not search.afs.get_state_or(search.search_agent_id, "pivot_pending"), (
            "pivot fired while cost was steadily improving — false stagnation"
        )

    def test_true_best_cost_recorded(self, search):
        """prev_best_scores must record the BEST (min) cost on the frontier,
        not the worst (max)."""
        objectives = search.config.objective_directions()
        fr = ParetoFrontier(
            points=[
                ParetoPoint("a", {"accuracy": 0.5, "context_cost": 2.0}),
                ParetoPoint("b", {"accuracy": 0.6, "context_cost": 8.0}),
            ],
            objectives=objectives,
        )
        search._update_stagnation(fr, iteration=1)
        best = search.afs.get_state_or(search.search_agent_id, "prev_best_scores")
        assert best["context_cost"] == 2.0, (
            f"recorded {best['context_cost']} as best cost; expected min 2.0"
        )
        assert best["accuracy"] == 0.6
