"""kaos.bench entry (E1) + harvest — Filter 1's gate and the three feed surfaces.

The test that matters most: a skill that succeeds-when-used but produces ZERO
counterfactual lift (the SWE-Skills-Bench profile — 39/49 such skills shipped)
must FAIL E1 despite a perfect Wilson bound (A5, R3).
"""

from __future__ import annotations

import json

import pytest

from kaos import Kaos
from kaos.bench.entry import TelemetryRow, evaluate_e1, wilson_lower_bound
from kaos.bench.harvest import harvest_all
from kaos.bench.schema import open_bench
from kaos.skills import SkillStore


def _rows(n, agents=2, buckets=3, success_rate=1.0, source="episode_status",
          prefix="b"):
    out = []
    for i in range(n):
        out.append(TelemetryRow(
            agent_id=f"a{i % agents}", task_hash=f"{prefix}{i % buckets}",
            success=(i >= int(n * (1 - success_rate))), outcome_source=source))
    return out


class TestE1:
    def test_swe_skills_profile_fails_despite_perfect_wilson(self):
        # Succeeds every time it's used — but unexposed tasks succeed just as
        # often: zero lift. Wilson-alone would admit it forever; A5 kills it.
        exposed = _rows(12, success_rate=1.0)
        unexposed = _rows(12, success_rate=1.0)
        res = evaluate_e1(exposed, unexposed)
        assert res.conditions["A4"]["passed"] is True      # wilson is perfect
        assert res.floors_met is True
        assert res.passed is False                          # ...and it still fails
        assert "A5" in res.reason and "lower bound" in res.reason

    def test_real_lift_passes(self):
        exposed = _rows(14, success_rate=1.0)               # 14/14 with the skill
        unexposed = _rows(14, success_rate=0.15)            # ~2/14 without
        res = evaluate_e1(exposed, unexposed)
        assert res.passed is True, res.reason
        assert res.conditions["A5"]["detail"]["lift_lb"] > 0

    def test_self_report_counts_as_nothing(self):
        # all rows self-report -> zero counted -> floors unmet -> E0, NOT a dud
        res = evaluate_e1(_rows(20, source="self_report"), [])
        assert res.floors_met is False and res.passed is False
        assert "excluded" in res.conditions["A3"]["detail"]

    def test_no_unexposed_arm_means_floors_unmet(self):
        res = evaluate_e1(_rows(15), [])                    # no counterfactual arm
        assert res.floors_met is False
        assert "A5" in res.reason

    def test_diversity_floor(self):
        res = evaluate_e1(_rows(12, agents=1, buckets=1), _rows(12, agents=1, buckets=1))
        assert res.conditions["A2"]["passed"] is False

    def test_quality_can_downgrade_but_never_rescue(self):
        # binary-perfect but graded quality is poor -> A6 downgrades the pass
        exposed = _rows(14, success_rate=1.0)
        for r in exposed:
            r.quality = 0.2
        res = evaluate_e1(exposed, _rows(14, success_rate=0.1))
        assert res.conditions["A4"]["passed"] is True
        assert res.conditions["A6"]["passed"] is False and res.passed is False
        # and poor binary is not rescued by great quality
        bad = _rows(14, success_rate=0.3)
        for r in bad:
            r.quality = 1.0
        res2 = evaluate_e1(bad, _rows(14, success_rate=0.1))
        assert res2.passed is False

    def test_wilson_bound_sanity(self):
        assert wilson_lower_bound(10, 10) > 0.80
        assert wilson_lower_bound(6, 10) < 0.60
        assert wilson_lower_bound(0, 0) == 0.0


@pytest.fixture
def dbs(tmp_path):
    afs = Kaos(db_path=str(tmp_path / "kaos.db"))
    bench = open_bench(tmp_path / "bench.db")
    yield afs, bench
    bench.close()
    afs.close()


class TestHarvest:
    def _seed(self, afs, n_uses=12):
        sk = SkillStore(afs.conn)
        sid = sk.save(name="retry_backoff", description="retry with backoff",
                      template="retry {n} times", tags=["retry"])
        a1 = afs.spawn("w1")
        a2 = afs.spawn("w2")
        for i in range(n_uses):
            sk.record_outcome(sid, success=True, agent_id=(a1 if i % 2 else a2),
                              task_hash=f"t{i % 4}")
        return sid

    def test_skill_harvested_and_stays_e0_on_legacy_selfreport(self, dbs):
        afs, bench = dbs
        self._seed(afs)
        rep = harvest_all(afs.conn, bench)
        assert rep.skills_harvested == 1
        row = bench.execute("SELECT status, e1_json FROM bench_candidates "
                            "WHERE source_kind='skill_telemetry'").fetchone()
        # legacy rows are self_report -> not evidence -> E0 accumulating, not a dud
        assert row["status"] == "harvested"
        assert rep.e0_accumulating == 1
        assert "excluded" in json.loads(row["e1_json"])["conditions"]["A3"]["detail"]

    def test_experiments_harvested_including_rejects(self, dbs):
        afs, bench = dbs
        from kaos.experiments import ExperimentStore
        store = ExperimentStore(afs.db_path)
        store.log_run(name="pfa-probe", family="probe",
                      verdict="REJECT: kill gate(s) failed: G1", git_sha="")
        store.log_run(name="gdl-probe", family="probe", verdict="ACCEPT", git_sha="")
        store.close()
        rep = harvest_all(afs.conn, bench)
        assert rep.experiments_harvested == 2
        verdicts = {json.loads(r["payload_json"])["verdict"][:6]
                    for r in bench.execute("SELECT payload_json FROM bench_candidates "
                                           "WHERE source_kind='experiment'")}
        assert "REJECT" in verdicts and "ACCEPT" in verdicts  # rejects ARE collected
        st = {r["status"] for r in bench.execute(
            "SELECT status FROM bench_candidates WHERE source_kind='experiment'")}
        assert st == {"e1_passed"}  # full probe = validation; ladder skipped

    def test_harvest_is_idempotent(self, dbs):
        afs, bench = dbs
        self._seed(afs)
        r1 = harvest_all(afs.conn, bench)
        r2 = harvest_all(afs.conn, bench)
        assert r1.skills_harvested == 1 and r2.skills_harvested == 0
        n = bench.execute("SELECT COUNT(*) FROM bench_candidates").fetchone()[0]
        assert n == 1

    def test_e1_pass_with_sourced_rows(self, dbs):
        afs, bench = dbs
        sid = self._seed(afs, n_uses=14)
        # provenance known for every use row -> admissible evidence
        use_ids = [r[0] for r in afs.conn.execute(
            "SELECT use_id FROM skill_uses WHERE skill_id=?", (sid,))]
        source_map = {uid: "episode_status" for uid in use_ids}
        # NOTE: no unexposed arm exists organically yet -> floors still unmet (E0).
        rep = harvest_all(afs.conn, bench, source_map=source_map)
        row = bench.execute("SELECT status, e1_json FROM bench_candidates "
                            "WHERE source_kind='skill_telemetry'").fetchone()
        e1 = json.loads(row["e1_json"])
        assert e1["conditions"]["A4"]["passed"] is True     # evidence now counted
        assert row["status"] == "harvested"                 # but no counterfactual arm yet
        assert rep.e0_accumulating == 1

    def test_dream_promotions_enter_as_e0(self, dbs):
        afs, bench = dbs
        afs.conn.execute(
            "INSERT INTO consolidation_proposals (kind, targets, rationale, applied, status)"
            " VALUES ('promote', '{\"memory_id\": 3}', 'hot memory', 1, 'applied')")
        afs.conn.commit()
        rep = harvest_all(afs.conn, bench)
        assert rep.promotions_harvested == 1
        row = bench.execute("SELECT status, kind FROM bench_candidates "
                            "WHERE source_kind='dream_promotion'").fetchone()
        assert row["status"] == "harvested" and row["kind"] == "skill"
