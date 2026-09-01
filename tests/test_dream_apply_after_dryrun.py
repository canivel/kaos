"""Regression: `consolidate --apply` after a dry-run must actually apply.

Found by the ARC-AGI-3 validation scenario (70/76): the v0.10 re-proposal
dedup treated *pending* journal rows as blocking, so the documented workflow
  kaos dream consolidate --dry-run   (or the automatic threshold cycle)
  kaos dream consolidate --apply
applied nothing — the dry-run journaled every candidate as pending, and the
apply run then skipped them all as duplicates. Dedup must block only DECIDED
identities (applied / rejected); pending ones are what --apply exists to act
on. Red-first: this file fails on the pre-fix code with applied == 0.
"""

from __future__ import annotations

from kaos import Kaos
from kaos.dream.phases import consolidation as C


def _mk_prunable_skill(conn):
    """A skill with 6+ uses and <40% success — the documented prune rule."""
    cur = conn.execute(
        "INSERT INTO agent_skills (name, description, template, use_count, success_count) "
        "VALUES ('flaky-skill', 'never works', 'do {x}', 8, 1)"
    )
    conn.commit()
    return cur.lastrowid


def _mk_promotable_memory(afs):
    """A memory with enough recorded hits to cross the promote threshold."""
    a = afs.spawn("mem-owner")
    cur = afs.conn.execute(
        "INSERT INTO memory (agent_id, key, content, type) "
        "VALUES (?, 'hot-fix', 'inject p50 risk as prior', 'result')", (a,)
    )
    mid = cur.lastrowid
    for _ in range(6):
        afs.conn.execute(
            "INSERT INTO memory_hits (memory_id, agent_id) VALUES (?, ?)", (mid, a)
        )
    afs.conn.commit()
    return mid


class TestApplyAfterDryRun:
    def test_apply_applies_pending_from_prior_dry_run(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sid = _mk_prunable_skill(afs.conn)

        r1 = C.run(afs.conn, dry_run=True)
        assert r1.pruned >= 1, "fixture must produce a prune candidate"

        r2 = C.run(afs.conn, dry_run=False)
        assert r2.applied >= 1, (
            "apply after dry-run applied nothing — pending journal rows "
            "were deduped away instead of applied"
        )
        deprecated = afs.conn.execute(
            "SELECT COALESCE(deprecated, 0) FROM agent_skills WHERE skill_id = ?",
            (sid,),
        ).fetchone()[0]
        assert deprecated == 1, "prune was reported applied but skill not deprecated"

        # the journal row flipped to applied — not duplicated
        rows = afs.conn.execute(
            "SELECT status, COUNT(*) FROM consolidation_proposals "
            "WHERE kind='prune' GROUP BY status"
        ).fetchall()
        assert dict(rows) == {"applied": 1}, f"journal state: {rows}"
        afs.close()

    def test_apply_after_dry_run_promotes_hot_memory(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        _mk_promotable_memory(afs)

        C.run(afs.conn, dry_run=True)
        r = C.run(afs.conn, dry_run=False)
        assert r.applied >= 1
        n = afs.conn.execute(
            "SELECT COUNT(*) FROM agent_skills WHERE name = 'hot-fix'"
        ).fetchone()[0]
        assert n == 1, "hot memory not promoted to a skill on apply"
        afs.close()

    def test_second_dry_run_still_reports_zero_new(self, tmp_path):
        """The v0.10 no-noise guarantee must survive the fix."""
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        _mk_prunable_skill(afs.conn)
        C.run(afs.conn, dry_run=True)
        r2 = C.run(afs.conn, dry_run=True)
        assert r2.pruned == 0
        assert r2.skipped_duplicates >= 1
        n = afs.conn.execute(
            "SELECT COUNT(*) FROM consolidation_proposals WHERE kind='prune'"
        ).fetchone()[0]
        assert n == 1, "dry-run duplicated the pending journal row"
        afs.close()

    def test_decided_identities_still_block_apply(self, tmp_path):
        """An applied proposal must not be re-applied on the next cycle."""
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        _mk_promotable_memory(afs)
        r1 = C.run(afs.conn, dry_run=False)
        assert r1.applied >= 1
        r2 = C.run(afs.conn, dry_run=False)
        assert r2.applied == 0, "applied identity resurrected on later cycle"
        assert r2.skipped_duplicates >= 1
        afs.close()
