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
        from kaos.plugins import get_registry
        plugin_benchmarks = get_registry().benchmarks
        if name in plugin_benchmarks:
            return plugin_benchmarks[name](**kwargs)
        raise ValueError(
            f"Unknown benchmark: {name}. Available: "
            f"{list(_registry.keys()) + list(plugin_benchmarks.keys())}"
        )
    try:
        return _registry[name](**kwargs)
    except ImportError as e:
        raise ImportError(
            f"Benchmark '{name}' requires optional dependencies. "
            f"Install with: uv pip install 'kaos-harness[benchmarks]'\n"
            f"Original error: {e}"
        ) from e


def list_benchmarks() -> list[str]:
    return list(_registry.keys())
