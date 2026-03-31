"""Harness data model — candidates, evaluation results, and search configuration."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass, field, asdict
from typing import Any

import ulid


@dataclass
class HarnessCandidate:
    """A single harness candidate — a Python program that wraps an LLM."""

    harness_id: str
    source_code: str
    parent_ids: list[str] = field(default_factory=list)
    iteration: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def new_id() -> str:
        return str(ulid.new())

    @classmethod
    def create(
        cls,
        source_code: str,
        parent_ids: list[str] | None = None,
        iteration: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> HarnessCandidate:
        return cls(
            harness_id=cls.new_id(),
            source_code=source_code,
            parent_ids=parent_ids or [],
            iteration=iteration,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> HarnessCandidate:
        return cls(**data)

    def validate_interface(self) -> tuple[bool, str]:
        """Validate that the harness source defines a run(problem) callable.

        Returns (is_valid, error_message).
        """
        try:
            tree = ast.parse(self.source_code)
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "run":
                    args = node.args
                    # Must accept at least one argument (problem)
                    total_args = len(args.args) + len(args.posonlyargs)
                    if total_args >= 1:
                        return True, ""
                    return False, "run() must accept at least one argument (problem)"

        return False, "No run() function found in harness source"


@dataclass
class EvaluationResult:
    """Result of evaluating a harness candidate against a benchmark."""

    harness_id: str
    scores: dict[str, float]
    trace: list[dict[str, Any]] = field(default_factory=list)
    per_problem: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None

    @property
    def is_success(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> EvaluationResult:
        return cls(**data)

    def to_scores_json(self) -> str:
        return json.dumps(self.scores, indent=2)

    def to_trace_jsonl(self) -> str:
        return "\n".join(json.dumps(entry) for entry in self.trace)


@dataclass
class SearchConfig:
    """Configuration for a meta-harness search run."""

    benchmark: str  # "text_classify" | "math_rag" | "agentic_coding"
    max_iterations: int = 20
    candidates_per_iteration: int = 3
    seed_harnesses: list[str] = field(default_factory=list)
    proposer_model: str | None = None
    evaluator_model: str | None = None
    objectives: list[str] = field(default_factory=lambda: ["+accuracy", "-context_cost"])
    max_parallel_evals: int = 4
    eval_subset_size: int | None = None  # Subsample problems for faster search
    harness_timeout_seconds: int = 300

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SearchConfig:
        return cls(**data)

    def objective_directions(self) -> dict[str, str]:
        """Parse objectives into {name: 'maximize'|'minimize'}."""
        directions = {}
        for obj in self.objectives:
            if obj.startswith("-"):
                directions[obj[1:]] = "minimize"
            elif obj.startswith("+"):
                directions[obj[1:]] = "maximize"
            else:
                directions[obj] = "maximize"
        return directions
