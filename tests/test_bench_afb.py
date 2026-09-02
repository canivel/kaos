"""Agent Forensics Bench: lock integrity + runner smoke on a tiny session set."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
AFB = ROOT / "benchmarks" / "afb"
sys.path.insert(0, str(AFB))

import run_afb  # noqa: E402
from generate_session import fingerprint, generate_sessions  # noqa: E402


def test_lock_is_preregistered():
    from kaos.eval.harness.manifest import sha256_file
    assert sha256_file(AFB / "preregistration.json") in run_afb.KNOWN_LOCK_SHA256


def test_tampered_lock_is_refused(tmp_path, monkeypatch):
    from kaos.eval.harness import LockTamperError
    bad = tmp_path / "preregistration.json"
    bad.write_text(json.dumps({"gates": {"ACCEPT": "anything"}}))
    monkeypatch.setattr(run_afb, "LOCK_PATH", bad)
    with pytest.raises(LockTamperError):
        run_afb.load_lock()


def test_generator_is_seed_deterministic():
    a = generate_sessions(7, 3, 12)
    b = generate_sessions(7, 3, 12)
    assert fingerprint(a) == fingerprint(b)
    assert fingerprint(generate_sessions(8, 3, 12)) != fingerprint(a)
    for s in a:
        assert 0 <= s.culprit_index < s.error_index < len(s.steps)
        assert s.steps[s.culprit_index].tool == "fs_write"
        assert s.steps[s.error_index].expect_error


def test_runner_smoke_tiny(tmp_path):
    lock = run_afb.load_lock()
    small = dict(lock, generator=dict(lock["generator"], n_agents=3, k_steps=14,
                                      checkpoint_at=7, crash_offset=1))
    res = run_afb.run(small, str(tmp_path / "afb.db"))
    assert set(res["tests"]) == {"checkpoint_fidelity", "journal_completeness",
                                 "cross_agent_isolation", "fault_localization",
                                 "cold_start_replay", "mid_task_recovery"}
    assert res["verdict"].split(":")[0] in {"ACCEPT", "REJECT", "VOID"}
    assert res["tests"]["cross_agent_isolation"]["leaks"] == 0
    assert res["tests"]["checkpoint_fidelity"]["value"] == 1.0
