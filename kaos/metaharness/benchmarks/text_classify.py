"""Online text classification benchmark.

Implements the text classification evaluation from the Meta-Harness paper
(Section 4.1). An LLM receives labeled examples one at a time, updates its
memory/context, and classifies held-out test examples.

Supports LawBench, Symptom2Disease, USPTO-50k, and custom datasets.
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path
from typing import Any

from kaos.metaharness.benchmarks import register_benchmark
from kaos.metaharness.benchmarks.base import Benchmark, Problem


# ── Seed harnesses ────────────────────────────────────────────────

SEED_ZERO_SHOT = '''\
"""Zero-shot text classification harness."""

def run(problem):
    """Classify text with no examples — just the label set."""
    text = problem["text"]
    labels = problem.get("labels", [])
    label_str = ", ".join(labels) if labels else "the correct category"

    prompt = (
        f"Classify the following text into exactly one of these categories: {label_str}\\n"
        f"Output ONLY the category name, nothing else.\\n\\n"
        f"Text: {text}\\n\\n"
        f"Category:"
    )

    # Call LLM if available, otherwise return prompt for scoring
    try:
        response = llm(prompt, max_tokens=32)
        # Extract label from response
        r = response.strip().lower()
        prediction = ""
        for label in labels:
            if label.lower() in r:
                prediction = label
                break
        return {
            "prediction": prediction or response.strip(),
            "prompt": prompt,
            "context_tokens": len(prompt.split()),
        }
    except NameError:
        # llm() not available — return prompt only
        return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_FEW_SHOT = '''\
"""Few-shot text classification harness with example retrieval."""

def run(problem):
    """Classify text using the most recent labeled examples as context."""
    text = problem["text"]
    labels = problem.get("labels", [])
    labeled_examples = problem.get("labeled_examples", [])

    examples = labeled_examples[-8:] if labeled_examples else []

    example_block = ""
    for ex in examples:
        example_block += f"Text: {ex['text']}\\nCategory: {ex['label']}\\n\\n"

    label_str = ", ".join(labels) if labels else "the correct category"

    prompt = (
        f"Classify the following text into exactly one of these categories: {label_str}\\n"
        f"Output ONLY the category name, nothing else.\\n\\n"
        f"{example_block}"
        f"Text: {text}\\n\\n"
        f"Category:"
    )

    try:
        response = llm(prompt, max_tokens=32)
        r = response.strip().lower()
        prediction = ""
        for label in labels:
            if label.lower() in r:
                prediction = label
                break
        return {
            "prediction": prediction or response.strip(),
            "prompt": prompt,
            "context_tokens": len(prompt.split()),
        }
    except NameError:
        return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_RETRIEVAL = '''\
"""Retrieval-based text classification with nearest-neighbor examples."""

def run(problem):
    """Classify text using the most similar labeled examples."""
    text = problem["text"]
    labels = problem.get("labels", [])
    labeled_examples = problem.get("labeled_examples", [])

    query_words = set(text.lower().split())

    scored = []
    for ex in labeled_examples:
        ex_words = set(ex["text"].lower().split())
        overlap = len(query_words & ex_words)
        scored.append((overlap, ex))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_examples = [ex for _, ex in scored[:5]]

    example_block = ""
    for ex in top_examples:
        example_block += f"Text: {ex['text']}\\nCategory: {ex['label']}\\n\\n"

    label_str = ", ".join(labels) if labels else "the correct category"

    prompt = (
        f"Classify the following text into exactly one of these categories: {label_str}\\n"
        f"Output ONLY the category name, nothing else.\\n\\n"
        f"Examples:\\n{example_block}"
        f"Text: {text}\\n\\n"
        f"Category:"
    )

    try:
        response = llm(prompt, max_tokens=32)
        r = response.strip().lower()
        prediction = ""
        for label in labels:
            if label.lower() in r:
                prediction = label
                break
        return {
            "prediction": prediction or response.strip(),
            "prompt": prompt,
            "context_tokens": len(prompt.split()),
        }
    except NameError:
        return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''


class TextClassifyBenchmark(Benchmark):
    """Online text classification benchmark.

    Supports loading datasets from JSON or CSV files with format:
        [{"text": "...", "label": "..."}, ...]

    Or built-in synthetic datasets for testing.
    """

    def __init__(
        self,
        dataset_path: str | None = None,
        dataset_name: str = "custom",
        search_size: int = 100,
        test_size: int = 100,
        seed: int = 42,
    ):
        self._dataset_name = dataset_name
        self._seed = seed
        self._search_size = search_size
        self._test_size = test_size

        if dataset_path:
            self._data = self._load_dataset(dataset_path)
        else:
            self._data = self._synthetic_dataset()

        # Split into search and test sets
        rng = random.Random(seed)
        shuffled = list(self._data)
        rng.shuffle(shuffled)
        self._labels = sorted(set(item["label"] for item in self._data))
        self._search_data = shuffled[:search_size]
        self._test_data = shuffled[search_size:search_size + test_size]

    @property
    def name(self) -> str:
        return f"text_classify_{self._dataset_name}"

    @property
    def objectives(self) -> list[str]:
        return ["+accuracy", "-context_cost"]

    def get_search_set(self) -> list[Problem]:
        return self._to_problems(self._search_data)

    def get_test_set(self) -> list[Problem]:
        return self._to_problems(self._test_data)

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        predicted = str(output.get("prediction", "")).strip().lower()
        expected = str(problem.expected).strip().lower()
        correct = 1.0 if predicted == expected else 0.0
        context_cost = output.get("context_tokens", 0)
        return {"accuracy": correct, "context_cost": context_cost}

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_ZERO_SHOT, SEED_FEW_SHOT, SEED_RETRIEVAL]

    def _to_problems(self, data: list[dict]) -> list[Problem]:
        problems = []
        seen_so_far = []  # Simulates online learning — labeled examples seen before this one

        for i, item in enumerate(data):
            problems.append(Problem(
                problem_id=f"{self._dataset_name}_{i}",
                input={
                    "text": item["text"],
                    "labels": self._labels,
                    "labeled_examples": list(seen_so_far),  # Copy of examples seen so far
                },
                expected=item["label"],
                metadata={"index": i},
            ))
            seen_so_far.append({"text": item["text"], "label": item["label"]})

        return problems

    @staticmethod
    def _load_dataset(path: str) -> list[dict]:
        p = Path(path)
        if p.suffix == ".json":
            with open(p) as f:
                return json.load(f)
        elif p.suffix == ".csv":
            with open(p) as f:
                reader = csv.DictReader(f)
                return [{"text": row["text"], "label": row["label"]} for row in reader]
        elif p.suffix == ".jsonl":
            items = []
            with open(p) as f:
                for line in f:
                    if line.strip():
                        items.append(json.loads(line))
            return items
        else:
            raise ValueError(f"Unsupported format: {p.suffix}. Use .json, .jsonl, or .csv")

    @staticmethod
    def _synthetic_dataset() -> list[dict]:
        """Generate a synthetic dataset for testing."""
        categories = {
            "technology": [
                "The new GPU architecture delivers 3x faster inference",
                "Cloud computing costs continue to drop as competition increases",
                "Open source LLMs are catching up to proprietary models",
                "The compiler optimization reduces build times by 40 percent",
                "Distributed systems require careful handling of network partitions",
                "Container orchestration simplifies microservice deployment",
                "WebAssembly enables near-native performance in browsers",
                "Edge computing reduces latency for real-time applications",
            ],
            "science": [
                "The protein folding prediction matches experimental results",
                "Climate models show accelerating ice sheet melting patterns",
                "Gene therapy trials demonstrate promising safety profiles",
                "Quantum entanglement was observed at room temperature",
                "The telescope detected organic molecules in distant atmosphere",
                "Neural plasticity enables recovery after brain injuries",
                "Coral reef bleaching events are increasing in frequency",
                "Dark matter distribution maps reveal unexpected patterns",
            ],
            "business": [
                "Q3 revenue exceeded analyst expectations by 12 percent",
                "The merger creates the largest logistics company in the region",
                "Supply chain disruptions continue to impact manufacturing",
                "Remote work policies vary widely across the industry",
                "Startup funding rounds reached record levels this quarter",
                "Consumer spending shifted toward experiences over goods",
                "Interest rate changes affect mortgage application volumes",
                "International trade agreements reshape export markets",
            ],
            "sports": [
                "The championship series goes to a decisive seventh game",
                "The rookie quarterback set a new passing record this season",
                "Transfer window spending reached unprecedented levels",
                "The marathon world record was broken by twelve seconds",
                "Draft picks signal a rebuilding strategy for the franchise",
                "Injury prevention programs reduce ACL tears by 30 percent",
                "The tournament bracket produced several major upsets",
                "Olympic qualifying standards were revised for next games",
            ],
        }
        data = []
        for label, texts in categories.items():
            for text in texts:
                data.append({"text": text, "label": label})
        return data


# Register
register_benchmark("text_classify", TextClassifyBenchmark)
