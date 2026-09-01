"""Regression guards for the GDL probe (demo_graphdiff_localizer_bench).

Guards: (1) the lock hash stays frozen; (2) tampered locks are refused;
(3) the falsification self-test stays admissible; (4) the stored verdict
is recomputable from results.json; (5) the DO-NOT-SHIP disposition and
bench-local containment hold — GDL must not enter kaos/ on the v1
verdict (vacuous G3; see VERDICT.md instrument-audit section).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from kaos.eval.harness import ArmResults, QueryResult, compute_verdict
from kaos.eval.harness.manifest import LockTamperError, load_lock

from demo_graphdiff_localizer_bench.gates import (
    KNOWN_LOCK_SHA256, LOCK_PATH, compute_gates,
)

BENCH = Path(__file__).parent.parent / "benchmarks" / "demo_graphdiff_localizer_bench"

FROZEN_SHA = "979127576a1196db60deb78df19d64b49f78118ab8274d1a37d2841554e2232c"


def test_lock_hash_frozen():
    actual = hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest()
    assert actual == FROZEN_SHA, (
        "ISA.lock.json content changed without a new pre-registration — "
        "this is a goalpost move; revert or register a v2 lock"
    )
    assert FROZEN_SHA in KNOWN_LOCK_SHA256


def test_tampered_lock_refused(tmp_path):
    lock = json.loads(LOCK_PATH.read_text())
    lock["kill_gates"]["G1"]["threshold_abs"] = 0.10  # the forbidden edit
    bad = tmp_path / "ISA.lock.json"
    bad.write_text(json.dumps(lock))
    with pytest.raises(LockTamperError):
        load_lock(bad, KNOWN_LOCK_SHA256)


def test_falsification_self_test_admissible():
    from demo_graphdiff_localizer_bench.falsify import main
    assert main() == 0, "harness can no longer kill the feature — INADMISSIBLE"


def test_stored_verdict_recomputable():
    results = json.loads((BENCH / "results.json").read_text())
    arms = {
        name: ArmResults(arm=name, per_query=[
            QueryResult(qid=q["qid"], qclass=q["qclass"],
                        correct=bool(q["correct"]), split=q.get("split", "in_dist"),
                        extras=q.get("extras", {}))
            for q in blob["per_query"]
        ])
        for name, blob in results["arms"].items()
    }
    outcomes = compute_gates(
        arms,
        organic_median_reuse=results["organic"]["median_reuse"],
        organic_n_agents=results["organic"]["n_agents"],
        pairing_same_family_rate=results["pairing_same_family_rate"],
    )
    verdict = compute_verdict(
        outcomes, judge_kappa=results["judge_kappa"], kappa_min=0.85,
    )
    assert verdict == results["verdict"]


def test_do_not_ship_disposition_recorded():
    text = (BENCH / "VERDICT.md").read_text(encoding="utf-8")
    assert "DO-NOT-SHIP" in text
    assert "vacuous" in text.lower() or "VACUOUS" in text


def test_gdl_stays_bench_local():
    """The v1 verdict does not license shipping: no graphdiff module may
    exist under kaos/ while this disposition stands."""
    for name in ("kaos.dream.graphdiff", "kaos.dream.phases.graphdiff",
                 "kaos.graphdiff"):
        assert importlib.util.find_spec(name) is None, (
            f"{name} exists — GDL shipped against the DO-NOT-SHIP "
            f"disposition; a v2 lock with a corrected G3 is required first"
        )
