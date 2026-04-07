"""Harness data model — candidates, evaluation results, and search configuration."""

from __future__ import annotations

import ast
import asyncio
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

        Two-stage validation (per paper Appendix D, Tip 5):
        1. AST check: parse the source and verify run() exists with correct signature
        2. Smoke test: actually import and call run() on a tiny sample problem

        Returns (is_valid, error_message).
        """
        # Stage 1: AST check
        try:
            tree = ast.parse(self.source_code)
        except SyntaxError as e:
            return False, f"Syntax error: {e}"

        found_run = False
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "run":
                    args = node.args
                    total_args = len(args.args) + len(args.posonlyargs)
                    if total_args >= 1:
                        found_run = True
                        break
                    return False, "run() must accept at least one argument (problem)"

        if not found_run:
            return False, "No run() function found in harness source"

        # Stage 2: Smoke test — try to import the module and locate run()
        # This catches import-time crashes (bad dependencies, top-level errors)
        # but is lenient about runtime failures (async, class methods, etc.)
        try:
            import importlib.util
            module_name = f"_validate_{self.harness_id[:8]}"
            spec = importlib.util.spec_from_loader(module_name, loader=None)
            module = importlib.util.module_from_spec(spec)
            exec(compile(self.source_code, f"<validate:{self.harness_id[:8]}>", "exec"), module.__dict__)

            run_fn = getattr(module, "run", None)
            if run_fn is None:
                return False, "run() function not found after import"

            # Try calling with a minimal sample — but don't fail hard if the
            # function can't handle it (async, class method, domain-specific input)
            if callable(run_fn) and not asyncio.iscoroutinefunction(run_fn):
                try:
                    sample = {"text": "test", "labels": ["a", "b"], "labeled_examples": []}
                    result = run_fn(sample)
                    if result is not None and not isinstance(result, dict):
                        return False, f"run() must return a dict, got {type(result).__name__}"
                except TypeError:
                    pass  # Class method needs self, or different signature — OK if AST passed
                except Exception:
                    pass  # Domain-specific error — let full evaluation catch it

        except SyntaxError as e:
            return False, f"Import failed: {e}"
        except Exception as e:
            return False, f"Import failed: {type(e).__name__}: {e}"

        return True, ""


@dataclass
class EvaluationResult:
    """Result of evaluating a harness candidate against a benchmark."""

    harness_id: str
    scores: dict[str, float]
    trace: list[dict[str, Any]] = field(default_factory=list)
    per_problem: list[dict[str, Any]] = field(default_factory=list)
    duration_ms: int = 0
    error: str | None = None
    diagnosis: Any = None  # VerifierDiagnosis, attached after evaluation

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
    candidates_per_iteration: int = 2  # Paper uses k=2 for text classification
    seed_harnesses: list[str] = field(default_factory=list)
    proposer_model: str | None = None
    evaluator_model: str | None = None
    objectives: list[str] | None = None  # None = inherit from benchmark
    max_parallel_evals: int = 4
    eval_subset_size: int | None = None  # Subsample problems for faster search
    harness_timeout_seconds: int = 300
    proposer_timeout_seconds: int = 900  # 15 min max per proposer iteration
    compaction_level: int = 5  # 0 (no compaction) to 10 (maximum)
    max_prior_seeds: int = 5  # max prior discoveries to load as seeds

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> SearchConfig:
        return cls(**data)

    def objective_directions(self) -> dict[str, str]:
        """Parse objectives into {name: 'maximize'|'minimize'}."""
        objectives = self.objectives or ["+accuracy", "-context_cost"]
        directions = {}
        for obj in objectives:
            if obj.startswith("-"):
                directions[obj[1:]] = "minimize"
            elif obj.startswith("+"):
                directions[obj[1:]] = "maximize"
            else:
                directions[obj] = "maximize"
        return directions
