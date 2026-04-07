"""Archive compactor — smart context compression for the proposer agent.

Uses AAAK-style compact notation (inspired by MemPalace) and tiered loading
to achieve high compression with zero diagnostic quality loss.

Tiered loading (maps to compaction levels):
  L0 (level 0-2):  Full verbose — all data, markdown format
  L1 (level 3-5):  Structured — AAAK shorthand for scores/errors, full source for frontier
  L2 (level 6-8):  Compact — AAAK for everything, source only for top harnesses
  L3 (level 9-10): Ultra — scores + error patterns only, minimal source

AAAK notation examples:
  H:keyword_cls|i2|acc=1.0|cost=8.0|8/8✓
  H:zero_shot|i0|acc=0.0|cost=22.8|0/8✓|ERR:empty_pred(8x)
  FRONTIER: keyword_cls(acc=1.0,cost=8.0)
  FIX: add 'team','player' to sports keywords | remove API dep

Information retention measured by diagnostic questions across 5 domains.
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

        Uses tiered loading:
          L0 (level 0-2):  Full verbose markdown
          L1 (level 3-5):  AAAK shorthand for non-frontier, full source for frontier
          L2 (level 6-8):  AAAK for everything, source only for top harnesses
          L3 (level 9-10): Ultra-compact scores + patterns only
        """
        metrics = CompactionMetrics()

        original = json.dumps(harness_data, default=str)
        if frontier_data:
            original += json.dumps(frontier_data)
        metrics.original_chars = len(original)

        # Determine tier
        if self.level <= 2:
            tier = 0
        elif self.level <= 5:
            tier = 1
        elif self.level <= 8:
            tier = 2
        else:
            tier = 3

        # Sort: best scores first
        harness_data = sorted(
            harness_data,
            key=lambda h: max(h.get("scores", {}).values()) if h.get("scores") else -1,
            reverse=True,
        )
        harness_data = harness_data[:self.max_harnesses_in_digest]

        # Identify frontier harness IDs
        frontier_ids = set()
        if frontier_data:
            frontier_ids = {p["harness_id"] for p in frontier_data.get("points", [])}

        parts: list[str] = []

        # ── Frontier ──
        if frontier_data:
            if tier == 0:
                parts.append("## Current Pareto Frontier\n")
                for p in frontier_data.get("points", []):
                    scores_str = ", ".join(f"{k}={v:.4f}" for k, v in p.get("scores", {}).items())
                    parts.append(f"- {p['harness_id'][:12]}... (iter {p.get('iteration', '?')}): {scores_str}")
            else:
                # AAAK frontier
                fp = []
                for p in frontier_data.get("points", []):
                    ss = ",".join(f"{k}={v:.4f}" for k, v in p.get("scores", {}).items())
                    fp.append(f"{p['harness_id'][:10]}({ss})")
                parts.append(f"FRONTIER: {' | '.join(fp)}")
            parts.append("")
            metrics.has_scores = True

        # ── Per-harness ──
        for h in harness_data:
            hid = h.get("harness_id", "?")
            scores = h.get("scores", {})
            source = h.get("source", "")
            per_problem = h.get("per_problem", [])
            error = h.get("error")
            is_frontier = hid in frontier_ids
            verifier_diag = h.get("diagnosis")

            if tier == 0:
                # L0: Full verbose
                parts.append(self._digest_verbose(h, metrics))
            elif tier == 1:
                # L1: AAAK header + full source for all (savings from AAAK format)
                parts.append(self._digest_aaak(h, metrics, full_source=True))
            elif tier == 2:
                # L2: AAAK everything, source only for top 3
                rank = harness_data.index(h)
                parts.append(self._digest_aaak(h, metrics, full_source=(rank < 3)))
            else:
                # L3: Ultra-compact — one line per harness
                parts.append(self._digest_ultra(h, metrics))

        digest = "\n".join(parts)
        metrics.compacted_chars = len(digest)
        return digest, metrics

    def _digest_verbose(self, h: dict, metrics: CompactionMetrics) -> str:
        """L0: Full verbose markdown format."""
        parts = []
        hid = h.get("harness_id", "?")
        scores = h.get("scores", {})
        source = h.get("source", "")
        per_problem = h.get("per_problem", [])
        error = h.get("error")

        parts.append(f"## Harness {hid[:12]}... (iteration {h.get('iteration', '?')})\n")

        if scores:
            parts.append(f"**Scores:** {', '.join(f'{k}={v:.4f}' for k, v in scores.items())}")
            metrics.has_scores = True

        if error:
            parts.append(f"**Error:** {error}")

        # Verifier diagnosis
        self._append_diagnosis(parts, h.get("diagnosis"))

        if per_problem:
            pattern, samples = self.compact_per_problem(per_problem)
            parts.append(f"**Results:** {pattern}")
            metrics.has_error_patterns = True
            if samples:
                parts.append("**Failure samples:**")
                for s in samples:
                    parts.append(f"  - {s.get('problem_id', '?')}: {json.dumps(s, default=str)[:150]}")
                metrics.has_failure_samples = True

        if source:
            parts.append(f"**Source ({len(source)} chars):**")
            parts.append(f"```python\n{source}\n```")
            metrics.has_source_code = True

        parts.append("")
        return "\n".join(parts)

    def _digest_aaak(self, h: dict, metrics: CompactionMetrics, full_source: bool = False) -> str:
        """L1/L2: AAAK shorthand notation."""
        parts = []
        hid = h.get("harness_id", "?")[:10]
        scores = h.get("scores", {})
        per_problem = h.get("per_problem", [])
        source = h.get("source", "")
        error = h.get("error")

        # Header line: H:id|iN|score1=val|score2=val|correct/total✓|ERR:type(Nx)
        header = f"H:{hid}|i{h.get('iteration', '?')}"
        if scores:
            header += "|" + "|".join(f"{k}={v:.4f}" for k, v in scores.items())
            metrics.has_scores = True

        if per_problem:
            correct = sum(1 for p in per_problem if p.get("correct"))
            total = len(per_problem)
            header += f"|{correct}/{total}\u2713"

            # Error summary in AAAK — preserve error message content for diagnostics
            wrong = [p for p in per_problem if not p.get("correct")]
            if wrong:
                err_types: dict[str, int] = {}
                for w in wrong:
                    if w.get("error"):
                        # Keep enough of the error for diagnostic search
                        key = w["error"][:40]
                    elif isinstance(w.get("output"), dict):
                        pred = str(w["output"].get("prediction", ""))[:15]
                        key = f"wrong pred:'{pred}'" if pred else "empty"
                    else:
                        key = "fail"
                    err_types[key] = err_types.get(key, 0) + 1
                err_str = ",".join(f"{k}({v}x)" for k, v in sorted(err_types.items(), key=lambda x: -x[1])[:3])
                header += f"|ERR:{err_str}"
                metrics.has_error_patterns = True
                metrics.has_failure_samples = True

        if error:
            header += f"|FAIL:{error[:30]}"

        parts.append(header)

        # Verifier suggestions in AAAK
        diag = h.get("diagnosis")
        if diag and isinstance(diag, dict):
            suggestions = diag.get("suggestions", [])
            if suggestions:
                parts.append("FIX: " + " | ".join(s[:60] for s in suggestions[:2]))
            root_causes = diag.get("failure_patterns", [])
            if root_causes:
                causes = [f"{p.get('pattern', '?')[:20]}→{p.get('root_cause', '?')[:30]}" for p in root_causes[:2]]
                parts.append("CAUSE: " + " | ".join(causes))

        # Source
        if source and full_source:
            parts.append(f"SRC({len(source)}c):")
            parts.append(f"```python\n{self.compact_source(source)}\n```")
            metrics.has_source_code = True
        elif source:
            # One-line source summary: first def + key identifiers
            first_def = ""
            key_ids = []
            for line in source.split("\n"):
                stripped = line.strip()
                if stripped.startswith("def run("):
                    first_def = stripped[:60]
                elif "KEYWORD" in stripped.upper() or "DOMAIN" in stripped.upper():
                    key_ids.append(stripped[:40])
                elif stripped.startswith("class ") or (stripped.startswith("def ") and "run" not in stripped):
                    key_ids.append(stripped[:40])
            if first_def or key_ids:
                parts.append(f"SRC: {first_def} {'| '.join(key_ids[:2])}")
                metrics.has_source_code = True

        return "\n".join(parts)

    def _digest_ultra(self, h: dict, metrics: CompactionMetrics) -> str:
        """L3: Ultra-compact — one line per harness."""
        hid = h.get("harness_id", "?")[:8]
        scores = h.get("scores", {})
        per_problem = h.get("per_problem", [])

        if scores:
            ss = ",".join(f"{k}={v:.2f}" for k, v in scores.items())
            metrics.has_scores = True
        else:
            ss = "no_scores"

        if per_problem:
            correct = sum(1 for p in per_problem if p.get("correct"))
            total = len(per_problem)
            metrics.has_error_patterns = True
            return f"{hid}|i{h.get('iteration', '?')}|{ss}|{correct}/{total}\u2713"
        return f"{hid}|i{h.get('iteration', '?')}|{ss}"

    def _append_diagnosis(self, parts: list[str], diagnosis: Any) -> None:
        """Append verifier diagnosis in verbose format."""
        if not diagnosis or not isinstance(diagnosis, dict):
            return
        suggestions = diagnosis.get("suggestions", [])
        if suggestions:
            parts.append("**Verifier suggestions:**")
            for s in suggestions[:3]:
                parts.append(f"  - {s}")
        fp = diagnosis.get("failure_patterns", [])
        if fp:
            parts.append("**Root causes:**")
            for p in fp[:3]:
                parts.append(f"  - {p.get('pattern', '?')}: {p.get('root_cause', '?')}")


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
