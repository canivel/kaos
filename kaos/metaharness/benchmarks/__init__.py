"""Benchmark registry for meta-harness evaluation."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kaos.metaharness.benchmarks.base import Benchmark

_registry: dict[str, type[Benchmark]] = {}


def register_benchmark(name: str, cls: type[Benchmark]) -> None:
    _registry[name] = cls


def get_benchmark(name: str, **kwargs) -> Benchmark:
    if name not in _registry:
        raise ValueError(
            f"Unknown benchmark: {name}. Available: {list(_registry.keys())}"
        )
    try:
        return _registry[name](**kwargs)
    except ImportError as e:
        raise ImportError(
            f"Benchmark '{name}' requires optional dependencies. "
            f"Install with: uv pip install kaos[benchmarks]\n"
            f"Original error: {e}"
        ) from e


def list_benchmarks() -> list[str]:
    return list(_registry.keys())
