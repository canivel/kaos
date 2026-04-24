"""Tests for the human-in-the-loop merge workflow.

Whitepaper §6.3b: v0.8.1 generated merge proposals but never applied them.
This module exercises list_pending_merges / accept_merge / reject_merge.
"""

from __future__ import annotations

import json

import pytest

from kaos.core import Kaos
from kaos.dream.phases.consolidation import (
    accept_merge,
    list_pending_merges,
    reject_merge,
    run as run_consolidation,
)
from kaos.skills import SkillStore


@pytest.fixture
def afs(tmp_path, monkeypatch):
    monkeypatch.setenv("KAOS_DREAM_AUTO", "0")
    fs = Kaos(db_path=str(tmp_path / "m.db"))
    yield fs
    fs.close()


def _make_duplicate_pair(afs) -> tuple[int, int]:
    aid = afs.spawn("a")
    sk = SkillStore(afs.conn)
    s1 = sk.save(name="fastapi-payment-gateway",
                 description="FastAPI payment gateway with idempotent handler",
                 template="Build FastAPI payment gateway for {project}",
                 source_agent_id=aid,
                 tags=["fastapi", "payments"])
    s2 = sk.save(name="fastapi-payments-endpoint",
                 description="FastAPI payments endpoint with idempotent handler",
                 template="Build FastAPI payments endpoint for {project}",
                 source_agent_id=aid,
                 tags=["fastapi", "payments"])
    # Record some uses so telemetry migrates measurably
    sk.record_outcome(s1, success=True, agent_id=aid)
    sk.record_outcome(s1, success=True, agent_id=aid)
    sk.record_outcome(s2, success=True, agent_id=aid)
    sk.record_outcome(s2, success=False, agent_id=aid)
    # Generate the merge proposal
    report = run_consolidation(afs.conn, dry_run=False, merge_threshold=0.6)
    assert any(p.kind == "merge" for p in report.proposals)
    return s1, s2


def _pending_merge_id(conn) -> int:
    rows = list_pending_merges(conn)
    assert rows, "expected at least one pending merge proposal"
    return rows[0]["proposal_id"]


class TestListPendingMerges:
    def test_returns_pending_only(self, afs):
        _make_duplicate_pair(afs)
        rows = list_pending_merges(afs.conn)
        assert rows
        assert all(r.get("proposal_id") for r in rows)
        assert all(r["targets"].get("skill_ids") for r in rows)

    def test_excludes_applied_and_rejected(self, afs):
        _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)
        assert list_pending_merges(afs.conn) == []

    def test_empty_on_fresh_db(self, afs):
        assert list_pending_merges(afs.conn) == []


class TestAcceptMerge:
    def test_keeps_lower_id_by_default(self, afs):
        s1, s2 = _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        result = accept_merge(afs.conn, pid)
        assert result["status"] == "applied"
        assert result["kept_skill_id"] == min(s1, s2)
        assert result["retired_skill_id"] == max(s1, s2)

    def test_explicit_keep_honored(self, afs):
        s1, s2 = _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        result = accept_merge(afs.conn, pid, keep_skill_id=max(s1, s2))
        assert result["kept_skill_id"] == max(s1, s2)
        assert result["retired_skill_id"] == min(s1, s2)

    def test_skill_uses_migrated(self, afs):
        s1, s2 = _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)
        # All skill_uses now attributed to the keeper
        keep = min(s1, s2)
        retire = max(s1, s2)
        retired_uses = afs.conn.execute(
            "SELECT COUNT(*) FROM skill_uses WHERE skill_id = ?", (retire,),
        ).fetchone()[0]
        kept_uses = afs.conn.execute(
            "SELECT COUNT(*) FROM skill_uses WHERE skill_id = ?", (keep,),
        ).fetchone()[0]
        assert retired_uses == 0
        assert kept_uses > 0

    def test_counters_rolled_into_keeper(self, afs):
        s1, s2 = _make_duplicate_pair(afs)
        keep = min(s1, s2)
        # Totals before merge
        total_uses = afs.conn.execute(
            "SELECT SUM(use_count) FROM agent_skills WHERE skill_id IN (?, ?)",
            (s1, s2),
        ).fetchone()[0]
        total_success = afs.conn.execute(
            "SELECT SUM(success_count) FROM agent_skills WHERE skill_id IN (?, ?)",
            (s1, s2),
        ).fetchone()[0]

        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)

        kept_row = afs.conn.execute(
            "SELECT use_count, success_count FROM agent_skills WHERE skill_id = ?",
            (keep,),
        ).fetchone()
        assert kept_row[0] == total_uses
        assert kept_row[1] == total_success

    def test_retired_skill_soft_deleted(self, afs):
        s1, s2 = _make_duplicate_pair(afs)
        retire = max(s1, s2)
        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)
        row = afs.conn.execute(
            "SELECT deprecated, deprecated_reason FROM agent_skills "
            "WHERE skill_id = ?", (retire,),
        ).fetchone()
        assert row[0] == 1
        assert "Merged into skill" in row[1]

    def test_proposal_marked_applied(self, afs):
        _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)
        row = afs.conn.execute(
            "SELECT status, applied, applied_at FROM consolidation_proposals "
            "WHERE proposal_id = ?", (pid,),
        ).fetchone()
        assert row[0] == "applied"
        assert row[1] == 1
        assert row[2] is not None

    def test_double_accept_errors(self, afs):
        _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)
        result = accept_merge(afs.conn, pid)
        assert "error" in result
        assert "applied" in result["error"]

    def test_unknown_proposal_errors(self, afs):
        result = accept_merge(afs.conn, 99999)
        assert "error" in result
        assert "not found" in result["error"]


class TestRejectMerge:
    def test_reject_marks_rejected(self, afs):
        _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        out = reject_merge(afs.conn, pid, reason="duplicates serve distinct callers")
        assert out["status"] == "rejected"
        row = afs.conn.execute(
            "SELECT status, rationale FROM consolidation_proposals "
            "WHERE proposal_id = ?", (pid,),
        ).fetchone()
        assert row[0] == "rejected"
        assert "duplicates serve distinct callers" in (row[1] or "")

    def test_rejected_is_not_listed_as_pending(self, afs):
        _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        reject_merge(afs.conn, pid)
        assert list_pending_merges(afs.conn) == []

    def test_double_reject_errors(self, afs):
        _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        reject_merge(afs.conn, pid)
        out = reject_merge(afs.conn, pid)
        assert "error" in out

    def test_cannot_accept_after_reject(self, afs):
        _make_duplicate_pair(afs)
        pid = _pending_merge_id(afs.conn)
        reject_merge(afs.conn, pid)
        out = accept_merge(afs.conn, pid)
        assert "error" in out


class TestAssociationCollapse:
    def test_association_weights_merge_under_conflict(self, afs):
        s1, s2 = _make_duplicate_pair(afs)
        keep, retire = min(s1, s2), max(s1, s2)

        # Seed a common neighbour so both skills have an edge that will
        # collide after collapse.
        aid = afs.spawn("b")
        sk = SkillStore(afs.conn)
        neighbour = sk.save(name="other-skill", description="d", template="t",
                            source_agent_id=aid, tags=[])
        afs.conn.execute(
            "INSERT OR REPLACE INTO associations "
            "(kind_a, id_a, kind_b, id_b, weight, uses) "
            "VALUES ('skill', ?, 'skill', ?, 1.5, 3)",
            (keep, neighbour),
        )
        afs.conn.execute(
            "INSERT OR REPLACE INTO associations "
            "(kind_a, id_a, kind_b, id_b, weight, uses) "
            "VALUES ('skill', ?, 'skill', ?, 2.0, 4)",
            (retire, neighbour),
        )
        afs.conn.commit()

        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)

        row = afs.conn.execute(
            "SELECT weight, uses FROM associations "
            "WHERE kind_a='skill' AND id_a=? AND kind_b='skill' AND id_b=?",
            (keep, neighbour),
        ).fetchone()
        assert row is not None
        assert row[0] == pytest.approx(3.5)
        assert row[1] == 7

        # Retired skill has no leftover edges
        left = afs.conn.execute(
            "SELECT COUNT(*) FROM associations "
            "WHERE (kind_a='skill' AND id_a=?) OR (kind_b='skill' AND id_b=?)",
            (retire, retire),
        ).fetchone()[0]
        assert left == 0

    def test_self_edge_dropped_after_merge(self, afs):
        s1, s2 = _make_duplicate_pair(afs)
        keep, retire = min(s1, s2), max(s1, s2)
        # An edge between the two merging skills would become a self-loop
        afs.conn.execute(
            "INSERT OR REPLACE INTO associations "
            "(kind_a, id_a, kind_b, id_b, weight, uses) "
            "VALUES ('skill', ?, 'skill', ?, 9.0, 9)",
            (retire, keep),
        )
        afs.conn.commit()
        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)
        # No self-loop on the keeper
        self_loop = afs.conn.execute(
            "SELECT COUNT(*) FROM associations "
            "WHERE kind_a='skill' AND id_a=? AND kind_b='skill' AND id_b=?",
            (keep, keep),
        ).fetchone()[0]
        assert self_loop == 0


class TestEndToEnd:
    def test_full_workflow_leaves_one_skill(self, afs):
        s1, s2 = _make_duplicate_pair(afs)
        # Two candidates before merge
        active_before = afs.conn.execute(
            "SELECT COUNT(*) FROM agent_skills WHERE deprecated = 0",
        ).fetchone()[0]
        pid = _pending_merge_id(afs.conn)
        accept_merge(afs.conn, pid)
        active_after = afs.conn.execute(
            "SELECT COUNT(*) FROM agent_skills WHERE deprecated = 0",
        ).fetchone()[0]
        assert active_after == active_before - 1
