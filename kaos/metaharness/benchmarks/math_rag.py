"""Retrieval-augmented math reasoning benchmark.

Implements the math reasoning evaluation from the Meta-Harness paper (Section 4.2).
Harnesses implement a retrieve-then-solve pattern over a corpus of solved math problems.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any

from kaos.metaharness.benchmarks import register_benchmark
from kaos.metaharness.benchmarks.base import Benchmark, Problem


SEED_NO_RETRIEVAL = '''\
"""No retrieval — solve the problem directly."""

def run(problem):
    """Attempt to solve the math problem with no retrieved examples."""
    question = problem["question"]

    prompt = (
        f"Solve the following math problem. Show your work step by step.\\n\\n"
        f"Problem: {question}\\n\\n"
        f"Solution:"
    )

    return {
        "prompt": prompt,
        "context_tokens": len(prompt.split()),
    }
'''

SEED_BM25_RETRIEVAL = '''\
"""BM25 retrieval — find similar problems from the corpus."""

def run(problem):
    """Retrieve similar problems using word overlap and solve."""
    question = problem["question"]
    corpus = problem.get("corpus", [])

    # Simple BM25-like scoring: word overlap
    query_words = set(question.lower().split())

    scored = []
    for doc in corpus:
        doc_words = set(doc["question"].lower().split())
        overlap = len(query_words & doc_words)
        total = len(query_words | doc_words) or 1
        score = overlap / total
        scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_k = [doc for _, doc in scored[:3]]

    examples_block = ""
    for ex in top_k:
        examples_block += (
            f"Example Problem: {ex['question']}\\n"
            f"Solution: {ex.get('solution', 'N/A')}\\n"
            f"Answer: {ex.get('answer', 'N/A')}\\n\\n"
        )

    prompt = (
        f"Here are some similar solved problems for reference:\\n\\n"
        f"{examples_block}"
        f"Now solve this problem. Show your work step by step.\\n\\n"
        f"Problem: {question}\\n\\n"
        f"Solution:"
    )

    return {
        "prompt": prompt,
        "context_tokens": len(prompt.split()),
    }
'''

SEED_CATEGORIZED_RETRIEVAL = '''\
"""Category-aware retrieval — route by math domain before retrieving."""

MATH_CATEGORIES = {
    "geometry": ["triangle", "circle", "angle", "polygon", "area", "perimeter",
                 "radius", "diameter", "tangent", "perpendicular"],
    "combinatorics": ["permutation", "combination", "counting", "probability",
                      "choose", "arrange", "ways", "factorial"],
    "number_theory": ["prime", "divisor", "modulo", "gcd", "lcm", "congruence",
                      "remainder", "factor", "integer"],
    "algebra": ["equation", "polynomial", "variable", "solve", "root",
                "inequality", "function", "quadratic"],
}

def classify_domain(question):
    """Classify a math problem into a domain."""
    q_lower = question.lower()
    scores = {}
    for domain, keywords in MATH_CATEGORIES.items():
        scores[domain] = sum(1 for kw in keywords if kw in q_lower)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "algebra"

def run(problem):
    """Retrieve examples from the same math domain, then solve."""
    question = problem["question"]
    corpus = problem.get("corpus", [])

    domain = classify_domain(question)

    # Filter corpus to same domain, fall back to all if too few
    domain_corpus = [
        doc for doc in corpus
        if classify_domain(doc["question"]) == domain
    ]
    if len(domain_corpus) < 3:
        domain_corpus = corpus

    # BM25-like scoring within domain
    query_words = set(question.lower().split())
    scored = []
    for doc in domain_corpus:
        doc_words = set(doc["question"].lower().split())
        overlap = len(query_words & doc_words)
        scored.append((overlap, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_k = [doc for _, doc in scored[:3]]

    examples_block = ""
    for ex in top_k:
        examples_block += (
            f"[{domain.upper()}] Problem: {ex['question']}\\n"
            f"Solution: {ex.get('solution', 'N/A')}\\n"
            f"Answer: {ex.get('answer', 'N/A')}\\n\\n"
        )

    prompt = (
        f"Domain: {domain}\\n\\n"
        f"Reference problems from the same domain:\\n\\n"
        f"{examples_block}"
        f"Now solve this problem step by step.\\n\\n"
        f"Problem: {question}\\n\\n"
        f"Solution:"
    )

    return {
        "prompt": prompt,
        "context_tokens": len(prompt.split()),
    }
'''


class MathRAGBenchmark(Benchmark):
    """Retrieval-augmented math reasoning benchmark.

    Loads math problems with optional corpus for retrieval.
    Dataset format (JSONL):
        {"question": "...", "answer": "42", "solution": "...", "domain": "algebra"}
    """

    def __init__(
        self,
        problems_path: str | None = None,
        corpus_path: str | None = None,
        search_size: int = 50,
        test_size: int = 50,
        corpus_size: int = 500,
        seed: int = 42,
    ):
        self._seed = seed
        self._search_size = search_size
        self._test_size = test_size

        if problems_path:
            self._problems = self._load_jsonl(problems_path)
        else:
            self._problems = self._synthetic_problems()

        if corpus_path:
            self._corpus = self._load_jsonl(corpus_path)[:corpus_size]
        else:
            self._corpus = self._synthetic_corpus()

        rng = random.Random(seed)
        shuffled = list(self._problems)
        rng.shuffle(shuffled)
        self._search_data = shuffled[:search_size]
        self._test_data = shuffled[search_size:search_size + test_size]

    @property
    def name(self) -> str:
        return "math_rag"

    @property
    def objectives(self) -> list[str]:
        return ["+accuracy", "-context_cost"]

    def get_search_set(self) -> list[Problem]:
        return self._to_problems(self._search_data)

    def get_test_set(self) -> list[Problem]:
        return self._to_problems(self._test_data)

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        predicted = str(output.get("prediction", "")).strip()
        expected = str(problem.expected).strip()

        # Normalize numeric answers
        try:
            correct = 1.0 if float(predicted) == float(expected) else 0.0
        except (ValueError, TypeError):
            correct = 1.0 if predicted.lower() == expected.lower() else 0.0

        context_cost = output.get("context_tokens", 0)
        return {"accuracy": correct, "context_cost": context_cost}

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_NO_RETRIEVAL, SEED_BM25_RETRIEVAL, SEED_CATEGORIZED_RETRIEVAL]

    def _to_problems(self, data: list[dict]) -> list[Problem]:
        return [
            Problem(
                problem_id=f"math_{i}",
                input={
                    "question": item["question"],
                    "corpus": self._corpus,
                },
                expected=item["answer"],
                metadata={"domain": item.get("domain", "unknown")},
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
    def _synthetic_problems() -> list[dict]:
        """Generate synthetic math problems for testing."""
        return [
            {"question": "What is 7 * 8?", "answer": "56", "domain": "algebra"},
            {"question": "Solve x^2 = 144", "answer": "12", "domain": "algebra"},
            {"question": "What is the area of a circle with radius 5?", "answer": "78.54", "domain": "geometry"},
            {"question": "How many ways to choose 3 items from 10?", "answer": "120", "domain": "combinatorics"},
            {"question": "What is the GCD of 48 and 36?", "answer": "12", "domain": "number_theory"},
            {"question": "Solve 2x + 5 = 17", "answer": "6", "domain": "algebra"},
            {"question": "What is the perimeter of a square with side 9?", "answer": "36", "domain": "geometry"},
            {"question": "What is 13 mod 5?", "answer": "3", "domain": "number_theory"},
            {"question": "Find the sum of first 10 natural numbers", "answer": "55", "domain": "algebra"},
            {"question": "How many prime numbers are less than 20?", "answer": "8", "domain": "number_theory"},
        ]

    @staticmethod
    def _synthetic_corpus() -> list[dict]:
        """Generate a synthetic retrieval corpus."""
        return [
            {"question": "What is 6 * 9?", "answer": "54", "solution": "6 * 9 = 54"},
            {"question": "Solve x^2 = 81", "answer": "9", "solution": "x = sqrt(81) = 9"},
            {"question": "Area of circle with radius 3?", "answer": "28.27", "solution": "pi * 3^2 = 28.27"},
            {"question": "Choose 2 from 5?", "answer": "10", "solution": "5! / (2! * 3!) = 10"},
            {"question": "GCD of 24 and 18?", "answer": "6", "solution": "Factors: 24={1,2,3,4,6,8,12,24}, 18={1,2,3,6,9,18}. GCD=6"},
        ]


register_benchmark("math_rag", MathRAGBenchmark)
