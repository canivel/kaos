"""Task complexity classifier for GEPA routing."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kaos.router.vllm_client import VLLMClient

logger = logging.getLogger(__name__)

# Complexity levels
TRIVIAL = "trivial"
MODERATE = "moderate"
COMPLEX = "complex"
CRITICAL = "critical"

VALID_COMPLEXITIES = {TRIVIAL, MODERATE, COMPLEX, CRITICAL}

CLASSIFICATION_PROMPT = """\
Classify the complexity of this software engineering task into exactly one of: trivial, moderate, complex, critical.

Rules:
- trivial: Simple lookup, formatting, renaming, single-line fix
- moderate: Multi-step task, function implementation, test writing, bug fix
- complex: Refactoring, system design, multi-file changes, performance optimization
- critical: Architecture changes, security-critical, distributed systems, migration

Task: {task_description}
Context length: {context_length} characters
Available tools: {tool_count}

Respond with ONLY one word: trivial, moderate, complex, or critical."""


@dataclass
class ClassificationResult:
    """Result of task complexity classification."""

    complexity: str
    confidence: float
    reasoning: str | None = None


class HeuristicClassifier:
    """
    Rule-based task complexity classifier.

    Uses heuristics based on task description, context length, and tool count
    to route requests to the appropriate model tier. Used as a fast fallback
    when no LLM classifier endpoint is available.
    """

    COMPLEX_PATTERNS = [
        r"refactor",
        r"architect",
        r"design",
        r"implement.*system",
        r"migration",
        r"security",
        r"performance.*optim",
        r"debug.*complex",
        r"distributed",
        r"concurrent",
    ]

    MODERATE_PATTERNS = [
        r"implement",
        r"create.*function",
        r"write.*test",
        r"add.*feature",
        r"update",
        r"modify",
        r"fix.*bug",
        r"integrate",
    ]

    TRIVIAL_PATTERNS = [
        r"format",
        r"rename",
        r"comment",
        r"docstring",
        r"typo",
        r"import",
        r"simple",
        r"lookup",
        r"list",
    ]

    def classify(
        self,
        task_description: str,
        context_length: int = 0,
        tool_count: int = 0,
    ) -> ClassificationResult:
        """Classify task complexity using heuristics."""
        desc_lower = task_description.lower()
        score = 0.0

        for pattern in self.COMPLEX_PATTERNS:
            if re.search(pattern, desc_lower):
                score += 3.0
        for pattern in self.MODERATE_PATTERNS:
            if re.search(pattern, desc_lower):
                score += 1.5
        for pattern in self.TRIVIAL_PATTERNS:
            if re.search(pattern, desc_lower):
                score -= 1.0

        if context_length > 50000:
            score += 2.0
        elif context_length > 20000:
            score += 1.0

        if tool_count > 10:
            score += 1.0

        if len(task_description) > 500:
            score += 1.0
        elif len(task_description) > 200:
            score += 0.5

        if score >= 5.0:
            complexity = CRITICAL
        elif score >= 3.0:
            complexity = COMPLEX
        elif score >= 1.0:
            complexity = MODERATE
        else:
            complexity = TRIVIAL

        return ClassificationResult(
            complexity=complexity,
            confidence=min(0.9, 0.5 + abs(score) * 0.1),
            reasoning=f"heuristic_score={score:.1f}",
        )


class LLMClassifier:
    """
    LLM-based task complexity classifier.

    Calls a local vLLM instance directly via httpx to classify task complexity.
    Falls back to HeuristicClassifier on failure.

    No openai SDK. No litellm. No dspy. Just raw HTTP to your local model.
    """

    def __init__(self, client: VLLMClient, model: str):
        self.client = client
        self.model = model
        self._fallback = HeuristicClassifier()

    async def classify(
        self,
        task_description: str,
        context_length: int = 0,
        tool_count: int = 0,
    ) -> ClassificationResult:
        """Classify task complexity by asking the local LLM."""
        prompt = CLASSIFICATION_PROMPT.format(
            task_description=task_description[:500],
            context_length=context_length,
            tool_count=tool_count,
        )

        try:
            response = await self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                max_tokens=10,
            )

            raw = (response.choices[0].message.content or "").strip().lower()
            complexity = self._parse_complexity(raw)

            return ClassificationResult(
                complexity=complexity,
                confidence=0.85,
                reasoning=f"llm_raw={raw}",
            )
        except Exception as e:
            logger.warning("LLM classification failed, falling back to heuristics: %s", e)
            return self._fallback.classify(task_description, context_length, tool_count)

    @staticmethod
    def _parse_complexity(raw: str) -> str:
        """Extract a valid complexity level from LLM output."""
        for level in (CRITICAL, COMPLEX, MODERATE, TRIVIAL):
            if level in raw:
                return level
        return MODERATE
