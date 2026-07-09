"""v0.10 verdict-statistical-rigor — cluster bootstrap + power budget.

The panel finding: bootstrap_diff_ci resamples queries WITHIN a single run,
so it captures sampling noise but not run-to-run variance — and single-run
pass@1 varies 2.2-6.0pp between runs even at temp 0, inside the margin of a
+4pp gate. The cluster bootstrap resamples RUNS; the power-budget check makes
a pre-registered runs-per-condition binding (VOID if unmet).
"""

from __future__ import annotations

import random

import pytest

from kaos.eval.harness import (
    bootstrap_diff_ci, check_power_budget, cluster_bootstrap_diff_ci,
)


def _run(p: float, n: int, seed: int) -> list[int]:
    rng = random.Random(seed)
    return [1 if rng.random() < p else 0 for _ in range(n)]


class TestClusterBootstrap:
    def test_stable_true_difference_detected(self):
        # 5 runs/condition, no between-run drift, true diff +0.30 → lo > 0.
        runs_a = [_run(0.7, 200, s) for s in range(5)]
        runs_b = [_run(0.4, 200, 100 + s) for s in range(5)]
        md, lo, hi = cluster_bootstrap_diff_ci(runs_a, runs_b, iters=800)
        assert md == pytest.approx(0.30, abs=0.06)
        assert lo > 0.0

    def test_run_level_variance_widens_the_interval(self):
        """The load-bearing property: when runs disagree, the cluster CI must
        be wider than a single-run within-run CI on the same data. A gate
        that trusted the single-run CI here would be confidently wrong."""
        # Condition A drifts run-to-run (0.35..0.75), B is stable at 0.45 —
        # pooled means look like A ≈ 0.55 vs B ≈ 0.45.
        ps = [0.35, 0.45, 0.55, 0.65, 0.75]
        runs_a = [_run(p, 200, i) for i, p in enumerate(ps)]
        runs_b = [_run(0.45, 200, 50 + i) for i in range(5)]

        _, c_lo, c_hi = cluster_bootstrap_diff_ci(runs_a, runs_b, iters=800)
        # Single-run view: just the luckiest run of A vs one run of B.
        _, s_lo, s_hi = bootstrap_diff_ci(runs_a[-1], runs_b[0], iters=800)

        assert (c_hi - c_lo) > (s_hi - s_lo), (
            "cluster CI must be wider than a single-run CI when runs drift"
        )
        # The lucky single run is confidently positive; the honest
        # run-level interval is not.
        assert s_lo > 0.0
        assert c_lo <= 0.05, (
            f"run-level lo={c_lo:.3f} — should not confidently clear a "
            f"gate on a run-to-run-unstable effect"
        )

    def test_seed_reproducibility(self):
        runs_a = [_run(0.6, 100, s) for s in range(3)]
        runs_b = [_run(0.5, 100, 30 + s) for s in range(3)]
        r1 = cluster_bootstrap_diff_ci(runs_a, runs_b, iters=400, seed=7)
        r2 = cluster_bootstrap_diff_ci(runs_a, runs_b, iters=400, seed=7)
        assert r1 == r2

    def test_empty_inputs_return_zeros(self):
        assert cluster_bootstrap_diff_ci([], [[1, 0]]) == (0.0, 0.0, 0.0)
        assert cluster_bootstrap_diff_ci([[]], [[1, 0]]) == (0.0, 0.0, 0.0)


class TestPowerBudget:
    LOCK = {"statistics": {"runs_per_condition": 5,
                           "interval": "cluster_bootstrap"}}

    def test_budget_met_returns_none(self):
        assert check_power_budget(self.LOCK, {"FULL": 5, "B0": 6}) is None

    def test_budget_unmet_voids_with_detail(self):
        msg = check_power_budget(self.LOCK, {"FULL": 5, "B0": 3})
        assert msg is not None and msg.startswith("VOID")
        assert "B0=3" in msg and "5 runs/condition" in msg

    def test_lock_without_statistics_block_is_single_run(self):
        # Pre-v0.10 locks (synthesis, action-realization) have no statistics
        # block — they remain valid single-run probes.
        assert check_power_budget({}, {"FULL": 1}) is None
        assert check_power_budget({"statistics": {}}, {"FULL": 1}) is None
