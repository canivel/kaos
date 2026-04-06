"""Tests for the archive compactor — measures compaction quality at each level."""

from __future__ import annotations

import json
import pytest

from kaos.metaharness.compactor import Compactor, CompactionMetrics, compact_conversation


# ── Test data ───────────────────────────────────────────────────

SAMPLE_PER_PROBLEM = [
    {"problem_id": "p1", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 22}, "output": {"prediction": "technology"}},
    {"problem_id": "p2", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 18}, "output": {"prediction": "science"}},
    {"problem_id": "p3", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 25}, "output": {"prediction": "technology"}, "error": ""},
    {"problem_id": "p4", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 20}, "output": {"prediction": "business"}},
    {"problem_id": "p5", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 15}, "output": {"prediction": "technology"}},
    {"problem_id": "p6", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 12}, "output": {"prediction": "sports"}},
    {"problem_id": "p7", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 19}, "output": {"prediction": "business"}},
    {"problem_id": "p8", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 30}, "output": {"prediction": "science"}, "error": "timeout"},
]

SAMPLE_SOURCE = '''\
"""Domain keyword classifier."""

import re
from collections import Counter

DOMAIN_KEYWORDS = {
    "technology": ["gpu", "cpu", "cloud", "compiler", "llm"],
    "science": ["protein", "quantum", "telescope", "climate"],
    "business": ["revenue", "merger", "startup", "funding"],
    "sports": ["championship", "quarterback", "marathon"],
}

def run(problem):
    """Classify via keyword matching."""
    text = problem["text"].lower()
    labels = problem.get("labels", [])
    scores = {}
    for label in labels:
        kws = DOMAIN_KEYWORDS.get(label, [])
        scores[label] = sum(1 for kw in kws if kw in text)
    best = max(scores, key=scores.get) if scores else labels[0]
    return {"prediction": best, "context_tokens": len(text.split())}
'''

SAMPLE_HARNESS_DATA = [
    {
        "harness_id": "h1_zero_shot",
        "iteration": 0,
        "scores": {"accuracy": 0.0, "context_cost": 22.75},
        "source": '"""Zero-shot."""\ndef run(p):\n    return {"prompt": p["text"]}',
        "per_problem": SAMPLE_PER_PROBLEM[:4],
        "error": None,
    },
    {
        "harness_id": "h2_keyword",
        "iteration": 1,
        "scores": {"accuracy": 0.875, "context_cost": 8.0},
        "source": SAMPLE_SOURCE,
        "per_problem": SAMPLE_PER_PROBLEM,
        "error": None,
    },
    {
        "harness_id": "h3_failed",
        "iteration": 1,
        "scores": {},
        "source": 'def run(p): raise RuntimeError("crash")',
        "per_problem": [],
        "error": "RuntimeError: crash",
    },
]

SAMPLE_FRONTIER = {
    "objectives": {"accuracy": "maximize", "context_cost": "minimize"},
    "points": [
        {"harness_id": "h2_keyword", "iteration": 1, "scores": {"accuracy": 0.875, "context_cost": 8.0}},
    ],
}


# ── CompactionMetrics ───────────────────────────────────────────


class TestCompactionMetrics:
    def test_ratio(self):
        m = CompactionMetrics(original_chars=1000, compacted_chars=300)
        assert m.ratio == 0.3
        assert m.savings_pct == 70.0

    def test_retention_score_full(self):
        m = CompactionMetrics(
            has_error_patterns=True, has_source_code=True,
            has_scores=True, has_failure_samples=True,
        )
        assert m.retention_score == 1.0

    def test_retention_score_partial(self):
        m = CompactionMetrics(has_scores=True, has_source_code=True)
        assert m.retention_score == 0.5

    def test_to_dict(self):
        m = CompactionMetrics(original_chars=100, compacted_chars=30)
        d = m.to_dict()
        assert d["savings_pct"] == 70.0
        assert "retained" in d


# ── Compactor levels ────────────────────────────────────────────


class TestCompactorLevels:
    """Verify that higher levels produce smaller output."""

    def test_level_0_no_compaction(self):
        c = Compactor(level=0)
        digest, metrics = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
        # Level 0 should be essentially full data
        assert metrics.ratio > 0.9
        assert metrics.retention_score == 1.0

    def test_level_5_balanced(self):
        c = Compactor(level=5)
        digest, metrics = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
        assert metrics.retention_score >= 0.75
        assert metrics.has_scores
        assert metrics.has_source_code
        assert metrics.has_error_patterns

    def test_level_10_maximum(self):
        c = Compactor(level=10)
        digest, metrics = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
        # Maximum compaction should still have scores and source
        assert metrics.has_scores
        assert metrics.has_source_code

    def test_monotonic_compression(self):
        """Higher levels should produce smaller or equal output."""
        sizes = []
        for level in range(0, 11):
            c = Compactor(level=level)
            digest, metrics = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
            sizes.append(metrics.compacted_chars)
        # Each level should be <= the previous (with some tolerance for formatting)
        for i in range(1, len(sizes)):
            assert sizes[i] <= sizes[i - 1] * 1.05, (
                f"Level {i} ({sizes[i]}) larger than level {i-1} ({sizes[i-1]})"
            )

    def test_retention_decreases_gracefully(self):
        """Retention score should decrease gradually, not cliff."""
        retentions = []
        for level in range(0, 11):
            c = Compactor(level=level)
            _, metrics = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
            retentions.append(metrics.retention_score)
        # Level 0 should be 1.0, level 10 should be >= 0.5
        assert retentions[0] == 1.0
        assert retentions[10] >= 0.5  # still has scores + source


# ── Per-problem compaction ──────────────────────────────────────


class TestCompactPerProblem:
    def test_all_correct(self):
        c = Compactor(level=5)
        pattern, samples = c.compact_per_problem([
            {"problem_id": "p1", "correct": True},
            {"problem_id": "p2", "correct": True},
        ])
        assert "100%" in pattern
        assert len(samples) == 0

    def test_mixed_results(self):
        c = Compactor(level=5)
        pattern, samples = c.compact_per_problem(SAMPLE_PER_PROBLEM)
        assert "4/8" in pattern  # 4 correct
        assert "4 wrong" in pattern
        assert len(samples) <= 3  # level 5 = max 3 samples

    def test_level_0_keeps_all_samples(self):
        c = Compactor(level=0)
        pattern, samples = c.compact_per_problem(SAMPLE_PER_PROBLEM)
        assert len(samples) == 4  # all 4 failures

    def test_level_10_no_samples(self):
        c = Compactor(level=10)
        pattern, samples = c.compact_per_problem(SAMPLE_PER_PROBLEM)
        assert len(samples) == 0
        assert "4 wrong" in pattern  # pattern still present

    def test_empty_input(self):
        c = Compactor(level=5)
        pattern, samples = c.compact_per_problem([])
        assert pattern == "no data"


# ── Source compaction ───────────────────────────────────────────


class TestCompactSource:
    def test_low_level_preserves_all(self):
        c = Compactor(level=2)
        result = c.compact_source(SAMPLE_SOURCE)
        assert result == SAMPLE_SOURCE

    def test_high_level_strips_docstrings(self):
        c = Compactor(level=8)
        result = c.compact_source(SAMPLE_SOURCE)
        assert '"""Domain keyword classifier."""' not in result
        assert "def run(problem):" in result  # function still there

    def test_max_level_strips_comments(self):
        c = Compactor(level=10)
        result = c.compact_source(SAMPLE_SOURCE)
        assert "# " not in result or "# ..." in result
        assert "def run" in result


# ── Conversation compaction ─────────────────────────────────────


class TestConversationCompaction:
    def test_short_conversation_unchanged(self):
        msgs = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi!"},
        ]
        result = compact_conversation(msgs)
        assert len(result) == 3

    def test_long_conversation_compacted(self):
        msgs = [{"role": "system", "content": "system"}]
        msgs.append({"role": "user", "content": "initial task"})
        for i in range(20):
            msgs.append({"role": "assistant", "content": f"step {i}", "tool_calls": [{"function": {"name": f"tool_{i}"}}]})
            msgs.append({"role": "tool", "content": "x" * 1000})
        msgs.append({"role": "assistant", "content": "final answer"})

        result = compact_conversation(msgs, keep_recent=4)
        assert len(result) < len(msgs)
        # First message (system) preserved
        assert result[0]["role"] == "system"
        # Last messages preserved
        assert result[-1]["content"] == "final answer"
        # Middle compressed
        has_prior = any("PRIOR CONTEXT" in str(m.get("content", "")) for m in result)
        assert has_prior

    def test_tool_results_compressed(self):
        # Build a conversation with many large tool results
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
        ]
        for i in range(6):
            msgs.append({"role": "assistant", "content": f"call {i}", "tool_calls": [{"function": {"name": f"tool_{i}"}}]})
            msgs.append({"role": "tool", "content": "x" * 3000})
        msgs.append({"role": "assistant", "content": "done"})

        result = compact_conversation(msgs, keep_recent=4)
        total_chars = sum(len(str(m.get("content", ""))) for m in result)
        original_chars = sum(len(str(m.get("content", ""))) for m in msgs)
        assert total_chars < original_chars * 0.7  # meaningful savings


# ── Integration: digest quality ─────────────────────────────────


class TestDigestQuality:
    """Verify that the digest answers the 4 diagnostic questions at every level."""

    @pytest.mark.parametrize("level", [0, 1, 3, 5, 7, 9, 10])
    def test_scores_always_present(self, level):
        c = Compactor(level=level)
        digest, metrics = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
        assert metrics.has_scores
        assert "0.875" in digest or "accuracy" in digest.lower()

    @pytest.mark.parametrize("level", [0, 1, 3, 5, 7])
    def test_source_present_below_8(self, level):
        c = Compactor(level=level)
        digest, metrics = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
        assert metrics.has_source_code
        assert "def run" in digest

    @pytest.mark.parametrize("level", [0, 1, 3, 5, 7])
    def test_error_patterns_present_below_8(self, level):
        c = Compactor(level=level)
        digest, metrics = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
        # At least one harness has per_problem data
        if any(h["per_problem"] for h in SAMPLE_HARNESS_DATA):
            assert metrics.has_error_patterns

    def test_failed_harness_error_shown(self):
        c = Compactor(level=5)
        digest, _ = c.build_digest(SAMPLE_HARNESS_DATA, SAMPLE_FRONTIER)
        assert "crash" in digest.lower()
