"""Tests for SharedLog.intent_auto — the policy consumer that closes the
loop between the `policies` table and the intent/vote/decide protocol.

Whitepaper §6.3a: v0.8.1 promoted approved intents into the policies table
but nothing consulted it at runtime. This module exercises the fix.
"""

from __future__ import annotations

import pytest

from kaos.core import Kaos
from kaos.dream.phases.policies import _normalise_action
from kaos.shared_log import SharedLog


@pytest.fixture
def afs(tmp_path, monkeypatch):
    monkeypatch.setenv("KAOS_DREAM_AUTO", "0")
    fs = Kaos(db_path=str(tmp_path / "p.db"))
    yield fs
    fs.close()


@pytest.fixture
def log(afs):
    return SharedLog(afs.conn)


@pytest.fixture
def agent_id(afs):
    return afs.spawn("a")


def _install_policy(
    conn,
    action_pattern: str,
    *,
    approval_rate: float = 0.9,
    sample_size: int = 12,
    enabled: int = 1,
) -> int:
    cur = conn.execute(
        "INSERT INTO policies (action_pattern, approval_rate, sample_size, "
        "enabled) VALUES (?, ?, ?, ?)",
        (_normalise_action(action_pattern), approval_rate, sample_size, enabled),
    )
    conn.commit()
    return cur.lastrowid


class TestIntentAutoFallthrough:
    def test_no_policy_returns_not_approved(self, log, agent_id):
        intent_id, auto = log.intent_auto(agent_id, "never-seen-before action")
        assert isinstance(intent_id, int) and intent_id > 0
        assert auto is False

    def test_disabled_policy_does_not_match(self, log, afs, agent_id):
        _install_policy(afs.conn, "run pytest suite", enabled=0)
        intent_id, auto = log.intent_auto(agent_id, "run pytest suite")
        assert auto is False


class TestIntentAutoApproval:
    def test_matching_policy_short_circuits(self, log, afs, agent_id):
        _install_policy(afs.conn, "run pytest suite")
        intent_id, auto = log.intent_auto(agent_id, "run pytest suite")
        assert auto is True

        # A synthetic approve vote exists
        votes = afs.conn.execute(
            "SELECT payload FROM shared_log WHERE type='vote' AND ref_id=?",
            (intent_id,),
        ).fetchall()
        assert len(votes) == 1

        # A decision exists and reports pass
        decision = afs.conn.execute(
            "SELECT payload FROM shared_log WHERE type='decision' AND ref_id=?",
            (intent_id,),
        ).fetchone()
        assert decision is not None
        import json
        assert json.loads(decision[0])["passed"] is True

    def test_case_insensitive_and_whitespace_tolerant(self, log, afs, agent_id):
        _install_policy(afs.conn, "deploy docs")
        _, auto = log.intent_auto(agent_id, "  DEPLOY\t docs  ")
        assert auto is True

    def test_applied_count_incremented(self, log, afs, agent_id):
        pid = _install_policy(afs.conn, "ship it")
        for _ in range(3):
            log.intent_auto(agent_id, "ship it")
        row = afs.conn.execute(
            "SELECT applied_count, last_applied_at FROM policies "
            "WHERE policy_id = ?", (pid,),
        ).fetchone()
        assert row[0] == 3
        assert row[1] is not None


class TestIntentAutoSafety:
    def test_standard_intent_unchanged(self, log, afs, agent_id):
        """intent() must still behave exactly like before — no vote, no decision."""
        intent_id = log.intent(agent_id, "do a thing")
        tally = log.tally(intent_id)
        assert tally.approve == 0 and tally.reject == 0
        decision = afs.conn.execute(
            "SELECT 1 FROM shared_log WHERE type='decision' AND ref_id=?",
            (intent_id,),
        ).fetchone()
        assert decision is None

    def test_missing_policies_table_is_safe(self, tmp_path):
        """Old databases without the policies table must not crash intent_auto."""
        fs = Kaos(db_path=str(tmp_path / "legacy.db"))
        try:
            aid = fs.spawn("legacy")
            fs.conn.execute("DROP TABLE policies")
            fs.conn.commit()
            log = SharedLog(fs.conn)
            intent_id, auto = log.intent_auto(aid, "anything")
            assert intent_id > 0
            assert auto is False
        finally:
            fs.close()
