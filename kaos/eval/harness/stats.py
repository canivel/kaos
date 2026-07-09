"""Bootstrap CI helpers for the harness.

These are the only inferential statistics any KAOS gate uses. Keeping them
in one place — and seeded — guarantees that "lo > 0" means the same thing
across every probe.

Two levels of inference:

- ``bootstrap_diff_ci`` — resamples QUERIES within a single run. Captures
  sampling noise only. Valid when each condition was executed once and the
  claim is about this workload sample.
- ``cluster_bootstrap_diff_ci`` — resamples RUNS (clusters), for probes
  executed multiple times per condition. Single-run pass@1 varies 2.2-6.0pp
  between runs even at temperature 0 (arXiv:2602.07150), which is inside the
  margin of a +4pp gate — so a single-run CI can be confidently wrong about
  a run-to-run-unstable effect. The multi-run protocol: declare
  runs-per-condition in the ISA.lock BEFORE running, gate on the cluster CI,
  and VOID if fewer runs were executed than declared (power budget unmet).

Retroactive sensitivity note: neither prior binding verdict changes under the
multi-run lens — the synthesis-arc REJECT margins were far outside any
plausible run-to-run band, and the action-realization VOID#1 was an n-floor
decision, not an interval one. The NEXT close call is what this protects.
"""

from __future__ import annotations

import random


def bootstrap_diff_ci(
    a: list[int],
    b: list[int],
    *,
    iters: int = 2000,
    seed: int = 12345,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Two-sample bootstrap CI for mean(a) - mean(b).

    a, b are 0/1 label lists (e.g. correctness per query). Returns
    ``(mean_diff, lo, hi)`` for a symmetric (1-alpha) CI. Empty inputs
    return ``(0.0, 0.0, 0.0)`` so callers can treat empty arms as
    "no claim". The seed is fixed so the verdict is reproducible.
    """
    if not a or not b:
        return 0.0, 0.0, 0.0
    rng = random.Random(seed)
    n_a, n_b = len(a), len(b)
    diffs: list[float] = []
    for _ in range(iters):
        ra = sum(rng.choice(a) for _ in range(n_a)) / n_a
        rb = sum(rng.choice(b) for _ in range(n_b)) / n_b
        diffs.append(ra - rb)
    diffs.sort()
    md = sum(a) / n_a - sum(b) / n_b
    lo_idx = int((alpha / 2.0) * len(diffs))
    hi_idx = int((1.0 - alpha / 2.0) * len(diffs))
    lo = diffs[lo_idx]
    hi = diffs[min(hi_idx, len(diffs) - 1)]
    return md, lo, hi


def cluster_bootstrap_diff_ci(
    runs_a: list[list[int]],
    runs_b: list[list[int]],
    *,
    iters: int = 2000,
    seed: int = 12345,
    alpha: float = 0.05,
) -> tuple[float, float, float]:
    """Run-level (cluster) bootstrap CI for mean(a) - mean(b).

    ``runs_a`` / ``runs_b`` are lists of runs, each run a 0/1 label list
    (one entry per query). The bootstrap resamples RUNS with replacement —
    not queries — so the interval reflects run-to-run variance (decoding
    nondeterminism, provider drift, environment noise) in addition to
    within-run sampling noise. This is the statistic multi-run probe gates
    must use; a within-run CI on a single run understates uncertainty
    whenever runs disagree.

    Returns ``(mean_diff, lo, hi)`` for a symmetric (1-alpha) CI. Empty
    inputs (or runs with no labels) return ``(0.0, 0.0, 0.0)``. Seeded for
    verdict reproducibility.
    """
    runs_a = [r for r in runs_a if r]
    runs_b = [r for r in runs_b if r]
    if not runs_a or not runs_b:
        return 0.0, 0.0, 0.0

    def _run_means(runs: list[list[int]]) -> list[float]:
        return [sum(r) / len(r) for r in runs]

    means_a = _run_means(runs_a)
    means_b = _run_means(runs_b)
    md = sum(means_a) / len(means_a) - sum(means_b) / len(means_b)

    rng = random.Random(seed)
    n_a, n_b = len(means_a), len(means_b)
    diffs: list[float] = []
    for _ in range(iters):
        ra = sum(rng.choice(means_a) for _ in range(n_a)) / n_a
        rb = sum(rng.choice(means_b) for _ in range(n_b)) / n_b
        diffs.append(ra - rb)
    diffs.sort()
    lo_idx = int((alpha / 2.0) * len(diffs))
    hi_idx = min(int((1.0 - alpha / 2.0) * len(diffs)), len(diffs) - 1)
    return md, diffs[lo_idx], diffs[hi_idx]


def check_power_budget(lock: dict, runs_executed: dict[str, int]) -> str | None:
    """Enforce a pre-registered multi-run power budget.

    If the ISA.lock declares::

        "statistics": {"runs_per_condition": N, "interval": "cluster_bootstrap"}

    then every arm in ``runs_executed`` must have at least N runs. Returns a
    VOID reason string when the budget is unmet, else None. Locks WITHOUT a
    statistics block are single-run probes (the pre-v0.10 protocol) and pass.
    A declared budget is binding the same way gates are: running fewer
    repetitions than pre-registered voids the verdict rather than quietly
    weakening the interval.
    """
    stats_block = lock.get("statistics") or {}
    required = int(stats_block.get("runs_per_condition", 1) or 1)
    if required <= 1:
        return None
    short = {arm: n for arm, n in runs_executed.items() if n < required}
    if short:
        detail = ", ".join(f"{arm}={n}" for arm, n in sorted(short.items()))
        return (
            f"VOID: power budget unmet — lock requires "
            f"{required} runs/condition, got: {detail}"
        )
    return None
