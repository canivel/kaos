"""v0.10 — #7 plasticity-loop-closure remainder.

Two sub-items the v0.10 panel left open:
  1. consolidation re-proposal dedup — a rejected/applied proposal must not be
     re-journaled on the next cycle (the reject_proposal docstring promised this
     but the persist loop re-inserted every candidate every run).
  2. skill_apply / skill_outcome agent_id threading — the MCP dispatchers dropped
     the calling agent, writing skill_uses rows with agent_id=NULL and starving
     the per-agent Hebbian association.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaos import Kaos
from kaos.skills import SkillStore
from kaos.dream.phases import consolidation as C


# ── 1. consolidation re-proposal dedup ───────────────────────────────

def _mk_mergeable_pair(sk: SkillStore):
    a = sk.save(name="ensemble_vote_a", description="ensemble voting classifier accuracy boost",
                template="use {n} models", tags=["ensemble", "voting", "accuracy"])
    b = sk.save(name="ensemble_vote_b", description="ensemble voting classifier accuracy boost",
                template="use {k} models", tags=["ensemble", "voting", "accuracy"])
    return a, b


class TestConsolidationDedup:
    def test_merge_pair_not_reproposed_across_runs(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sk = SkillStore(afs.conn)
        _mk_mergeable_pair(sk)

        r1 = C.run(afs.conn, dry_run=True, merge_threshold=0.5)
        assert r1.merge_candidates >= 1, "fixture should produce a merge candidate"

        r2 = C.run(afs.conn, dry_run=True, merge_threshold=0.5)
        assert r2.merge_candidates == 0, "same merge pair re-proposed on second run"
        assert r2.skipped_duplicates >= 1

        rows = afs.conn.execute(
            "SELECT COUNT(*) FROM consolidation_proposals WHERE kind='merge'"
        ).fetchone()[0]
        assert rows == 1, f"expected 1 journaled merge proposal, got {rows}"
        afs.close()

    def test_rejected_proposal_stays_rejected(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sk = SkillStore(afs.conn)
        _mk_mergeable_pair(sk)
        C.run(afs.conn, dry_run=True, merge_threshold=0.5)
        pid = afs.conn.execute(
            "SELECT proposal_id FROM consolidation_proposals WHERE kind='merge'"
        ).fetchone()[0]
        C.reject_merge(afs.conn, pid, reason="not actually duplicates")

        # a subsequent cycle must NOT resurrect the rejected pair as pending
        C.run(afs.conn, dry_run=True, merge_threshold=0.5)
        statuses = [r[0] for r in afs.conn.execute(
            "SELECT status FROM consolidation_proposals WHERE kind='merge'").fetchall()]
        assert statuses == ["rejected"], f"rejected pair resurrected: {statuses}"
        afs.close()

    def test_distinct_pairs_still_proposed(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sk = SkillStore(afs.conn)
        _mk_mergeable_pair(sk)
        C.run(afs.conn, dry_run=True, merge_threshold=0.5)
        # a genuinely new mergeable pair must still be journaled
        sk.save(name="retry_backoff_a", description="retry with exponential backoff on timeout",
                template="retry {n}", tags=["retry", "backoff", "timeout"])
        sk.save(name="retry_backoff_b", description="retry with exponential backoff on timeout",
                template="retry {m}", tags=["retry", "backoff", "timeout"])
        r = C.run(afs.conn, dry_run=True, merge_threshold=0.5)
        assert r.merge_candidates >= 1, "a new distinct pair should still be proposed"
        afs.close()

    def test_identity_is_order_independent(self):
        assert C._proposal_identity("merge", {"skill_ids": [3, 7]}) == \
               C._proposal_identity("merge", {"skill_ids": [7, 3]})
        assert C._proposal_identity("prune", {"skill_id": 5, "success_rate": 0.1}) == \
               C._proposal_identity("prune", {"skill_id": 5, "success_rate": 0.9})


# ── 2. skill_apply / skill_outcome agent_id threading ────────────────

def _dispatch(afs, name, args):
    import asyncio
    from kaos.mcp.server import init_server, call_tool
    init_server(afs, None)  # type: ignore[arg-type]
    return asyncio.run(call_tool(name, args))


class TestSkillAgentIdThreading:
    def test_skill_apply_threads_agent_id(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sk = SkillStore(afs.conn)
        sid = sk.save(name="s", description="d", template="do {x}", tags=[])
        aid = afs.spawn("worker-apply")  # real agent id (skill_uses.agent_id has a FK)

        _dispatch(afs, "skill_apply",
                  {"skill_id": sid, "params": {"x": "y"}, "outcome": "success",
                   "agent_id": aid})

        rows = afs.conn.execute(
            "SELECT agent_id FROM skill_uses WHERE skill_id=?", (sid,)
        ).fetchall()
        assert rows and rows[0][0] == aid, \
            f"skill_apply dropped agent_id: {rows}"
        afs.close()

    def test_skill_outcome_threads_agent_id(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sk = SkillStore(afs.conn)
        sid = sk.save(name="s", description="d", template="t", tags=[])
        aid = afs.spawn("worker-outcome")  # real agent id (FK on skill_uses.agent_id)

        _dispatch(afs, "skill_outcome",
                  {"skill_id": sid, "success": True, "agent_id": aid})

        row = afs.conn.execute(
            "SELECT agent_id FROM skill_uses WHERE skill_id=?", (sid,)
        ).fetchone()
        assert row and row[0] == aid, f"skill_outcome dropped agent_id: {row}"
        afs.close()

    def test_agent_id_in_both_schemas(self):
        import kaos.mcp.server as server
        tools = {t.name: t for t in server.build_tool_list()}
        for name in ("skill_apply", "skill_outcome"):
            props = tools[name].inputSchema["properties"]
            assert "agent_id" in props, f"{name} schema missing agent_id"
