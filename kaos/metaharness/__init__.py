"""Meta-Harness — automated harness optimization for LLMs.

Implements the Meta-Harness search loop (arXiv:2603.28052) using KAOS's
isolated agent VFS, event journal, and checkpoint system as the backing store.
"""

from kaos.metaharness.harness import HarnessCandidate, EvaluationResult, SearchConfig
from kaos.metaharness.pareto import ParetoFrontier, compute_pareto

__all__ = [
    "HarnessCandidate",
    "EvaluationResult",
    "SearchConfig",
    "ParetoFrontier",
    "compute_pareto",
]
