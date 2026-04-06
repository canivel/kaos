"""Archive compactor — smart context compression for the proposer agent.

Compacts archive data (traces, scores, source, per-problem results) into a
dense digest that preserves diagnostic signal while reducing token count.

Three strategies applied per data type:
- Lossless: scores, source code, metadata (small, high signal)
- Structured extraction: traces/per-problem → error patterns + samples
- Progressive summarization: conversation history → sliding window

Compaction level (0-10):
  0 = no compaction (full archive)
  5 = balanced (default — keeps error samples + top/bottom harnesses)
 10 = maximum (scores + source only, no traces)

Information retention is measured by four diagnostic questions:
  Q1: Which problems does each harness get wrong?  → error_patterns
  Q2: What approach does each harness use?          → source_code
  Q3: How do harnesses compare?                     → scores
  Q4: What specific failure to fix?                 → failure_samples
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CompactionMetrics:
    """Measures compaction quality."""

    original_chars: int = 0
    compacted_chars: int = 0
    # Retention flags for the 4 diagnostic questions
    has_error_patterns: bool = False    # Q1
    has_source_code: bool = False       # Q2
    has_scores: bool = False            # Q3
    has_failure_samples: bool = False   # Q4

    @property
    def ratio(self) -> float:
        """Compaction ratio: 0.3 means 70% reduction."""
        if self.original_chars == 0:
            return 1.0
        return self.compacted_chars / self.original_chars

    @property
    def savings_pct(self) -> float:
        """Percentage of chars saved."""
        return (1.0 - self.ratio) * 100

    @property
    def retention_score(self) -> float:
        """0.0-1.0 score: fraction of diagnostic questions answerable."""
        checks = [
            self.has_error_patterns,
            self.has_source_code,
            self.has_scores,
            self.has_failure_samples,
        ]
        return sum(checks) / len(checks)

    def to_dict(self) -> dict:
        return {
            "original_chars": self.original_chars,
            "compacted_chars": self.compacted_chars,
            "ratio": round(self.ratio, 3),
            "savings_pct": round(self.savings_pct, 1),
            "retention_score": self.retention_score,
            "retained": {
                "error_patterns": self.has_error_patterns,
                "source_code": self.has_source_code,
                "scores": self.has_scores,
                "failure_samples": self.has_failure_samples,
            },
        }


@dataclass
class HarnessDigest:
    """Compacted representation of a single harness evaluation."""

    harness_id: str
    iteration: int
    scores: dict[str, float]
    source_code: str
    error_pattern: str       # "3/8 wrong: science→technology (2), business→sports (1)"
    failure_samples: list[dict]  # [{problem_id, expected, predicted, input_preview}]
    total_problems: int
    correct_count: int
    error: str | None = None


class Compactor:
    """Compacts archive data for the proposer with tunable compression.

    Args:
        level: 0 (no compaction) to 10 (maximum compaction).
    """

    def __init__(self, level: int = 5):
        self.level = max(0, min(10, level))

    # ── How level maps to behavior ────────────────────────────────

    @property
    def max_failure_samples(self) -> int:
        """How many failure samples to keep per harness."""
        if self.level <= 2:
            return 20  # nearly all
        if self.level <= 5:
            return 3   # key samples
        if self.level <= 8:
            return 1   # single example
        return 0       # none

    @property
    def max_source_lines(self) -> int:
        """Max source code lines to keep. 0 = unlimited."""
        if self.level <= 7:
            return 0  # full source
        return 50      # truncate very long harnesses

    @property
    def include_traces(self) -> bool:
        """Whether to include any trace data."""
        return self.level < 9

    @property
    def max_harnesses_in_digest(self) -> int:
        """How many harnesses to include (frontier + worst)."""
        if self.level <= 2:
            return 50
        if self.level <= 5:
            return 10
        return 5

    # ── Core compaction methods ───────────────────────────────────

    def compact_per_problem(
        self,
        per_problem: list[dict],
    ) -> tuple[str, list[dict]]:
        """Compact per-problem results into error pattern + failure samples.

        Returns:
            (error_pattern_string, failure_samples_list)
        """
        if not per_problem:
            return "no data", []

        correct = sum(1 for p in per_problem if p.get("correct"))
        total = len(per_problem)
        wrong = [p for p in per_problem if not p.get("correct")]

        if not wrong:
            return f"{correct}/{total} correct (100%)", []

        # Build error pattern: group by (expected → predicted) pairs
        misclass: dict[str, int] = {}
        for p in wrong:
            scores = p.get("scores", {})
            # Try to extract expected/predicted from output
            output = p.get("output", {})
            if isinstance(output, dict):
                predicted = str(output.get("prediction", "?"))[:30]
            else:
                predicted = "?"
            error_msg = p.get("error", "")
            if error_msg:
                key = f"error: {error_msg[:40]}"
            else:
                key = f"predicted '{predicted}'"
            misclass[key] = misclass.get(key, 0) + 1

        # Build pattern string
        pattern_parts = []
        for key, count in sorted(misclass.items(), key=lambda x: -x[1]):
            pattern_parts.append(f"{key} ({count}x)")
        pattern = f"{correct}/{total} correct — {len(wrong)} wrong: " + ", ".join(pattern_parts[:5])

        # Select failure samples
        samples = []
        for p in wrong[:self.max_failure_samples]:
            sample = {"problem_id": p.get("problem_id", "?")}
            if isinstance(p.get("output"), dict):
                sample["predicted"] = str(p["output"].get("prediction", ""))[:50]
            if p.get("error"):
                sample["error"] = p["error"][:80]
            scores = p.get("scores", {})
            if scores:
                sample["scores"] = scores
            samples.append(sample)

        return pattern, samples

    def compact_source(self, source: str) -> str:
        """Compact source code — strip comments at high levels."""
        if self.level <= 3:
            return source

        lines = source.split("\n")

        if self.level >= 8:
            # Strip docstrings and blank lines
            in_docstring = False
            kept = []
            for line in lines:
                stripped = line.strip()
                if not in_docstring and (stripped.startswith('"""') or stripped.startswith("'''")):
                    delim = '"""' if stripped.startswith('"""') else "'''"
                    # Single-line docstring: """text"""
                    if stripped.count(delim) >= 2:
                        continue
                    # Multi-line docstring start
                    in_docstring = True
                    continue
                if in_docstring:
                    if '"""' in stripped or "'''" in stripped:
                        in_docstring = False
                    continue
                if stripped.startswith("#") and self.level >= 9:
                    continue
                if not stripped and self.level >= 9:
                    continue
                kept.append(line)
            lines = kept

        if self.max_source_lines > 0 and len(lines) > self.max_source_lines:
            lines = lines[:self.max_source_lines] + [f"# ... ({len(lines) - self.max_source_lines} more lines)"]

        return "\n".join(lines)

    def compact_trace(self, trace_jsonl: str) -> str:
        """Compact trace JSONL — keep only error/failure entries."""
        if not self.include_traces:
            return ""
        if self.level <= 1:
            return trace_jsonl

        lines = trace_jsonl.strip().split("\n")
        kept = []
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
                # Always keep errors
                if entry.get("type") in ("problem_error", "problem_timeout"):
                    kept.append(line)
                    continue
                # Keep failures at lower levels
                if self.level <= 5 and not entry.get("correct", True):
                    kept.append(line)
                    continue
                # At higher levels, only keep errors
            except json.JSONDecodeError:
                pass

        return "\n".join(kept)

    # ── Archive digest builder ────────────────────────────────────

    def build_digest(
        self,
        harness_data: list[dict],
        frontier_data: dict | None = None,
    ) -> tuple[str, CompactionMetrics]:
        """Build a complete archive digest from harness data.

        Args:
            harness_data: list of {harness_id, iteration, scores, source,
                          per_problem, trace, metadata, error}
            frontier_data: the current Pareto frontier dict

        Returns:
            (digest_text, metrics)
        """
        metrics = CompactionMetrics()

        # Measure original size
        original = json.dumps(harness_data, default=str)
        if frontier_data:
            original += json.dumps(frontier_data)
        metrics.original_chars = len(original)

        parts: list[str] = []

        # Level 0: return raw data
        if self.level == 0:
            parts.append("## Full Archive (no compaction)\n")
            parts.append(original)
            metrics.compacted_chars = len(original)
            metrics.has_error_patterns = True
            metrics.has_source_code = True
            metrics.has_scores = True
            metrics.has_failure_samples = True
            return "\n".join(parts), metrics

        # Frontier summary
        if frontier_data:
            parts.append("## Current Pareto Frontier\n")
            for point in frontier_data.get("points", []):
                scores_str = ", ".join(f"{k}={v:.4f}" for k, v in point.get("scores", {}).items())
                parts.append(f"- {point['harness_id'][:12]}... (iter {point.get('iteration', '?')}): {scores_str}")
            parts.append("")
            metrics.has_scores = True

        # Sort harnesses: frontier first, then by best score descending
        harness_data = sorted(
            harness_data,
            key=lambda h: max(h.get("scores", {}).values()) if h.get("scores") else -1,
            reverse=True,
        )

        # Limit harness count based on level
        harness_data = harness_data[:self.max_harnesses_in_digest]

        for h in harness_data:
            hid = h.get("harness_id", "?")
            scores = h.get("scores", {})
            source = h.get("source", "")
            per_problem = h.get("per_problem", [])
            error = h.get("error")

            parts.append(f"## Harness {hid[:12]}... (iteration {h.get('iteration', '?')})\n")

            # Scores (always lossless)
            if scores:
                scores_str = ", ".join(f"{k}={v:.4f}" for k, v in scores.items())
                parts.append(f"**Scores:** {scores_str}")
                metrics.has_scores = True

            if error:
                parts.append(f"**Error:** {error}")

            # Error pattern (structured extraction)
            if per_problem:
                pattern, samples = self.compact_per_problem(per_problem)
                parts.append(f"**Results:** {pattern}")
                metrics.has_error_patterns = True

                if samples:
                    parts.append("**Failure samples:**")
                    for s in samples:
                        parts.append(f"  - {s.get('problem_id', '?')}: {json.dumps(s, default=str)[:150]}")
                    metrics.has_failure_samples = True

            # Source code (lossless or compacted at high levels)
            if source:
                compacted_source = self.compact_source(source)
                parts.append(f"**Source ({len(source)} chars):**")
                parts.append(f"```python\n{compacted_source}\n```")
                metrics.has_source_code = True

            parts.append("")

        digest = "\n".join(parts)
        metrics.compacted_chars = len(digest)
        return digest, metrics


def compact_conversation(messages: list[dict], keep_recent: int = 4) -> list[dict]:
    """Progressive summarization of conversation history.

    Keeps the system prompt, first user message, and last `keep_recent`
    messages verbatim. Summarizes everything in between into a single
    "[PRIOR CONTEXT]" message.

    Args:
        messages: conversation message list
        keep_recent: number of recent messages to keep verbatim

    Returns:
        compacted message list
    """
    if len(messages) <= keep_recent + 2:
        return messages

    # Keep: system prompt + first user message + last N
    head = []
    for msg in messages:
        head.append(msg)
        if msg.get("role") == "user":
            break

    tail = messages[-keep_recent:]
    middle = messages[len(head):-keep_recent]

    if not middle:
        return messages

    # Summarize middle into a compact block
    summary_parts = []
    for msg in middle:
        role = msg.get("role", "?")
        content = str(msg.get("content", ""))
        if role == "tool":
            # Heavily compress tool results
            summary_parts.append(f"[tool result: {len(content)} chars]")
        elif role == "assistant":
            tool_calls = msg.get("tool_calls", [])
            if tool_calls:
                names = [tc.get("function", {}).get("name", "?") for tc in tool_calls]
                summary_parts.append(f"[assistant called: {', '.join(names)}]")
            else:
                summary_parts.append(f"[assistant: {content[:100]}...]")
        else:
            summary_parts.append(f"[{role}: {content[:100]}...]")

    summary = "\n".join(summary_parts)

    compacted = head + [{
        "role": "user",
        "content": f"[PRIOR CONTEXT — {len(middle)} messages compacted]\n{summary}\n[/PRIOR CONTEXT]",
    }] + tail

    return compacted
