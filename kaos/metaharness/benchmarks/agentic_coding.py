"""Agentic coding benchmark (TerminalBench-style).

Implements the agentic coding evaluation from the Meta-Harness paper (Section 4.3).
Harnesses are agentic systems that solve coding tasks using shell execution,
file I/O, and multi-step reasoning.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from kaos.metaharness.benchmarks import register_benchmark
from kaos.metaharness.benchmarks.base import Benchmark, Problem


SEED_DIRECT = '''\
"""Direct coding harness — solve the task in one shot."""

def run(problem):
    """Generate a solution directly from the task description."""
    task = problem["task"]
    language = problem.get("language", "python")

    prompt = (
        f"You are an expert programmer. Solve the following task.\\n\\n"
        f"Task: {task}\\n\\n"
        f"Language: {language}\\n\\n"
        f"Write the complete solution:"
    )

    return {
        "prompt": prompt,
        "context_tokens": len(prompt.split()),
    }
'''

SEED_PLAN_THEN_CODE = '''\
"""Plan-then-code harness — decompose the task before coding."""

def run(problem):
    """First plan the approach, then write the solution."""
    task = problem["task"]
    language = problem.get("language", "python")
    constraints = problem.get("constraints", "")

    constraint_block = f"\\nConstraints: {constraints}" if constraints else ""

    prompt = (
        f"You are an expert programmer. Solve this task step by step.\\n\\n"
        f"Task: {task}{constraint_block}\\n\\n"
        f"Language: {language}\\n\\n"
        f"First, outline your approach in 3-5 steps.\\n"
        f"Then write the complete solution.\\n\\n"
        f"## Plan\\n"
    )

    return {
        "prompt": prompt,
        "context_tokens": len(prompt.split()),
    }
'''

SEED_ENV_AWARE = '''\
"""Environment-aware coding harness — gather env info before solving.

Inspired by the Meta-Harness paper's key finding on TerminalBench-2:
gathering an environment snapshot before the agent loop eliminates
2-4 wasted exploratory turns.
"""

def run(problem):
    """Gather environment info, then solve the task."""
    task = problem["task"]
    language = problem.get("language", "python")
    env_info = problem.get("environment", {})

    env_block = ""
    if env_info:
        env_block = "\\n[Environment Snapshot]\\n"
        for key, value in env_info.items():
            env_block += f"  {key}: {value}\\n"
        env_block += "\\n"

    prompt = (
        f"You are an expert programmer working in a sandboxed environment.\\n"
        f"{env_block}"
        f"Task: {task}\\n\\n"
        f"Language: {language}\\n\\n"
        f"Write the complete solution, accounting for the available "
        f"tools and environment:\\n"
    )

    return {
        "prompt": prompt,
        "context_tokens": len(prompt.split()),
    }
'''


class AgenticCodingBenchmark(Benchmark):
    """Agentic coding benchmark (TerminalBench-style).

    Tasks are coding problems that may require:
    - File I/O, shell commands, package installation
    - Multi-step reasoning and debugging
    - Environment awareness (available tools, languages, memory)

    Dataset format (JSONL):
        {"task": "...", "language": "python", "test_cmd": "pytest test.py",
         "expected_output": "...", "difficulty": "medium"}
    """

    def __init__(
        self,
        tasks_path: str | None = None,
        search_size: int = 30,
        test_size: int = 30,
        seed: int = 42,
    ):
        self._seed = seed

        if tasks_path:
            self._tasks = self._load_jsonl(tasks_path)
        else:
            self._tasks = self._synthetic_tasks()

        rng = random.Random(seed)
        shuffled = list(self._tasks)
        rng.shuffle(shuffled)
        self._search_data = shuffled[:search_size]
        self._test_data = shuffled[search_size:search_size + test_size]

    @property
    def name(self) -> str:
        return "agentic_coding"

    @property
    def objectives(self) -> list[str]:
        return ["+pass_rate"]

    def get_search_set(self) -> list[Problem]:
        return self._to_problems(self._search_data)

    def get_test_set(self) -> list[Problem]:
        return self._to_problems(self._test_data)

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        # Binary pass/fail based on expected output match
        predicted = str(output.get("prediction", "")).strip()
        expected = str(problem.expected).strip()

        if expected and predicted:
            passed = 1.0 if expected.lower() in predicted.lower() else 0.0
        else:
            passed = 0.0

        return {"pass_rate": passed}

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_DIRECT, SEED_PLAN_THEN_CODE, SEED_ENV_AWARE]

    def _to_problems(self, data: list[dict]) -> list[Problem]:
        return [
            Problem(
                problem_id=f"coding_{i}",
                input={
                    "task": item["task"],
                    "language": item.get("language", "python"),
                    "constraints": item.get("constraints", ""),
                    "environment": item.get("environment", {
                        "python": "3.12",
                        "pip": "available",
                        "memory": "4GB",
                    }),
                },
                expected=item.get("expected_output", ""),
                metadata={
                    "difficulty": item.get("difficulty", "medium"),
                },
            )
            for i, item in enumerate(data)
        ]

    @staticmethod
    def _load_jsonl(path: str) -> list[dict]:
        items = []
        with open(path) as f:
            for line in f:
                if line.strip():
                    items.append(json.loads(line))
        return items

    @staticmethod
    def _synthetic_tasks() -> list[dict]:
        """Generate synthetic coding tasks for testing."""
        return [
            {
                "task": "Write a function that checks if a string is a palindrome",
                "language": "python",
                "expected_output": "def is_palindrome",
                "difficulty": "easy",
            },
            {
                "task": "Implement a binary search on a sorted array",
                "language": "python",
                "expected_output": "def binary_search",
                "difficulty": "easy",
            },
            {
                "task": "Write a function to find the longest common subsequence of two strings",
                "language": "python",
                "expected_output": "def lcs",
                "difficulty": "medium",
            },
            {
                "task": "Implement a simple HTTP server that returns JSON on GET /health",
                "language": "python",
                "expected_output": "health",
                "difficulty": "medium",
            },
            {
                "task": "Write a shell script that finds all files larger than 10MB in /tmp",
                "language": "bash",
                "expected_output": "find",
                "difficulty": "easy",
            },
            {
                "task": "Implement a thread-safe counter class with increment and get methods",
                "language": "python",
                "expected_output": "class Counter",
                "difficulty": "medium",
            },
            {
                "task": "Write a function that parses a cron expression and returns the next run time",
                "language": "python",
                "expected_output": "def next_run",
                "difficulty": "hard",
            },
            {
                "task": "Implement a simple key-value store with get, set, and delete over TCP",
                "language": "python",
                "expected_output": "socket",
                "difficulty": "hard",
            },
        ]


register_benchmark("agentic_coding", AgenticCodingBenchmark)
