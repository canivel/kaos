"""Paper benchmark dataset loaders.

Provides loaders for the datasets used in the Meta-Harness paper
(arXiv:2603.28052, Section 4):

- LawBench (215 classes) — criminal charges from case descriptions
- Symptom2Disease (22 classes) — diseases from symptom descriptions
- USPTO-50k (180 classes) — precursor reactants from product molecules

These loaders download from HuggingFace datasets or accept local files.
They wrap the TextClassifyBenchmark with the correct configuration.

Usage:
    from kaos.metaharness.benchmarks.paper_datasets import load_lawbench

    bench = load_lawbench()  # downloads or uses cached
    # or
    bench = load_lawbench(path="/data/lawbench.jsonl")
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import httpx

from kaos.metaharness.benchmarks import register_benchmark
from kaos.metaharness.benchmarks.text_classify import TextClassifyBenchmark

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "kaos" / "datasets"

# HuggingFace dataset endpoints (public datasets)
DATASET_URLS = {
    "lawbench": "https://huggingface.co/datasets/nguha/legalbench/resolve/main/data/abercrombie/base_task.json",
    "symptom2disease": "https://huggingface.co/datasets/gretelai/symptom2disease/resolve/main/data/train.jsonl",
    "uspto_50k": "https://huggingface.co/datasets/Chemformer/USPTO-50k/resolve/main/data/train.jsonl",
}


def _ensure_cache_dir() -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return CACHE_DIR


def _download_if_needed(name: str, url: str) -> Path:
    """Download a dataset to the cache directory if not already present."""
    cache_path = _ensure_cache_dir() / f"{name}.jsonl"
    if cache_path.exists():
        logger.info("Using cached dataset: %s", cache_path)
        return cache_path

    logger.info("Downloading %s from %s ...", name, url)
    try:
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            cache_path.write_bytes(response.content)
        logger.info("Downloaded %s (%d bytes)", name, len(response.content))
    except Exception as e:
        logger.warning("Failed to download %s: %s. Using synthetic data.", name, e)
        return cache_path  # Will fall back to synthetic

    return cache_path


def _load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file."""
    items = []
    with open(path) as f:
        for line in f:
            if line.strip():
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return items


def _load_json(path: Path) -> list[dict]:
    """Load a JSON file (array of objects)."""
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "data" in data:
        return data["data"]
    return [data]


def _normalize_text_label(items: list[dict], text_field: str, label_field: str) -> list[dict]:
    """Normalize dataset items to {"text": ..., "label": ...} format."""
    normalized = []
    for item in items:
        text = item.get(text_field, "")
        label = item.get(label_field, "")
        if text and label:
            normalized.append({"text": str(text), "label": str(label)})
    return normalized


def load_lawbench(
    path: str | None = None,
    search_size: int = 100,
    test_size: int = 100,
) -> TextClassifyBenchmark:
    """Load the LawBench dataset (criminal charges classification).

    215 classes. From the paper Section 4.1.

    Args:
        path: Local file path. If None, downloads from HuggingFace.
        search_size: Number of examples for the search set.
        test_size: Number of examples for the test set.
    """
    if path:
        dataset_path = path
    else:
        cache_path = _download_if_needed("lawbench", DATASET_URLS["lawbench"])
        dataset_path = str(cache_path)

    return TextClassifyBenchmark(
        dataset_path=dataset_path if Path(dataset_path).exists() else None,
        dataset_name="lawbench",
        search_size=search_size,
        test_size=test_size,
    )


def load_symptom2disease(
    path: str | None = None,
    search_size: int = 100,
    test_size: int = 100,
) -> TextClassifyBenchmark:
    """Load the Symptom2Disease dataset.

    22 classes. From the paper Section 4.1.

    Args:
        path: Local file path. If None, downloads from HuggingFace.
        search_size: Number of examples for the search set.
        test_size: Number of examples for the test set.
    """
    if path:
        dataset_path = path
    else:
        cache_path = _download_if_needed("symptom2disease", DATASET_URLS["symptom2disease"])
        dataset_path = str(cache_path)

    return TextClassifyBenchmark(
        dataset_path=dataset_path if Path(dataset_path).exists() else None,
        dataset_name="symptom2disease",
        search_size=search_size,
        test_size=test_size,
    )


def load_uspto50k(
    path: str | None = None,
    search_size: int = 100,
    test_size: int = 100,
) -> TextClassifyBenchmark:
    """Load the USPTO-50k dataset (precursor reactants classification).

    180 classes. From the paper Section 4.1.

    Args:
        path: Local file path. If None, downloads from HuggingFace.
        search_size: Number of examples for the search set.
        test_size: Number of examples for the test set.
    """
    if path:
        dataset_path = path
    else:
        cache_path = _download_if_needed("uspto_50k", DATASET_URLS["uspto_50k"])
        dataset_path = str(cache_path)

    return TextClassifyBenchmark(
        dataset_path=dataset_path if Path(dataset_path).exists() else None,
        dataset_name="uspto_50k",
        search_size=search_size,
        test_size=test_size,
    )


# Register paper benchmarks
register_benchmark("lawbench", lambda **kw: load_lawbench(**kw))
register_benchmark("symptom2disease", lambda **kw: load_symptom2disease(**kw))
register_benchmark("uspto_50k", lambda **kw: load_uspto50k(**kw))
