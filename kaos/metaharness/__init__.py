"""Meta-Harness — automated harness optimization for LLMs.

Implements the Meta-Harness search loop (arXiv:2603.28052) using KAOS's
isolated agent VFS, event journal, and checkpoint system as the backing store.

Paper: https://yoonholee.com/meta-harness/
Original code: https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact
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
