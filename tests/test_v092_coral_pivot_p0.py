"""v0.9.2 Tier-0 — CORAL stagnation pivot is dead code (RED-FIRST).

The v0.10 panel verified in source that the Tier-1 pivot prompt can NEVER
fire: _update_stagnation (search.py) stamps pivot_fired_at=stagnant the moment
stagnation reaches the threshold, and propose() (proposer.py) then recomputes
the SAME predicate, where stagnant - pivot_fired_at == 0 < threshold — so the
proposer's condition is always False. Two predicates, one defeats the other.

Fix: a single authority. _update_stagnation decides and raises a `pivot_pending`
flag; the proposer consumes the flag (no recompute) and assembles the pivot
prompt. These tests drive the real state machine with NO LLM call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kaos import Kaos
from kaos.metaharness.search import MetaHarnessSearch
from kaos.metaharness.harness import SearchConfig
from kaos.metaharness.proposer import ProposerAgent
from kaos.metaharness.pareto import ParetoFrontier, ParetoPoint


class _FakeBenchmark:
    name = "fake"
    def get_seed_harnesses(self):
        return ["def run(problem):\n    return {'accuracy': 0.5}\n"]
    def get_search_set(self):
        return []
    def objectives(self):
        return {"accuracy": "maximize"}


@pytest.fixture
def search(tmp_path: Path):
    afs = Kaos(db_path=str(tmp_path / "kaos.db"))
    cfg = SearchConfig(
        benchmark="fake",
        max_iterations=10,
        candidates_per_iteration=1,
        objectives=["+accuracy"],
        stagnation_threshold=3,
    )
    s = MetaHarnessSearch(afs, router=None, benchmark=_FakeBenchmark(), config=cfg)
    s.search_agent_id = afs.spawn("meta-harness-search")
    yield s
    afs.close()


def _flat_frontier(objectives):
    """A frontier that never improves (fixed single point)."""
    return ParetoFrontier(
        points=[ParetoPoint("h0", {"accuracy": 0.5}, iteration=0)],
        objectives=objectives,
    )


class TestPivotFires:
    def test_update_stagnation_raises_pivot_pending_at_threshold(self, search):
        """After `threshold` non-improving iterations, the single authority
        must raise pivot_pending=True. Pre-fix there is no such flag and the
        pivot is silently consumed by pivot_fired_at."""
        objectives = search.config.objective_directions()
        fr = _flat_frontier(objectives)
        pending_seen = False
        for it in range(1, 6):
            search._update_stagnation(fr, iteration=it)
            if search.afs.get_state_or(search.search_agent_id, "pivot_pending"):
                pending_seen = True
                break
        assert pending_seen, "pivot_pending never set — Tier-1 pivot is dead code"

    def test_proposer_prompt_includes_pivot_when_pending(self, search):
        """Given pivot_pending=True, the proposer's assembled prompt must
        contain the pivot text. Exercises the prompt seam, no LLM call."""
        search.afs.set_state(search.search_agent_id, "pivot_pending", True)
        proposer = ProposerAgent(
            search.afs, router=None,
            search_agent_id=search.search_agent_id,
        )
        fr = _flat_frontier(search.config.objective_directions())
        prompt = proposer._assemble_prompt(
            iteration=4,
            n_candidates=1,
            benchmark_name="fake",
            frontier=fr,
            compaction_level=5,
            pivot_pending=True,
        )
        pivot_marker = "PIVOT REQUIRED"
        assert pivot_marker.strip() and pivot_marker in prompt, \
            "pivot prompt not assembled even with pivot_pending=True"

    def test_no_pivot_when_not_pending(self, search):
        proposer = ProposerAgent(
            search.afs, router=None,
            search_agent_id=search.search_agent_id,
        )
        fr = _flat_frontier(search.config.objective_directions())
        prompt = proposer._assemble_prompt(
            iteration=4,
            n_candidates=1,
            benchmark_name="fake",
            frontier=fr,
            compaction_level=5,
            pivot_pending=False,
        )
        pivot_marker = "PIVOT REQUIRED"
        assert pivot_marker not in prompt

    def test_pivot_pending_cleared_after_consumption(self, search):
        """Once the proposer fires the pivot, it must consume the flag so it
        does not re-fire every subsequent iteration."""
        search.afs.set_state(search.search_agent_id, "pivot_pending", True)
        proposer = ProposerAgent(
            search.afs, router=None,
            search_agent_id=search.search_agent_id,
        )
        fr = _flat_frontier(search.config.objective_directions())
        proposer._assemble_prompt(
            iteration=4, n_candidates=1, benchmark_name="fake",
            frontier=fr, compaction_level=5, pivot_pending=True,
        )
        assert not search.afs.get_state_or(search.search_agent_id, "pivot_pending")

    def test_improvement_resets_pending(self, search):
        """An improving iteration clears both stagnation and any pending pivot."""
        objectives = search.config.objective_directions()
        fr = _flat_frontier(objectives)
        for it in range(1, 5):
            search._update_stagnation(fr, iteration=it)
        # now improve: a frontier with a better point
        fr2 = ParetoFrontier(
            points=[ParetoPoint("h1", {"accuracy": 0.9}, iteration=5)],
            objectives=objectives,
        )
        search._update_stagnation(fr2, iteration=5)
        assert search.afs.get_state_or(search.search_agent_id, "stagnant_iterations") == 0
        assert not search.afs.get_state_or(search.search_agent_id, "pivot_pending")


# ── trivial P0: kaos --version must match the package version ─────────


def test_cli_version_matches_package():
    from click.testing import CliRunner
    from kaos import __version__
    from kaos.cli.main import cli

    result = CliRunner().invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output, (
        f"kaos --version ({result.output.strip()!r}) must report the package "
        f"version {__version__!r}"
    )
