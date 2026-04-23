"""Tests for consolidation + policies phases."""

from __future__ import annotations

import json

import pytest

from kaos.core import Kaos
from kaos.dream.phases.consolidation import (
    DEFAULT_MERGE_JACCARD_THRESHOLD,
    DEFAULT_PROMOTE_MIN_HITS,
    DEFAULT_PRUNE_MIN_USES,
    run as run_consolidation,
)
from kaos.dream.phases.policies import run as run_policies
from kaos.memory import MemoryStore
from kaos.shared_log import SharedLog
from kaos.skills import SkillStore


@pytest.fixture
def afs(tmp_path, monkeypatch):
    # Disable auto so we can observe the manual consolidation behavior
    # without threshold triggers interfering.
    monkeypatch.setenv("KAOS_DREAM_AUTO", "0")
    fs = Kaos(db_path=str(tmp_path / "c.db"))
    yield fs
    fs.close()


# ── Promotion ────────────────────────────────────────────────────────


class TestPromotion:
    def test_memory_with_enough_hits_proposed_for_promotion(self, afs):
        aid = afs.spawn("a")
        mem = MemoryStore(afs.conn)
        mid = mem.write(agent_id=aid, content="x", type="insight", key="hot-memory")
        # Directly insert memory_hits to bypass the auto hook (which is off)
        for _ in range(DEFAULT_PROMOTE_MIN_HITS):
            afs.conn.execute(
                "INSERT INTO memory_hits (memory_id, agent_id, query, rank_pos) "
                "VALUES (?, ?, ?, 1)", (mid, aid, "x")
            )
        afs.conn.commit()

        report = run_consolidation(afs.conn, dry_run=True)
        kinds = [p.kind for p in report.proposals]
        assert "promote" in kinds

    def test_promotion_apply_creates_skill(self, afs):
        aid = afs.spawn("a")
        mem = MemoryStore(afs.conn)
        mid = mem.write(agent_id=aid, content="Do X when Y",
                        type="insight", key="hot-memory")
        for _ in range(DEFAULT_PROMOTE_MIN_HITS):
            afs.conn.execute(
                "INSERT INTO memory_hits (memory_id, agent_id, query, rank_pos) "
                "VALUES (?, ?, ?, 1)", (mid, aid, "x")
            )
        afs.conn.commit()

        before = afs.conn.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0]
        run_consolidation(afs.conn, dry_run=False)
        after = afs.conn.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0]
        assert after == before + 1
        # The promoted skill carries the memory content as template
        row = afs.conn.execute(
            "SELECT name, template FROM agent_skills WHERE name = 'hot-memory'"
        ).fetchone()
        assert row is not None
        assert row[1] == "Do X when Y"


# ── Prune ────────────────────────────────────────────────────────────


class TestPrune:
    def test_low_success_skill_marked_deprecated(self, afs):
        aid = afs.spawn("a")
        sk = SkillStore(afs.conn)
        bad = sk.save(name="bad-skill", description="d", template="t",
                      source_agent_id=aid, tags=[])
        # 6 attempts, 1 success → 16.7% success rate, below the 40% threshold
        sk.record_outcome(bad, success=True, agent_id=aid)
        for _ in range(5):
            sk.record_outcome(bad, success=False, agent_id=aid)

        report = run_consolidation(afs.conn, dry_run=False)
        kinds = [p.kind for p in report.proposals]
        assert "prune" in kinds

        row = afs.conn.execute(
            "SELECT deprecated, deprecated_reason FROM agent_skills WHERE skill_id = ?",
            (bad,),
        ).fetchone()
        assert row[0] == 1
        assert row[1]  # reason non-empty

    def test_already_deprecated_not_re_pruned(self, afs):
        aid = afs.spawn("a")
        sk = SkillStore(afs.conn)
        bad = sk.save(name="bad", description="d", template="t",
                      source_agent_id=aid, tags=[])
        for _ in range(6):
            sk.record_outcome(bad, success=False, agent_id=aid)
        run_consolidation(afs.conn, dry_run=False)
        report = run_consolidation(afs.conn, dry_run=False)
        kinds = [p.kind for p in report.proposals]
        assert "prune" not in kinds  # skipped because already deprecated

    def test_high_success_skill_not_pruned(self, afs):
        aid = afs.spawn("a")
        sk = SkillStore(afs.conn)
        good = sk.save(name="good", description="d", template="t",
                       source_agent_id=aid, tags=[])
        for _ in range(10):
            sk.record_outcome(good, success=True, agent_id=aid)
        report = run_consolidation(afs.conn, dry_run=True)
        pruned_names = [p.targets.get("name") for p in report.proposals
                        if p.kind == "prune"]
        assert "good" not in pruned_names


# ── Merge ────────────────────────────────────────────────────────────


class TestMerge:
    def test_near_duplicate_skills_proposed_for_merge(self, afs):
        aid = afs.spawn("a")
        sk = SkillStore(afs.conn)
        sk.save(name="fastapi-payment-gateway",
                description="FastAPI payment gateway with idempotent handler",
                template="Build FastAPI payment gateway for {project}",
                source_agent_id=aid,
                tags=["fastapi", "payments"])
        sk.save(name="fastapi-payments-endpoint",
                description="FastAPI payments endpoint with idempotent handler",
                template="Build FastAPI payments endpoint for {project}",
                source_agent_id=aid,
                tags=["fastapi", "payments"])
        report = run_consolidation(afs.conn, dry_run=True,
                                   merge_threshold=0.6)
        merges = [p for p in report.proposals if p.kind == "merge"]
        assert merges

    def test_merge_never_auto_applied(self, afs):
        aid = afs.spawn("a")
        sk = SkillStore(afs.conn)
        sk.save(name="a-b-c-d",
                description="alpha beta gamma delta",
                template="t", source_agent_id=aid, tags=[])
        sk.save(name="a-b-c-e",
                description="alpha beta gamma epsilon",
                template="t", source_agent_id=aid, tags=[])
        before = afs.conn.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0]
        run_consolidation(afs.conn, dry_run=False)
        after = afs.conn.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0]
        # No auto-merge: skill count unchanged, nothing deprecated
        assert after == before


# ── Proposal journal ─────────────────────────────────────────────────


class TestProposalJournal:
    def test_every_proposal_persisted(self, afs):
        aid = afs.spawn("a")
        sk = SkillStore(afs.conn)
        bad = sk.save(name="bad", description="d", template="t",
                      source_agent_id=aid, tags=[])
        for _ in range(6):
            sk.record_outcome(bad, success=False, agent_id=aid)
        run_consolidation(afs.conn, dry_run=True)
        rows = afs.conn.execute(
            "SELECT kind, applied FROM consolidation_proposals"
        ).fetchall()
        assert rows
        # Dry run → no applied=1
        assert all(r[1] == 0 for r in rows)

    def test_applied_flag_set_in_apply_mode(self, afs):
        aid = afs.spawn("a")
        sk = SkillStore(afs.conn)
        bad = sk.save(name="bad", description="d", template="t",
                      source_agent_id=aid, tags=[])
        for _ in range(6):
            sk.record_outcome(bad, success=False, agent_id=aid)
        run_consolidation(afs.conn, dry_run=False)
        rows = afs.conn.execute(
            "SELECT kind, applied FROM consolidation_proposals "
            "WHERE kind = 'prune'"
        ).fetchall()
        assert any(r[1] == 1 for r in rows)


# ── Policies ─────────────────────────────────────────────────────────


class TestPolicies:
    def test_repeated_approved_intent_promoted(self, afs):
        """Three identical intents, all approved → policy emerges."""
        log = SharedLog(afs.conn)
        agents = [afs.spawn(f"a{i}") for i in range(3)]

        for aid in agents:
            intent_id = log.intent(aid, "migrate schema")
            log.vote(aid, intent_id, approve=True)
            log.decide(intent_id, aid)

        report = run_policies(afs.conn, dry_run=False)
        assert report.total_promoted == 1
        row = afs.conn.execute(
            "SELECT action_pattern, approval_rate, sample_size FROM policies"
        ).fetchone()
        assert row is not None
        assert "migrate schema" in row[0]
        assert row[1] == 1.0
        assert row[2] >= 3

    def test_policy_idempotent_across_runs(self, afs):
        log = SharedLog(afs.conn)
        agents = [afs.spawn(f"a{i}") for i in range(3)]
        for aid in agents:
            intent_id = log.intent(aid, "repeated action")
            log.vote(aid, intent_id, approve=True)
            log.decide(intent_id, aid)

        run_policies(afs.conn, dry_run=False)
        rows_before = afs.conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
        run_policies(afs.conn, dry_run=False)
        rows_after = afs.conn.execute("SELECT COUNT(*) FROM policies").fetchone()[0]
        assert rows_after == rows_before  # already known → skipped

    def test_low_approval_not_promoted(self, afs):
        log = SharedLog(afs.conn)
        agents = [afs.spawn(f"a{i}") for i in range(4)]
        for aid in agents:
            intent_id = log.intent(aid, "contested action")
            # Mixed votes below 90% threshold
            log.vote(aid, intent_id, approve=(aid == agents[0]))
            log.decide(intent_id, aid)

        report = run_policies(afs.conn, dry_run=False)
        assert report.total_promoted == 0

    def test_dry_run_does_not_persist(self, afs):
        log = SharedLog(afs.conn)
        agents = [afs.spawn(f"a{i}") for i in range(3)]
        for aid in agents:
            intent_id = log.intent(aid, "safe action")
            log.vote(aid, intent_id, approve=True)
            log.decide(intent_id, aid)

        report = run_policies(afs.conn, dry_run=True)
        persisted = afs.conn.execute(
            "SELECT COUNT(*) FROM policies"
        ).fetchone()[0]
        assert persisted == 0
        # But the report should still identify the candidate
        assert len(report.candidates) >= 1
