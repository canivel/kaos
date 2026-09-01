"""Regression guards for the PFA probe (demo_process_flag_bench).

Guards: (1) lock hash frozen; (2) tampered locks refused; (3) stored
verdict recomputable from results.json; (4) REJECT disposition holds —
no process-flag auditor module may enter kaos/ on the v1 verdict;
(5) the blind-rendering leak guard actually scrubs.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from kaos.eval.harness import compute_verdict
from kaos.eval.harness.manifest import LockTamperError, load_lock

from demo_process_flag_bench.gates import (
    KNOWN_LOCK_SHA256, LOCK_PATH, compute_gates,
)
from demo_process_flag_bench.workload import leak_guard, _scrub

BENCH = Path(__file__).parent.parent / "benchmarks" / "demo_process_flag_bench"
FROZEN_SHA = "4f820f7354a3421a6e763c57fb14430e1696071a75cbd01167b8e12a89c01f2a"


def test_lock_hash_frozen():
    assert hashlib.sha256(LOCK_PATH.read_bytes()).hexdigest() == FROZEN_SHA
    assert FROZEN_SHA in KNOWN_LOCK_SHA256


def test_tampered_lock_refused(tmp_path):
    lock = json.loads(LOCK_PATH.read_text())
    lock["kill_gates"]["G1"]["threshold_pp"] = 1.0
    bad = tmp_path / "ISA.lock.json"
    bad.write_text(json.dumps(lock))
    with pytest.raises(LockTamperError):
        load_lock(bad, KNOWN_LOCK_SHA256)


def test_stored_verdict_recomputable():
    r = json.loads((BENCH / "results.json").read_text())
    pe = r["per_episode"]
    outcomes = compute_gates(
        n_failure=r["sample"]["n_failure"], n_completed=r["sample"]["n_completed"],
        parse_ok_rate=r["parse_ok_rate"], leak_guard_ok=True,
        full_flagged=[e["full"] for e in pe],
        det_flagged=[e["det"] for e in pe],
        rand_flagged=[e["rand"] for e in pe],
        failed=[e["failure_class"] for e in pe],
        evidence_resolved_rate=(r["evidence"]["resolved"] / r["evidence"]["instances"]),
        n_flag_instances=r["evidence"]["instances"],
    )
    assert compute_verdict(outcomes, judge_kappa=1.0, kappa_min=0.85) == r["verdict"]
    assert r["verdict"].startswith("REJECT")


def test_reject_disposition_no_shipping():
    for name in ("kaos.dream.process_flags", "kaos.process_flags",
                 "kaos.dream.phases.process_flags", "kaos.dream.auditor"):
        assert importlib.util.find_spec(name) is None, (
            f"{name} exists — a process-flag auditor shipped against the "
            f"v1 REJECT; a successor lock is required first"
        )


def test_leak_guard_scrubs_outcome_tokens():
    dirty = 'the run failed after agent_kill; status completed {"s": "agent_fail"}'
    assert not leak_guard(dirty)
    assert leak_guard(_scrub(dirty))
