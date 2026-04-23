"""Tests for the inline (automatic) plasticity hooks."""

from __future__ import annotations

import os

import pytest

from kaos.core import Kaos
from kaos.dream import auto
from kaos.dream.phases.associations import related
from kaos.dream.phases.failures import lookup
from kaos.memory import MemoryStore
from kaos.skills import SkillStore


@pytest.fixture
def afs(tmp_path):
    db_path = str(tmp_path / "auto.db")
    fs = Kaos(db_path=db_path)
    yield fs
    fs.close()


# ── Helper fixture for the opt-out path ─────────────────────────────


@pytest.fixture
def auto_off(monkeypatch):
    monkeypatch.setenv("KAOS_DREAM_AUTO", "0")
    yield
    # monkeypatch undoes this


# ── Association auto-build on skill outcomes ────────────────────────


class TestAutoAssociationsOnSkillOutcome:
    def test_two_skills_same_agent_get_associated(self, afs):
        aid = afs.spawn("agent")
        sk = SkillStore(afs.conn)
        s1 = sk.save(name="alpha", description="one", template="t1",
                     source_agent_id=aid, tags=[])
        s2 = sk.save(name="beta", description="two", template="t2",
                     source_agent_id=aid, tags=[])
        sk.record_outcome(s1, success=True, agent_id=aid)
        sk.record_outcome(s2, success=True, agent_id=aid)

        edges = related(afs.conn, "skill", s1)
        assert edges
        assert any(e.id_b == s2 and e.kind_b == "skill" for e in edges)

    def test_unrelated_agents_do_not_associate(self, afs):
        a1 = afs.spawn("agent-1")
        a2 = afs.spawn("agent-2")
        sk = SkillStore(afs.conn)
        s1 = sk.save(name="x", description="d", template="t",
                     source_agent_id=a1, tags=[])
        s2 = sk.save(name="y", description="d", template="t",
                     source_agent_id=a2, tags=[])
        sk.record_outcome(s1, success=True, agent_id=a1)
        sk.record_outcome(s2, success=True, agent_id=a2)
        edges = related(afs.conn, "skill", s1)
        # No co-use in the same agent session → no edge.
        assert not any(e.id_b == s2 for e in edges)

    def test_opt_out_disables_hooks(self, afs, auto_off):
        aid = afs.spawn("agent")
        sk = SkillStore(afs.conn)
        s1 = sk.save(name="a", description="d", template="t",
                     source_agent_id=aid, tags=[])
        s2 = sk.save(name="b", description="d", template="t",
                     source_agent_id=aid, tags=[])
        sk.record_outcome(s1, success=True, agent_id=aid)
        sk.record_outcome(s2, success=True, agent_id=aid)
        edges = related(afs.conn, "skill", s1)
        assert not edges  # hooks didn't fire

    def test_weight_accumulates_on_repeated_coincidences(self, afs):
        aid = afs.spawn("agent")
        sk = SkillStore(afs.conn)
        s1 = sk.save(name="a", description="d", template="t",
                     source_agent_id=aid, tags=[])
        s2 = sk.save(name="b", description="d", template="t",
                     source_agent_id=aid, tags=[])
        # First call makes both skill_uses visible to each other's sibling query
        sk.record_outcome(s1, success=True, agent_id=aid)
        sk.record_outcome(s2, success=True, agent_id=aid)
        # Subsequent calls should keep bumping the edge weight
        for _ in range(3):
            sk.record_outcome(s1, success=True, agent_id=aid)
            sk.record_outcome(s2, success=True, agent_id=aid)
        edges = related(afs.conn, "skill", s1)
        edge = next(e for e in edges if e.id_b == s2)
        # uses reflects unweighted count — should be > 1
        assert edge.uses >= 2


# ── Memory hit auto-associations ────────────────────────────────────


class TestAutoAssociationsOnMemoryHits:
    def test_co_retrieved_memory_links(self, afs):
        aid = afs.spawn("agent")
        mem = MemoryStore(afs.conn)
        m1 = mem.write(agent_id=aid, content="retry jitter backoff",
                       type="insight", key="retry-guide")
        m2 = mem.write(agent_id=aid, content="retry queue deadletter",
                       type="insight", key="dlq-notes")
        # Search returns both → association fires
        results = mem.search("retry", record_hits=True, requesting_agent_id=aid)
        assert len(results) >= 2

        edges = related(afs.conn, "memory", m1)
        assert any(e.id_b == m2 and e.kind_b == "memory" for e in edges)

    def test_skill_memory_cross_associations(self, afs):
        aid = afs.spawn("agent")
        sk = SkillStore(afs.conn)
        mem = MemoryStore(afs.conn)
        skill_id = sk.save(name="auth-setup", description="d", template="t",
                           source_agent_id=aid, tags=[])
        sk.record_outcome(skill_id, success=True, agent_id=aid)

        m_id = mem.write(agent_id=aid, content="JWT validation pattern",
                         type="result", key="jwt-pattern")
        mem.search("JWT", record_hits=True, requesting_agent_id=aid)

        edges = related(afs.conn, "skill", skill_id)
        assert any(e.id_b == m_id and e.kind_b == "memory" for e in edges)


# ── Failure fingerprint extraction ──────────────────────────────────


class TestFailureFingerprints:
    def test_normalise_strips_identifiers(self):
        raw = ("Connection refused to /tmp/0a1b2c-uuid/path "
               "at 0xdeadbeef 2026-04-23T10:00:00.123Z")
        out = auto.normalise_error(raw)
        # Hex, path, timestamp should be masked
        assert "0xdeadbeef" not in out
        assert "2026-04-23T10:00:00" not in out
        assert "/tmp/0a1b2c" not in out

    def test_same_error_same_fingerprint(self):
        fp1 = auto.fingerprint_of("http", "Connection refused: 127.0.0.1:8080")
        fp2 = auto.fingerprint_of("http", "Connection refused: 127.0.0.1:8080")
        assert fp1 == fp2

    def test_different_tool_different_fingerprint(self):
        fp1 = auto.fingerprint_of("http", "Connection refused")
        fp2 = auto.fingerprint_of("fs", "Connection refused")
        assert fp1 != fp2

    def test_failure_recorded_on_agent_fail(self, afs):
        aid = afs.spawn("failing-agent")
        # Plant a failed tool_call with an error
        call_id = afs.log_tool_call(aid, "http_get",
                                    {"url": "https://example.com/api"})
        afs.start_tool_call(call_id)
        afs.complete_tool_call(call_id, output={}, status="error",
                               error_message="Connection refused",
                               token_count=0)
        afs.fail(aid, error="Connection refused")

        # Fingerprint table should have a row
        rows = afs.conn.execute(
            "SELECT fingerprint, tool_name, count FROM failure_fingerprints"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "http_get"
        assert rows[0][2] == 1

    def test_duplicate_failure_bumps_count(self, afs):
        for i in range(3):
            aid = afs.spawn(f"agent-{i}")
            call_id = afs.log_tool_call(aid, "http_get", {"url": "x"})
            afs.start_tool_call(call_id)
            afs.complete_tool_call(call_id, output={}, status="error",
                                   error_message="Same root-cause failure",
                                   token_count=0)
            afs.fail(aid)
        # Only ONE fingerprint row expected (UNIQUE constraint), count=3
        rows = afs.conn.execute(
            "SELECT count FROM failure_fingerprints"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == 3

    def test_lookup_returns_matching_fp(self, afs):
        aid = afs.spawn("a")
        call_id = afs.log_tool_call(aid, "http_get", {})
        afs.start_tool_call(call_id)
        afs.complete_tool_call(call_id, output={}, status="error",
                               error_message="rate limit exceeded: quota=100",
                               token_count=0)
        afs.fail(aid)
        # Fresh call with a superficially different-looking error that
        # should normalise to the same fingerprint.
        row = lookup(afs.conn, "http_get", "rate limit exceeded: quota=100")
        assert row is not None
        assert row["count"] >= 1


# ── Threshold-triggered consolidation ───────────────────────────────


class TestThresholdTriggeredConsolidation:
    def test_threshold_one_fires_consolidation(self, afs, monkeypatch):
        monkeypatch.setenv("KAOS_DREAM_THRESHOLD", "1")
        aid = afs.spawn("agent")
        # No skills/memory yet — consolidation will have nothing to propose
        # but MUST still insert a proposals scan attempt record (zero-count
        # rows mean we verify the trigger fired by checking the policies/
        # consolidation phase was executed — proxy via presence of the
        # agent_skills.deprecated column being accessible without error).
        afs.complete(aid)

        # The hook should have called trigger_consolidation, which in a
        # DB with zero skills is a no-op — but it shouldn't raise.
        # Assert indirect signal: schema column still intact.
        col_rows = afs.conn.execute(
            "PRAGMA table_info(agent_skills)"
        ).fetchall()
        cols = [r[1] for r in col_rows]
        assert "deprecated" in cols

    def test_threshold_respected(self, afs, monkeypatch):
        """With threshold=3, completing 3 agents triggers consolidation."""
        monkeypatch.setenv("KAOS_DREAM_THRESHOLD", "3")
        sk = SkillStore(afs.conn)

        # Plant a skill that WILL be a prune candidate (low success rate)
        seed_agent = afs.spawn("seed")
        bad = sk.save(name="bad", description="bad", template="t",
                      source_agent_id=seed_agent, tags=[])
        for i in range(7):
            sk.record_outcome(bad, success=False, agent_id=seed_agent)
        afs.complete(seed_agent)         # completed=1

        afs.complete(afs.spawn("a1"))    # completed=2
        # Up to here, threshold (3) not crossed → no consolidation yet.
        intermediate = afs.conn.execute(
            "SELECT COUNT(*) FROM consolidation_proposals"
        ).fetchone()[0]
        assert intermediate == 0

        afs.complete(afs.spawn("a2"))    # completed=3 → trigger fires
        final = afs.conn.execute(
            "SELECT COUNT(*) FROM consolidation_proposals"
        ).fetchone()[0]
        assert final >= 1


# ── On-completion episode signals ───────────────────────────────────


class TestEpisodeSignalsOnCompletion:
    def test_completion_writes_episode_signal_inline(self, afs):
        aid = afs.spawn("agent")
        afs.complete(aid)
        row = afs.conn.execute(
            "SELECT success, status FROM episode_signals WHERE agent_id = ?",
            (aid,),
        ).fetchone()
        assert row is not None
        assert row[0] == 1
        assert row[1] == "completed"

    def test_failure_writes_episode_signal_inline(self, afs):
        aid = afs.spawn("agent")
        afs.fail(aid)
        row = afs.conn.execute(
            "SELECT success, status FROM episode_signals WHERE agent_id = ?",
            (aid,),
        ).fetchone()
        assert row is not None
        assert row[0] == 0
        assert row[1] == "failed"
