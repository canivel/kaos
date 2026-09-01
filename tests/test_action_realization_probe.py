"""PR-4 (v0.9) — action-realization probe regression tests.

These tests don't try to reproduce the binding verdict (that requires
organic data and is captured in demo_action_realization_bench/VERDICT.md).
They guard against goalpost moves and harness drift:

  * the lock sha256 is the one pre-registered before any probe code
    existed (any future edit to ISA.lock.json must update KNOWN_LOCK_SHA256
    AND change this test);
  * the falsification self-test stays ADMISSIBLE — FULL := B1 emits
    [KILL: G1];
  * the workload sampler honours synthetic_fallback=NONE: with an empty
    DB it returns insufficient counts and is_sufficient flags VOID#1.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from kaos.eval.harness import LockTamperError, sha256_file
from kaos.schema import init_schema


PROBE_DIR = Path(__file__).resolve().parent.parent / \
    "benchmarks" / "demo_action_realization_bench"


def test_lock_sha256_is_pre_registered():
    """The lock file on disk must hash to the value pre-registered
    BEFORE any probe code was committed. Any change to the lock
    requires a new pre-registration commit + a new entry in
    gates.KNOWN_LOCK_SHA256."""
    from demo_action_realization_bench.gates import (
        LOCK_PATH, KNOWN_LOCK_SHA256,
    )
    h = sha256_file(LOCK_PATH)
    assert h in KNOWN_LOCK_SHA256, (
        f"Lock sha256 {h} not in pre-registered set "
        f"{set(KNOWN_LOCK_SHA256)}. The lock was edited without "
        f"a new pre-registration commit — this is a goalpost move."
    )


def test_lock_is_loadable_via_harness():
    """load_lock() returns the parsed dict and accepts the known hash."""
    from demo_action_realization_bench.gates import load
    lock = load()
    assert lock["name"] == "action-realization-probe"
    assert "kill_gates" in lock
    assert set(lock["kill_gates"]) == {"G1", "G2", "G3", "G4"}


def test_falsification_self_test_is_admissible():
    """FULL := B1 MUST emit [KILL: G1]. A harness that cannot kill
    is inadmissible per the lock."""
    from demo_action_realization_bench.falsify import main as falsify_main
    rc = falsify_main()
    assert rc == 0, "harness is INADMISSIBLE — feature cannot lose"


class TestWorkloadSampler:
    def test_empty_db_yields_insufficient_workload(self, tmp_path: Path):
        """Empty DB → VOID#1 (insufficient organic sample). Probe
        MUST NOT silently substitute synthetic data."""
        from demo_action_realization_bench.workload import sample_workload

        db = tmp_path / "empty.db"
        conn = sqlite3.connect(db)
        init_schema(conn)
        conn.close()

        wl = sample_workload(db)
        ok, msg = wl.is_sufficient
        assert not ok
        assert "VOID#1" in msg
        assert "synthetic substitution" in msg.lower() \
            or "synthetic substitution" in msg

    def test_missing_db_returns_empty_workload(self, tmp_path: Path):
        from demo_action_realization_bench.workload import sample_workload
        wl = sample_workload(tmp_path / "nope.db")
        assert len(wl.action) == 0
        assert len(wl.control) == 0
        assert len(wl.sanity) == 0

    def test_action_class_regex_classifies_known_signals(self):
        from demo_action_realization_bench.workload import (
            _ACTION_RATIONALE_RE,
        )
        # Positive signals
        for s in ("malformed JSON", "schema violation in args",
                  "unparseable input", "missing required arg",
                  "unexpected keyword argument 'raw'",
                  "unknown tool 'frobnicate'"):
            assert _ACTION_RATIONALE_RE.search(s), s
        # Negative signals (these are planning / memory / system)
        for s in ("ran out of context", "rate limit exceeded",
                  "network unreachable"):
            assert _ACTION_RATIONALE_RE.search(s) is None, s


class TestGatesTamperEvidence:
    def test_modified_lock_blocks_via_LockTamperError(self, tmp_path: Path,
                                                      monkeypatch):
        """If someone edits ISA.lock.json after results land, the
        harness must refuse to compute a verdict."""
        from demo_action_realization_bench import gates

        edited = tmp_path / "ISA.lock.json"
        edited.write_text('{"name":"tampered","kill_gates":{}}')

        monkeypatch.setattr(gates, "LOCK_PATH", edited)
        with pytest.raises(LockTamperError):
            gates.load()
