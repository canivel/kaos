"""Surrogate Verifier — structured failure diagnostics for the proposer.

Inspired by EvoSkills (arXiv:2604.01687). After a harness is evaluated,
the verifier analyzes the results and produces:
1. Per-problem root-cause analysis
2. Pattern-level failure diagnosis
3. Actionable revision suggestions

Key design: the verifier is informationally isolated — it reads the task
description and harness OUTPUT but not the harness SOURCE CODE. This
prevents confirmation bias (rationalizing the code's approach instead
of judging output quality).

The verifier can work in two modes:
- LLM mode: uses the configured provider for deep analysis
- Heuristic mode: pattern matching when no LLM is available (default)
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class VerifierDiagnosis:
    """Structured failure diagnosis from the Surrogate Verifier."""

    harness_id: str
    total_problems: int = 0
    correct_count: int = 0
    wrong_count: int = 0

    # Pattern-level analysis
    failure_patterns: list[dict] = field(default_factory=list)
    # e.g. [{"pattern": "sports misclassified as technology", "count": 3, "root_cause": "missing sports keywords"}]

    # Per-problem diagnostics (top failures only)
    problem_diagnostics: list[dict] = field(default_factory=list)
    # e.g. [{"problem_id": "p4", "expected": "sports", "predicted": "technology", "root_cause": "..."}]

    # Actionable suggestions for the proposer
    suggestions: list[str] = field(default_factory=list)
    # e.g. ["Add 'team', 'player', 'coach' to sports keywords"]

    # Overall summary
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "harness_id": self.harness_id,
            "total_problems": self.total_problems,
            "correct_count": self.correct_count,
            "wrong_count": self.wrong_count,
            "accuracy": self.correct_count / max(self.total_problems, 1),
            "failure_patterns": self.failure_patterns,
            "problem_diagnostics": self.problem_diagnostics,
            "suggestions": self.suggestions,
            "summary": self.summary,
        }

    def to_text(self) -> str:
        """Format as text for the proposer digest."""
        lines = [f"**Verifier Diagnosis** ({self.correct_count}/{self.total_problems} correct)"]

        if self.failure_patterns:
            lines.append("Failure patterns:")
            for p in self.failure_patterns:
                lines.append(f"  - {p['pattern']} ({p['count']}x): {p.get('root_cause', '?')}")

        if self.suggestions:
            lines.append("Suggested fixes:")
            for s in self.suggestions:
                lines.append(f"  - {s}")

        if self.summary:
            lines.append(f"Summary: {self.summary}")

        return "\n".join(lines)


class SurrogateVerifier:
    """Analyzes harness evaluation results and produces structured diagnostics.

    Information isolation: the verifier sees task description + outputs,
    NOT the harness source code. This prevents confirmation bias.
    """

    def __init__(self, router=None):
        """
        Args:
            router: GEPARouter for LLM-based analysis. If None, uses heuristic mode.
        """
        self.router = router

    def diagnose(
        self,
        harness_id: str,
        per_problem: list[dict],
        benchmark_objectives: list[str] | None = None,
    ) -> VerifierDiagnosis:
        """Analyze evaluation results and produce a diagnosis.

        Args:
            harness_id: which harness was evaluated
            per_problem: list of per-problem results from the evaluator
            benchmark_objectives: e.g. ["+accuracy", "-context_cost"]

        Returns:
            VerifierDiagnosis with patterns, root causes, and suggestions.
        """
        diagnosis = VerifierDiagnosis(harness_id=harness_id)

        if not per_problem:
            diagnosis.summary = "No evaluation data available."
            return diagnosis

        diagnosis.total_problems = len(per_problem)
        diagnosis.correct_count = sum(1 for p in per_problem if p.get("correct"))
        diagnosis.wrong_count = diagnosis.total_problems - diagnosis.correct_count

        if diagnosis.wrong_count == 0:
            diagnosis.summary = "All problems correct. No failures to diagnose."
            return diagnosis

        # Separate failures
        failures = [p for p in per_problem if not p.get("correct")]
        successes = [p for p in per_problem if p.get("correct")]

        # Pattern analysis
        diagnosis.failure_patterns = self._extract_patterns(failures)

        # Per-problem diagnostics (top 5 most informative failures)
        diagnosis.problem_diagnostics = self._diagnose_problems(failures, successes)

        # Generate suggestions
        diagnosis.suggestions = self._generate_suggestions(
            diagnosis.failure_patterns,
            diagnosis.problem_diagnostics,
            failures,
            successes,
        )

        # Summary
        accuracy = diagnosis.correct_count / diagnosis.total_problems
        pattern_summary = ", ".join(
            f"{p['pattern']} ({p['count']}x)" for p in diagnosis.failure_patterns[:3]
        )
        diagnosis.summary = (
            f"{accuracy:.0%} accuracy. "
            f"Main failure patterns: {pattern_summary}. "
            f"{len(diagnosis.suggestions)} suggested fixes."
        )

        return diagnosis

    def _extract_patterns(self, failures: list[dict]) -> list[dict]:
        """Group failures into patterns."""
        patterns: dict[str, dict] = {}

        for f in failures:
            error = f.get("error", "")
            output = f.get("output", {})
            predicted = ""
            if isinstance(output, dict):
                predicted = str(output.get("prediction", ""))[:50]

            # Determine pattern key
            if error:
                # Error-based pattern
                error_type = error.split(":")[0] if ":" in error else error[:40]
                key = f"error: {error_type}"
            elif not predicted or predicted == "None":
                key = "empty prediction"
            else:
                # Wrong prediction pattern
                scores = f.get("scores", {})
                key = f"wrong prediction: '{predicted}'"

            if key not in patterns:
                patterns[key] = {"pattern": key, "count": 0, "examples": []}
            patterns[key]["count"] += 1
            if len(patterns[key]["examples"]) < 3:
                patterns[key]["examples"].append(f.get("problem_id", "?"))

        # Sort by frequency, add root cause analysis
        sorted_patterns = sorted(patterns.values(), key=lambda x: -x["count"])

        for p in sorted_patterns:
            p["root_cause"] = self._infer_root_cause(p)

        return sorted_patterns[:5]

    def _infer_root_cause(self, pattern: dict) -> str:
        """Heuristic root-cause inference from pattern."""
        pat = pattern["pattern"].lower()

        if "empty prediction" in pat:
            return "harness returns no prediction — likely missing 'prediction' key in output dict or LLM call failed silently"
        elif "error: connect" in pat:
            return "external API/service unreachable — harness depends on network call that fails"
        elif "error: timeout" in pat:
            return "LLM call or computation exceeded time limit"
        elif "error: syntax" in pat:
            return "generated code has syntax errors"
        elif "error: testfailed" in pat:
            return "generated code runs but produces wrong output for test cases"
        elif "error: key" in pat or "error: index" in pat:
            return "harness accesses a key/index that doesn't exist in the input"
        elif "wrong prediction" in pat:
            return "harness produces a prediction but it doesn't match the expected answer"
        else:
            return "unknown — examine the specific error messages"

    def _diagnose_problems(
        self,
        failures: list[dict],
        successes: list[dict],
    ) -> list[dict]:
        """Per-problem diagnostics for the most informative failures."""
        diagnostics = []

        for f in failures[:5]:
            diag: dict[str, Any] = {
                "problem_id": f.get("problem_id", "?"),
            }

            # What was predicted vs expected
            output = f.get("output", {})
            if isinstance(output, dict):
                diag["predicted"] = str(output.get("prediction", ""))[:100]
                diag["method"] = output.get("method", "unknown")
            diag["error"] = f.get("error", "")[:100] if f.get("error") else None

            # Compare with successes to find contrast
            if successes:
                success_methods = Counter(
                    s.get("output", {}).get("method", "?")
                    if isinstance(s.get("output"), dict) else "?"
                    for s in successes
                )
                most_common_success = success_methods.most_common(1)[0][0]
                fail_method = diag.get("method", "unknown")
                if fail_method != most_common_success and fail_method != "unknown":
                    diag["contrast"] = (
                        f"This problem used method '{fail_method}' but "
                        f"successful problems mostly used '{most_common_success}'"
                    )

            diagnostics.append(diag)

        return diagnostics

    def _generate_suggestions(
        self,
        patterns: list[dict],
        diagnostics: list[dict],
        failures: list[dict],
        successes: list[dict],
    ) -> list[str]:
        """Generate actionable revision suggestions."""
        suggestions = []

        accuracy = len(successes) / max(len(successes) + len(failures), 1)

        for p in patterns:
            pat = p["pattern"].lower()
            count = p["count"]

            if "empty prediction" in pat:
                suggestions.append(
                    f"Fix empty predictions ({count}x): ensure run() always returns "
                    f'{{"prediction": <value>}} — check that the LLM call succeeds '
                    f"and the response is parsed correctly"
                )
            elif "error: connect" in pat:
                suggestions.append(
                    f"Remove external API dependency ({count}x): use a local/heuristic "
                    f"approach instead of calling an external service"
                )
            elif "wrong prediction" in pat:
                # Extract what was predicted
                pred = pat.replace("wrong prediction: ", "").strip("'\"")
                suggestions.append(
                    f"Fix wrong predictions for '{pred}' ({count}x): "
                    f"the classification logic produces this label too often — "
                    f"check the decision boundary or keyword/feature overlap"
                )
            elif "error:" in pat:
                suggestions.append(
                    f"Fix runtime error ({count}x): {p.get('root_cause', 'examine error details')}"
                )

        # Overall strategy suggestion based on accuracy
        if accuracy == 0:
            suggestions.append(
                "CRITICAL: 0% accuracy — the harness is fundamentally broken. "
                "Start with the simplest possible approach (keyword matching, "
                "majority class) and verify it produces valid predictions before "
                "adding complexity."
            )
        elif accuracy < 0.5:
            suggestions.append(
                f"Low accuracy ({accuracy:.0%}): consider a different approach entirely. "
                f"Check if the successful predictions share a common method/strategy "
                f"and double down on that."
            )
        elif accuracy < 0.9:
            # Look for patterns in what succeeded vs what failed
            if diagnostics and any(d.get("contrast") for d in diagnostics):
                contrasts = [d["contrast"] for d in diagnostics if d.get("contrast")]
                suggestions.append(f"Near-miss: {contrasts[0]}")

        if not suggestions:
            suggestions.append("No specific suggestions — examine the failure patterns above.")

        return suggestions


def verify_evaluation(
    harness_id: str,
    per_problem: list[dict],
    router=None,
    objectives: list[str] | None = None,
) -> VerifierDiagnosis:
    """Convenience function: run the surrogate verifier on evaluation results."""
    verifier = SurrogateVerifier(router=router)
    return verifier.diagnose(harness_id, per_problem, objectives)
