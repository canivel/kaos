"""kaos.bench.fingerprint — Filter 2 semantics must be exactly PLAN v2 §3.2.

The regression that matters most: GDL's 81-point constructed win must be WITHHELD
on a workload whose consumed axis is absent/unknown — hard gate, no partial credit.
"""

from __future__ import annotations

import pytest

from kaos.bench.fingerprint import (
    CTX_FULL_THRESHOLD,
    Envelope,
    Grain,
    Level,
    PARTIAL_WEIGHT,
    TaskShape,
    anchor_tokens,
    m1_level,
    m2_level,
    m4_level,
    match,
)


class TestLevels:
    def test_unknown_is_the_floor(self):
        assert Level.UNKNOWN < Level.ABSENT < Level.WEAK < Level.PRESENT < Level.STRONG

    def test_m1_vacuity_guard(self):
        # GDL lesson: mono-label agents (diversity < 3) → UNKNOWN even at reuse 10.0
        assert m1_level(covered_fraction=0.9, median_reuse=10.0, label_diversity=1) == Level.UNKNOWN
        assert m1_level(covered_fraction=0.9, median_reuse=10.0, label_diversity=2) == Level.UNKNOWN
        # diverse basis with real reuse → present/strong
        assert m1_level(covered_fraction=0.6, median_reuse=1.5, label_diversity=8) == Level.STRONG
        assert m1_level(covered_fraction=0.1, median_reuse=1.0, label_diversity=8) == Level.ABSENT

    def test_m2_grain_and_predicates(self):
        assert m2_level(checkable_predicates=0, outcome_grain=Grain.NONE) == Level.ABSENT
        assert m2_level(checkable_predicates=1, outcome_grain=Grain.EPISODE) == Level.PRESENT
        assert m2_level(checkable_predicates=3, outcome_grain=Grain.STEP) == Level.STRONG

    def test_m4_mono_label_match_is_weak(self):
        # a loose episode match with diversity < 3 is undiffable (GDL) — weak, not present
        assert m4_level(strong_provider_reachable=False, matched_episode=True,
                        matched_episode_diversity=1) == Level.WEAK
        assert m4_level(strong_provider_reachable=False, matched_episode=True,
                        matched_episode_diversity=5) == Level.PRESENT


class TestAnchors:
    def test_extraction(self):
        toks = anchor_tokens("fix the parser in src/parser_x.py after exit 1 at abc1234def")
        assert "parser_x" in toks and "py" in toks and "abc1234def" in toks

    def test_m3_scored_per_candidate(self):
        task = TaskShape(m3_anchor_tokens=anchor_tokens("update billing/reconcile.py totals"))
        hit = Envelope(retrieval_keys=anchor_tokens("skill for billing/reconcile.py rounding"))
        miss = Envelope(retrieval_keys=anchor_tokens("kubernetes deploy canary_rollout.yaml"))
        assert task.level("M3", hit) >= Level.PRESENT
        assert task.level("M3", miss) == Level.ABSENT


class TestMatchHardGate:
    def test_consumed_absent_withholds_no_partial_credit(self):
        # The GDL regression: envelope consumes M1; workload M1 absent → WITHHOLD
        env = Envelope(consumes=("M1",), measured={"M1": Level.STRONG})
        task = TaskShape(m1=Level.ABSENT, m2=Level.PRESENT, m2_grain=Grain.EPISODE)
        r = match(env, task)
        assert r.decision == "WITHHOLD" and r.reason == "axis-absent" and r.axis == "M1"
        assert r.weight == 0.0

    def test_consumed_unknown_withholds(self):
        # unknown is never present — the vacuous-gate lesson as pull-time law
        env = Envelope(consumes=("M1",))
        task = TaskShape(m1=Level.UNKNOWN, m2_grain=Grain.STEP)
        r = match(env, task)
        assert r.decision == "WITHHOLD" and r.reason == "axis-unknown"

    def test_unmonitorable_withholds(self):
        # record needs step-grain outcomes; task only writes episode-grain
        env = Envelope(consumes=(), m2_grain=Grain.STEP)
        task = TaskShape(m2=Level.PRESENT, m2_grain=Grain.EPISODE)
        r = match(env, task)
        assert r.decision == "WITHHOLD" and r.reason == "unmonitorable"

    def test_consumed_m3_gates_on_overlap(self):
        env = Envelope(consumes=("M3",), retrieval_keys=anchor_tokens("auth_rotate api/auth.py"),
                       m2_grain=Grain.EPISODE)
        matching = TaskShape(m3_anchor_tokens=anchor_tokens("rotate secret in api/auth.py"),
                             m2_grain=Grain.EPISODE)
        unrelated = TaskShape(m3_anchor_tokens=anchor_tokens("optimize sql query planner"),
                              m2_grain=Grain.EPISODE)
        assert match(env, matching).decision == "PULL"
        assert match(env, unrelated).decision == "WITHHOLD"


class TestMatchSoftContext:
    def test_full_pull_when_context_close(self):
        env = Envelope(consumes=("M2",), m2_grain=Grain.EPISODE,
                       measured={"M1": Level.PRESENT, "M4": Level.ABSENT},
                       retrieval_keys=anchor_tokens("retry_backoff pipelines/scrape.py"))
        task = TaskShape(m1=Level.PRESENT, m2=Level.PRESENT, m4=Level.ABSENT,
                         m2_grain=Grain.EPISODE,
                         m3_anchor_tokens=anchor_tokens("fix retry_backoff in pipelines/scrape.py"))
        r = match(env, task)
        assert r.decision == "PULL" and r.fidelity == "full" and r.weight == 1.0
        assert r.ctx_score >= CTX_FULL_THRESHOLD

    def test_partial_pull_on_context_drift(self):
        env = Envelope(consumes=("M2",), m2_grain=Grain.EPISODE,
                       measured={"M1": Level.STRONG, "M4": Level.STRONG},
                       retrieval_keys=set())
        task = TaskShape(m1=Level.ABSENT, m2=Level.PRESENT, m4=Level.ABSENT,
                         m2_grain=Grain.EPISODE)
        r = match(env, task)
        assert r.decision == "PULL" and r.fidelity == "partial"
        assert r.weight == PARTIAL_WEIGHT
        assert r.ctx_score < CTX_FULL_THRESHOLD

    def test_partial_is_stamped_for_stratification(self):
        # fidelity must ride the result so outcome telemetry can stratify by it
        env = Envelope(consumes=(), measured={}, m2_grain=Grain.NONE)
        task = TaskShape()
        r = match(env, task)
        assert r.fidelity in ("full", "partial")
