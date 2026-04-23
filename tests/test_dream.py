"""Tests for the neuroplasticity substrate: signals, phases, cycle, weighted search."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kaos.core import Kaos
from kaos.dream import DreamCycle
from kaos.dream.cycle import get_run, list_runs
from kaos.dream.phases import narrative, replay, weights
from kaos.dream.signals import (
    DEFAULT_HALF_LIFE_DAYS,
    coldness,
    now_utc,
    parse_iso,
    recency_weight,
    success_rate,
    weighted_score,
    wilson_lower_bound,
)
from kaos.memory import MemoryStore
from kaos.skills import SkillStore


# ── Signals ─────────────────────────────────────────────────────────


class TestParseIso:
    def test_parses_standard_format(self):
        dt = parse_iso("2026-04-20T10:00:00.000")
        assert dt is not None
        assert dt.year == 2026 and dt.month == 4 and dt.day == 20
        assert dt.tzinfo is not None  # naive input treated as UTC

    def test_returns_none_on_garbage(self):
        assert parse_iso(None) is None
        assert parse_iso("") is None
        assert parse_iso("not a date") is None

    def test_trailing_z_handled(self):
        dt = parse_iso("2026-04-20T10:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None


class TestRecencyWeight:
    def test_now_is_one(self):
        now = now_utc()
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        assert recency_weight(ts, now=now) == pytest.approx(1.0, abs=0.01)

    def test_half_life_is_half(self):
        now = now_utc()
        past = (now - timedelta(days=DEFAULT_HALF_LIFE_DAYS)).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3]
        assert recency_weight(past, now=now) == pytest.approx(0.5, abs=0.01)

    def test_missing_ts_neutral(self):
        assert recency_weight(None) == 0.5

    def test_garbage_ts_neutral(self):
        assert recency_weight("not a date") == 0.5

    def test_weight_decreases_monotonically(self):
        now = now_utc()
        older = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        newer = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        assert recency_weight(older, now=now) < recency_weight(newer, now=now)


class TestSuccessRate:
    def test_none_when_no_uses(self):
        assert success_rate(0, 0) is None

    def test_simple_ratio(self):
        assert success_rate(10, 7) == 0.7

    def test_clamped_to_unit(self):
        assert success_rate(2, 5) == 1.0  # defensive clamp
        assert success_rate(2, -1) == 0.0


class TestWilsonLowerBound:
    def test_zero_uses_zero_score(self):
        assert wilson_lower_bound(0, 0) == 0.0

    def test_higher_n_higher_confidence(self):
        # 10/10 beats 1/1 because the sample size is bigger
        assert wilson_lower_bound(10, 10) > wilson_lower_bound(1, 1)

    def test_all_failure_near_zero(self):
        assert wilson_lower_bound(0, 10) < 0.05

    def test_always_in_unit(self):
        for u in [1, 5, 100]:
            for s in range(0, u + 1):
                v = wilson_lower_bound(s, u)
                assert 0.0 <= v <= 1.0


class TestWeightedScore:
    def test_zero_uses_gets_half_credit(self):
        # A brand-new skill should not score zero — just lower.
        assert weighted_score(bm25_score=1.0, uses=0, successes=0,
                              last_used_at=None) > 0.0

    def test_successful_recent_beats_stale(self):
        now = now_utc()
        recent_ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        stale_ts = (now - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        good = weighted_score(bm25_score=1.0, uses=10, successes=9,
                              last_used_at=recent_ts, now=now)
        stale = weighted_score(bm25_score=1.0, uses=10, successes=9,
                               last_used_at=stale_ts, now=now)
        assert good > stale

    def test_more_uses_beats_fewer_at_same_rate(self):
        now = now_utc()
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        many = weighted_score(bm25_score=1.0, uses=20, successes=18,
                              last_used_at=ts, now=now)
        few = weighted_score(bm25_score=1.0, uses=2, successes=2,
                             last_used_at=ts, now=now)
        # Same rate (or higher for few), but Wilson penalises tiny n
        assert many > few


class TestColdness:
    def test_never_used_is_maxcold(self):
        assert coldness(0, None) == 1.0

    def test_recently_used_is_warm(self):
        now = now_utc()
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        assert coldness(1, ts, now=now) < 0.1


# ── End-to-end: seeded DB with usage history ────────────────────────


@pytest.fixture
def plastic_db(tmp_path):
    """Return (db_path, skill_ids, memory_ids) for a DB with varied usage.

    Three skills, deliberately differentiated:
      - hot_skill: recent, 10/10 success → should dominate the hot list
      - mid_skill: moderate, 5/8 success
      - cold_skill: never used → should dominate the cold list
    """
    db_path = tmp_path / "plastic.db"
    afs = Kaos(db_path=str(db_path))

    a1 = afs.spawn("worker-a")
    a2 = afs.spawn("worker-b")

    sk = SkillStore(afs.conn)
    hot_id = sk.save(name="hot-skill", description="often succeeds",
                     template="do {thing}", source_agent_id=a1, tags=["hot"])
    mid_id = sk.save(name="mid-skill", description="sometimes works",
                     template="maybe {thing}", source_agent_id=a1, tags=["mid"])
    cold_id = sk.save(name="cold-skill", description="never used",
                      template="try {thing}", source_agent_id=a2, tags=["cold"])

    for _ in range(10):
        sk.record_outcome(hot_id, success=True, agent_id=a1)
    for i in range(8):
        sk.record_outcome(mid_id, success=(i < 5), agent_id=a1)

    mem = MemoryStore(afs.conn)
    popular_mid = mem.write(agent_id=a1,
                            content="Critical insight about distributed retries",
                            type="insight", key="retry-insight")
    unpopular_mid = mem.write(agent_id=a2,
                              content="Minor observation about logging",
                              type="observation", key="log-obs")

    # Simulate retrievals: popular is hit many times, unpopular zero
    for _ in range(7):
        mem.search("distributed retries", rank="bm25",
                   record_hits=True, requesting_agent_id=a1)

    # Mark workers completed so replay sees successful episodes
    afs.complete(a1)
    afs.complete(a2)

    afs.close()
    yield str(db_path), {"hot": hot_id, "mid": mid_id, "cold": cold_id}, {
        "popular": popular_mid, "unpopular": unpopular_mid
    }


class TestReplayPhase:
    def test_counts_agents_correctly(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            report = replay.run(afs.conn, apply=False)
        finally:
            afs.close()
        assert len(report.episodes) == 2
        assert report.successes == 2
        assert report.failures == 0

    def test_apply_writes_episode_signals(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            replay.run(afs.conn, apply=True)
            rows = afs.conn.execute(
                "SELECT COUNT(*) FROM episode_signals"
            ).fetchone()[0]
        finally:
            afs.close()
        assert rows == 2

    def test_idempotent_upsert(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            replay.run(afs.conn, apply=True)
            replay.run(afs.conn, apply=True)  # second run should not duplicate
            rows = afs.conn.execute(
                "SELECT COUNT(*) FROM episode_signals"
            ).fetchone()[0]
        finally:
            afs.close()
        assert rows == 2


class TestWeightsPhase:
    def test_hot_skill_ranks_first(self, plastic_db):
        db_path, ids, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            report = weights.run(afs.conn)
        finally:
            afs.close()
        assert report.hot_skills
        # hot-skill should be the top scorer (10/10, recent)
        assert report.hot_skills[0].name == "hot-skill"

    def test_cold_skill_flagged_cold(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            report = weights.run(afs.conn)
        finally:
            afs.close()
        cold_names = [s.name for s in report.cold_skills]
        assert "cold-skill" in cold_names

    def test_popular_memory_scores_higher(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            report = weights.run(afs.conn)
        finally:
            afs.close()
        popular = next(m for m in report.memory if m.key == "retry-insight")
        unpopular = next(m for m in report.memory if m.key == "log-obs")
        assert popular.score > unpopular.score


class TestNarrativePhase:
    def test_renders_all_sections(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            r = replay.run(afs.conn, apply=False)
            w = weights.run(afs.conn)
        finally:
            afs.close()
        digest = narrative.render_digest(
            replay=r, weights=w, mode="dry_run",
            since_ts=None,
            started_at=now_utc(),
            finished_at=now_utc(),
            db_path=db_path,
        )
        assert "# KAOS dream digest" in digest
        assert "## Episodes (replay)" in digest
        assert "## 🔥 Hot skills" in digest
        assert "hot-skill" in digest
        assert "cold-skill" in digest
        assert "## 🧠 Hot memory" in digest
        assert "retry-insight" in digest


# ── DreamCycle orchestration ────────────────────────────────────────


class TestDreamCycle:
    def test_dry_run_writes_run_row_no_episode_signals(self, plastic_db, tmp_path):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            cycle = DreamCycle(afs, digest_dir=tmp_path / "Dreams")
            result = cycle.run(dry_run=True)
            rows = afs.conn.execute(
                "SELECT COUNT(*) FROM episode_signals"
            ).fetchone()[0]
            runs_count = afs.conn.execute(
                "SELECT COUNT(*) FROM dream_runs"
            ).fetchone()[0]
        finally:
            afs.close()
        assert result.mode == "dry_run"
        assert runs_count == 1
        assert rows == 0  # dry run must not write episode_signals

    def test_apply_writes_episode_signals(self, plastic_db, tmp_path):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            cycle = DreamCycle(afs, digest_dir=tmp_path / "Dreams")
            result = cycle.run(dry_run=False)
            rows = afs.conn.execute(
                "SELECT COUNT(*) FROM episode_signals"
            ).fetchone()[0]
        finally:
            afs.close()
        assert result.mode == "apply"
        assert rows == 2

    def test_digest_written_to_disk(self, plastic_db, tmp_path):
        db_path, _, _ = plastic_db
        digest_dir = tmp_path / "Dreams"
        afs = Kaos(db_path=db_path)
        try:
            result = DreamCycle(afs, digest_dir=digest_dir).run(dry_run=True)
        finally:
            afs.close()
        assert result.digest_path
        p = Path(result.digest_path)
        assert p.is_file()
        assert "KAOS dream digest" in p.read_text(encoding="utf-8")

    def test_list_and_get_runs(self, plastic_db, tmp_path):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            cycle = DreamCycle(afs, digest_dir=tmp_path / "Dreams")
            r1 = cycle.run(dry_run=True)
            r2 = cycle.run(dry_run=False)
            runs = list_runs(afs.conn)
            fetched = get_run(afs.conn, r1.run_id)
        finally:
            afs.close()
        assert len(runs) == 2
        assert runs[0]["run_id"] == r2.run_id  # newest first
        assert fetched is not None
        assert fetched["run_id"] == r1.run_id

    def test_phase_timings_recorded(self, plastic_db, tmp_path):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            result = DreamCycle(afs, digest_dir=tmp_path / "Dreams").run(dry_run=True)
        finally:
            afs.close()
        assert "replay_ms" in result.phase_timings_ms
        assert "weights_ms" in result.phase_timings_ms
        assert "narrative_ms" in result.phase_timings_ms
        assert "total_ms" in result.phase_timings_ms


# ── Weighted search behaviour on SkillStore / MemoryStore ───────────


class TestWeightedSearch:
    def test_skill_search_bm25_default_unchanged(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            sk = SkillStore(afs.conn)
            results = sk.search("skill")  # default rank=bm25
            names = [s.name for s in results]
        finally:
            afs.close()
        assert set(names) == {"hot-skill", "mid-skill", "cold-skill"}

    def test_skill_search_weighted_promotes_hot(self, plastic_db):
        """Weighted ranking must put hot-skill above cold-skill for an
        ambiguous query that FTS alone might order differently."""
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            sk = SkillStore(afs.conn)
            weighted = sk.search("skill", rank="weighted")
            names_w = [s.name for s in weighted]
        finally:
            afs.close()
        # Must include all three
        assert set(names_w) == {"hot-skill", "mid-skill", "cold-skill"}
        # Hot skill must outrank cold skill under weighted
        assert names_w.index("hot-skill") < names_w.index("cold-skill")

    def test_memory_search_weighted_promotes_popular(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            mem = MemoryStore(afs.conn)
            weighted = mem.search("insight OR observation", rank="weighted")
            keys = [m.key for m in weighted]
        finally:
            afs.close()
        assert "retry-insight" in keys
        assert "log-obs" in keys
        # popular memory entry must rank ahead of unpopular
        assert keys.index("retry-insight") < keys.index("log-obs")

    def test_memory_record_hits_persists(self, plastic_db):
        db_path, _, _ = plastic_db
        afs = Kaos(db_path=db_path)
        try:
            mem = MemoryStore(afs.conn)
            # Use a real agent_id from the fixture to satisfy the FK constraint.
            agent_id = afs.conn.execute(
                "SELECT agent_id FROM agents LIMIT 1"
            ).fetchone()[0]
            before = afs.conn.execute("SELECT COUNT(*) FROM memory_hits").fetchone()[0]
            mem.search("retry", record_hits=True, requesting_agent_id=agent_id)
            after = afs.conn.execute("SELECT COUNT(*) FROM memory_hits").fetchone()[0]
        finally:
            afs.close()
        assert after > before
