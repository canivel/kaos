"""Fixes found by the WMP probe smoke run: per-problem timeout semantics and
seed-eval subset application (both silently broke LLM-calling harnesses)."""

from __future__ import annotations

import asyncio
import time

import pytest

from kaos import Kaos
from kaos.metaharness.evaluator import HarnessEvaluator
from kaos.metaharness.harness import HarnessCandidate


SLOW_HARNESS = '''
import time

def run(problem):
    time.sleep(0.6)   # slower than old divided timeout (1.0/2=0.5s), well
    return {"prediction": problem.get("expected_hint", "x")}
'''


class _Bench:
    """Two-problem benchmark with mechanical scoring."""
    name = "stub"
    objectives = ["+accuracy"]

    def get_search_set(self):
        from kaos.metaharness.benchmarks.base import Problem
        return [Problem(problem_id=f"p{i}",
                        input={"expected_hint": "x"}, expected="x",
                        metadata={}) for i in range(2)]

    def score(self, problem, output):
        return {"accuracy": 1.0 if output.get("prediction") == "x" else 0.0}

    def aggregate_scores(self, per_problem):
        if not per_problem:
            return {}
        keys = per_problem[0].keys()
        return {k: sum(s[k] for s in per_problem) / len(per_problem)
                for k in keys}


class TestPerProblemTimeout:
    def test_timeout_is_per_problem_not_divided(self, tmp_path):
        """timeout_seconds=1.0 with 2 problems x 0.6s each: the old
        divided semantics (0.5s/problem) failed both; per-problem passes."""
        afs = Kaos(db_path=str(tmp_path / "k.db"))
        ev = HarnessEvaluator(afs, router=None, benchmark=_Bench(),
                              timeout_seconds=1)
        h = HarnessCandidate(harness_id=HarnessCandidate.new_id(),
                             source_code=SLOW_HARNESS)
        res = asyncio.run(ev.evaluate(h))
        afs.close()
        assert res.scores.get("accuracy") == 1.0, res.scores
