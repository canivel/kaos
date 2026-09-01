"""Root conftest — make benchmarks/ importable.

The falsifiable-eval benchmark suites live under benchmarks/ (moved from the
repo root in v2.0) but keep their historical top-level module names
(``demo_action_realization_bench`` etc.) so the sha256-locked probe adapters,
their internal imports, and the experiments-journal references stay stable.
"""

import sys
from pathlib import Path

_BENCH = str(Path(__file__).resolve().parent / "benchmarks")
if _BENCH not in sys.path:
    sys.path.insert(0, _BENCH)
