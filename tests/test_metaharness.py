"""Tests for the meta-harness module."""

from __future__ import annotations

import pytest

from kaos.metaharness.harness import HarnessCandidate, EvaluationResult, SearchConfig
from kaos.metaharness.pareto import compute_pareto, dominates, ParetoFrontier


# ── HarnessCandidate ─────────────────────────────────────────────


class TestHarnessCandidate:
    def test_create(self):
        h = HarnessCandidate.create(
            source_code="def run(problem): return {}",
            iteration=1,
        )
        assert h.harness_id
        assert h.source_code == "def run(problem): return {}"
        assert h.iteration == 1
        assert h.parent_ids == []

    def test_create_with_parents(self):
        h = HarnessCandidate.create(
            source_code="def run(problem): return {}",
            parent_ids=["parent1", "parent2"],
        )
        assert h.parent_ids == ["parent1", "parent2"]

    def test_to_dict_from_dict_roundtrip(self):
        h = HarnessCandidate.create(
            source_code="def run(p): return {'answer': 42}",
            parent_ids=["abc"],
            iteration=3,
            metadata={"rationale": "test"},
        )
        d = h.to_dict()
        h2 = HarnessCandidate.from_dict(d)
        assert h2.harness_id == h.harness_id
        assert h2.source_code == h.source_code
        assert h2.parent_ids == h.parent_ids
        assert h2.metadata == h.metadata

    def test_validate_interface_valid(self):
        h = HarnessCandidate.create(source_code="def run(problem): return {}")
        valid, err = h.validate_interface()
        assert valid
        assert err == ""

    def test_validate_interface_valid_with_extra_args(self):
        h = HarnessCandidate.create(
            source_code="def run(problem, context=None): return {}"
        )
        valid, _ = h.validate_interface()
        assert valid

    def test_validate_interface_async(self):
        h = HarnessCandidate.create(
            source_code="async def run(problem): return {}"
        )
        valid, _ = h.validate_interface()
        assert valid

    def test_validate_interface_no_run(self):
        h = HarnessCandidate.create(source_code="def solve(problem): return {}")
        valid, err = h.validate_interface()
        assert not valid
        assert "No run() function" in err

    def test_validate_interface_no_args(self):
        h = HarnessCandidate.create(source_code="def run(): return {}")
        valid, err = h.validate_interface()
        assert not valid
        assert "must accept at least one argument" in err

    def test_validate_interface_syntax_error(self):
        h = HarnessCandidate.create(source_code="def run(problem\n  return")
        valid, err = h.validate_interface()
        assert not valid
        assert "Syntax error" in err

    def test_validate_interface_run_in_class(self):
        code = """
class Harness:
    def run(self, problem):
        return {}
"""
        h = HarnessCandidate.create(source_code=code)
        valid, _ = h.validate_interface()
        # run() inside a class still counts — self + problem = 2 args
        assert valid

    def test_validate_interface_complex_harness(self):
        code = """
import json

SYSTEM_PROMPT = "You are a helpful assistant."

def preprocess(problem):
    return problem["text"].strip()

def run(problem):
    text = preprocess(problem)
    return {"answer": text, "confidence": 0.9}

def postprocess(result):
    return result
"""
        h = HarnessCandidate.create(source_code=code)
        valid, _ = h.validate_interface()
        assert valid


# ── EvaluationResult ─────────────────────────────────────────────


class TestEvaluationResult:
    def test_success(self):
        r = EvaluationResult(
            harness_id="test",
            scores={"accuracy": 0.85, "context_cost": 1200},
            duration_ms=5000,
        )
        assert r.is_success
        assert r.scores["accuracy"] == 0.85

    def test_failure(self):
        r = EvaluationResult(
            harness_id="test",
            scores={},
            error="RuntimeError: harness crashed",
        )
        assert not r.is_success

    def test_to_scores_json(self):
        r = EvaluationResult(
            harness_id="test",
            scores={"accuracy": 0.9},
        )
        j = r.to_scores_json()
        assert '"accuracy": 0.9' in j

    def test_to_trace_jsonl(self):
        r = EvaluationResult(
            harness_id="test",
            scores={},
            trace=[
                {"type": "llm_call", "tokens": 100},
                {"type": "tool_call", "name": "fs_write"},
            ],
        )
        lines = r.to_trace_jsonl().split("\n")
        assert len(lines) == 2
        assert '"llm_call"' in lines[0]

    def test_roundtrip(self):
        r = EvaluationResult(
            harness_id="test",
            scores={"accuracy": 0.7},
            trace=[{"x": 1}],
            per_problem=[{"id": "p1", "correct": True}],
            duration_ms=3000,
        )
        d = r.to_dict()
        r2 = EvaluationResult.from_dict(d)
        assert r2.harness_id == r.harness_id
        assert r2.scores == r.scores
        assert r2.trace == r.trace


# ── SearchConfig ─────────────────────────────────────────────────


class TestSearchConfig:
    def test_defaults(self):
        c = SearchConfig(benchmark="text_classify")
        assert c.max_iterations == 20
        assert c.candidates_per_iteration == 3
        assert c.objectives == ["+accuracy", "-context_cost"]

    def test_objective_directions(self):
        c = SearchConfig(
            benchmark="test",
            objectives=["+accuracy", "-context_cost", "f1"],
        )
        dirs = c.objective_directions()
        assert dirs == {
            "accuracy": "maximize",
            "context_cost": "minimize",
            "f1": "maximize",
        }

    def test_roundtrip(self):
        c = SearchConfig(
            benchmark="math_rag",
            max_iterations=10,
            proposer_model="deepseek-r1-70b",
        )
        d = c.to_dict()
        c2 = SearchConfig.from_dict(d)
        assert c2.benchmark == c.benchmark
        assert c2.max_iterations == c.max_iterations
        assert c2.proposer_model == c.proposer_model


# ── Pareto ───────────────────────────────────────────────────────


class TestDominates:
    def test_dominates_both_maximize(self):
        objectives = {"acc": "maximize", "f1": "maximize"}
        assert dominates({"acc": 0.9, "f1": 0.8}, {"acc": 0.8, "f1": 0.7}, objectives)

    def test_does_not_dominate_equal(self):
        objectives = {"acc": "maximize"}
        assert not dominates({"acc": 0.8}, {"acc": 0.8}, objectives)

    def test_does_not_dominate_tradeoff(self):
        objectives = {"acc": "maximize", "cost": "minimize"}
        # a is better on acc but worse on cost
        assert not dominates({"acc": 0.9, "cost": 2000}, {"acc": 0.8, "cost": 1000}, objectives)

    def test_dominates_minimize(self):
        objectives = {"cost": "minimize"}
        assert dominates({"cost": 100}, {"cost": 200}, objectives)

    def test_dominates_mixed(self):
        objectives = {"acc": "maximize", "cost": "minimize"}
        assert dominates({"acc": 0.9, "cost": 100}, {"acc": 0.8, "cost": 200}, objectives)

    def test_not_dominates_one_worse(self):
        objectives = {"acc": "maximize", "f1": "maximize"}
        # a is better on acc but worse on f1
        assert not dominates({"acc": 0.9, "f1": 0.6}, {"acc": 0.8, "f1": 0.7}, objectives)


class TestComputePareto:
    def _make_result(self, hid: str, **scores) -> EvaluationResult:
        return EvaluationResult(harness_id=hid, scores=scores)

    def test_single_point(self):
        results = [self._make_result("h1", accuracy=0.8)]
        frontier = compute_pareto(results, {"accuracy": "maximize"})
        assert len(frontier.points) == 1
        assert frontier.points[0].harness_id == "h1"

    def test_dominated_point_excluded(self):
        results = [
            self._make_result("h1", accuracy=0.9),
            self._make_result("h2", accuracy=0.7),
        ]
        frontier = compute_pareto(results, {"accuracy": "maximize"})
        assert len(frontier.points) == 1
        assert frontier.points[0].harness_id == "h1"

    def test_pareto_tradeoff(self):
        results = [
            self._make_result("h1", accuracy=0.9, cost=2000),
            self._make_result("h2", accuracy=0.7, cost=500),
            self._make_result("h3", accuracy=0.6, cost=2500),  # dominated by h2 (worse acc, worse cost)
        ]
        objectives = {"accuracy": "maximize", "cost": "minimize"}
        frontier = compute_pareto(results, objectives)
        ids = {p.harness_id for p in frontier.points}
        assert ids == {"h1", "h2"}
        assert "h3" not in ids

    def test_all_on_frontier(self):
        results = [
            self._make_result("h1", accuracy=0.9, cost=2000),
            self._make_result("h2", accuracy=0.8, cost=1000),
            self._make_result("h3", accuracy=0.7, cost=500),
        ]
        objectives = {"accuracy": "maximize", "cost": "minimize"}
        frontier = compute_pareto(results, objectives)
        assert len(frontier.points) == 3

    def test_failed_results_excluded(self):
        results = [
            self._make_result("h1", accuracy=0.9),
            EvaluationResult(harness_id="h2", scores={}, error="crashed"),
        ]
        frontier = compute_pareto(results, {"accuracy": "maximize"})
        assert len(frontier.points) == 1

    def test_empty_results(self):
        frontier = compute_pareto([], {"accuracy": "maximize"})
        assert len(frontier.points) == 0

    def test_iterations_tracked(self):
        results = [self._make_result("h1", accuracy=0.8)]
        frontier = compute_pareto(
            results, {"accuracy": "maximize"}, iterations={"h1": 5}
        )
        assert frontier.points[0].iteration == 5

    def test_frontier_best_by_objective(self):
        results = [
            self._make_result("h1", accuracy=0.9, cost=2000),
            self._make_result("h2", accuracy=0.7, cost=500),
        ]
        objectives = {"accuracy": "maximize", "cost": "minimize"}
        frontier = compute_pareto(results, objectives)
        best = frontier.best_by_objective
        assert best["accuracy"].harness_id == "h1"
        assert best["cost"].harness_id == "h2"

    def test_frontier_serialization(self):
        results = [
            self._make_result("h1", accuracy=0.9),
            self._make_result("h2", accuracy=0.8),
        ]
        frontier = compute_pareto(results, {"accuracy": "maximize"})
        d = frontier.to_dict()
        f2 = ParetoFrontier.from_dict(d)
        assert len(f2.points) == len(frontier.points)
        assert f2.points[0].harness_id == frontier.points[0].harness_id

    def test_five_points_mixed(self):
        results = [
            self._make_result("h1", accuracy=0.95, cost=5000),
            self._make_result("h2", accuracy=0.90, cost=3000),
            self._make_result("h3", accuracy=0.85, cost=1000),
            self._make_result("h4", accuracy=0.80, cost=4000),  # dominated by h2
            self._make_result("h5", accuracy=0.70, cost=6000),  # dominated by all
        ]
        objectives = {"accuracy": "maximize", "cost": "minimize"}
        frontier = compute_pareto(results, objectives)
        ids = {p.harness_id for p in frontier.points}
        assert ids == {"h1", "h2", "h3"}
