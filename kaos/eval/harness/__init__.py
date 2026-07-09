"""Falsifiable-eval harness primitives.

Public API:

    from kaos.eval.harness import (
        ArmResults, QueryResult, GateOutcome,
        bootstrap_diff_ci,
        load_lock, sha256_file,
        judge_arm,
        compute_verdict,
        Probe,
    )
"""

from kaos.eval.harness.types import ArmResults, QueryResult, GateOutcome
from kaos.eval.harness.stats import bootstrap_diff_ci, cluster_bootstrap_diff_ci, check_power_budget
from kaos.eval.harness.manifest import load_lock, sha256_file, LockTamperError
from kaos.eval.harness.judge import judge_arm
from kaos.eval.harness.verdict import compute_verdict
from kaos.eval.harness.probe import Probe

__all__ = [
    "ArmResults",
    "QueryResult",
    "GateOutcome",
    "bootstrap_diff_ci",
    "cluster_bootstrap_diff_ci",
    "check_power_budget",
    "load_lock",
    "sha256_file",
    "LockTamperError",
    "judge_arm",
    "compute_verdict",
    "Probe",
]
