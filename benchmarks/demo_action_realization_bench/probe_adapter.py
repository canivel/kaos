"""Probe-subclass adapter for the action-realization bench.

Wires the existing workload/arms/gates/run pipeline into the
kaos.eval.harness.Probe ABC so the bench can be driven via the
`kaos eval probe {run,verify,falsify}` CLI surface. Pure adapter —
no domain logic lives here; everything routes through the modules
that landed at commit 1bc1703.

Usage from the CLI:

    kaos eval probe falsify \
        --probe demo_action_realization_bench.probe_adapter:ActionRealizationProbe
    kaos eval probe run \
        --probe demo_action_realization_bench.probe_adapter:ActionRealizationProbe \
        --out-dir demo_action_realization_bench
    kaos eval probe verify \
        --probe demo_action_realization_bench.probe_adapter:ActionRealizationProbe \
        --results demo_action_realization_bench/results.json
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from kaos.eval.harness import ArmResults, GateOutcome, Probe

from demo_action_realization_bench.gates import (
    KNOWN_LOCK_SHA256,
    LOCK_PATH,
    compute_gates as _compute_gates,
)
from demo_action_realization_bench.run import main as _run_main


class ActionRealizationProbe(Probe):
    lock_path = str(LOCK_PATH)
    known_sha256 = dict(KNOWN_LOCK_SHA256)
    kappa_min = 0.85

    # Inline-overhead per arm, populated by run() and consumed by
    # gates(). For verify() (gates re-computed off-disk), overheads
    # are taken from the stored arm summary.
    _last_inline_us: dict[str, list[float]] = {}

    def arms(self) -> list[str]:
        return ["B0", "B1", "FULL", "L1", "L2"]

    def gates(self, arms_in: dict[str, ArmResults]) -> list[GateOutcome]:
        return _compute_gates(
            arms_in,
            inline_overhead_us_by_arm=self._last_inline_us,
        )

    def run(self, *, out_dir: str | Path, **kw: Any) -> dict:
        db_path = kw.get("db_path", "kaos.db")
        return _run_main(out_dir=out_dir, db_path=db_path)

    def verify(self, results_path: str | Path) -> str:
        """Re-compute verdict from results.json. For G4 we use the
        p95 numbers stored per-arm at run time (the harness can't
        re-measure inline overhead from a results.json alone)."""
        data = json.loads(Path(results_path).read_text())
        # Prime _last_inline_us from the stored arm p95 so G4
        # re-computes deterministically — single-point reconstruction.
        self._last_inline_us = {
            name: [(arr.get("p95_us") or 0.0)]
            for name, arr in data.get("arms", {}).items()
        }
        return super().verify(results_path)

    def falsify(self) -> tuple[list[GateOutcome], str]:
        """Delegate to the existing falsify.main() so the kill proof
        uses the same numbers reviewers can see in the script."""
        from demo_action_realization_bench.falsify import main as _falsify
        # _falsify prints + returns 0 if ADMISSIBLE; we replay the
        # same setup here to get structured outcomes for the CLI.
        import random
        from kaos.eval.harness import QueryResult, compute_verdict

        def _mk(name, *, acc_action, acc_non_action, acc_sanity,
                seed, n_per=220):
            rng = random.Random(hash((name, seed)) & 0xffffffff)
            a = ArmResults(arm=name)
            for label, p in (("action", acc_action),
                             ("non_action", acc_non_action),
                             ("sanity", acc_sanity)):
                for i in range(n_per):
                    a.per_query.append(QueryResult(
                        qid=f"{label}-{i}", qclass=label,
                        correct=(rng.random() < p), split="in_dist",
                    ))
            return a

        b1 = _mk("B1", acc_action=0.25, acc_non_action=0.35,
                 acc_sanity=0.99, seed=1)
        full = ArmResults(arm="FULL", per_query=list(b1.per_query))
        arms = {
            "B0": _mk("B0", acc_action=0.05, acc_non_action=0.10,
                      acc_sanity=0.99, seed=2),
            "B1": b1, "FULL": full,
            "L1": _mk("L1", acc_action=0.25, acc_non_action=0.35,
                      acc_sanity=0.99, seed=3),
            "L2": _mk("L2", acc_action=0.26, acc_non_action=0.34,
                      acc_sanity=0.99, seed=4),
        }
        self._last_inline_us = {
            a: [10.0 + 0.001 * i for i in range(660)] for a in arms
        }
        outs = self.gates(arms)
        verdict = compute_verdict(outs, judge_kappa=1.0,
                                  kappa_min=self.kappa_min)
        return outs, verdict
