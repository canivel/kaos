"""kaos.bench.schema — the local bench.db must make the design's promises
unrepresentable to violate: immutable records, append-forever candidates,
rejection-requires-reasoning (D0.1), no self-reported outcomes, monotone
item-state lattice, idempotent harvest.
"""

from __future__ import annotations

import sqlite3

import pytest

from kaos.bench.schema import bench_id, init_bench_db, open_bench


@pytest.fixture
def db(tmp_path):
    conn = open_bench(tmp_path / "test.bench.db")
    yield conn
    conn.close()


def _admit(conn, cid="tb1:" + "a" * 64, kind="skill", verdict="ACCEPT"):
    conn.execute(
        "INSERT INTO eval_records (record_cid, schema_id, kind, self_test_passed,"
        " verdict, variant, faithful, repro_class, body_json, origin_bench_id)"
        " VALUES (?, 'transferbench/eval_record/v1', ?, 1, ?, 'as-is', 1,"
        " 'llm_nondeterministic', '{}', ?)",
        (cid, kind, verdict, bench_id(conn)),
    )
    conn.commit()
    return cid


class TestInit:
    def test_init_is_idempotent(self, tmp_path):
        p = tmp_path / "b.bench.db"
        c1 = open_bench(p)
        bid = bench_id(c1)
        c1.close()
        c2 = open_bench(p)  # re-open runs init again
        assert bench_id(c2) == bid  # same bench identity, single version row
        assert c2.execute("SELECT COUNT(*) FROM bench_schema_version").fetchone()[0] == 1
        c2.close()

    def test_tier_stamped(self, tmp_path):
        c = open_bench(tmp_path / "e.bench.db", bench_tier="enterprise")
        tier = c.execute("SELECT value FROM bench_meta WHERE key='bench_tier'").fetchone()[0]
        assert tier == "enterprise"
        c.close()


class TestRecordImmutability:
    def test_verdict_flip_blocked(self, db):
        cid = _admit(db, verdict="REJECT")
        with pytest.raises(sqlite3.DatabaseError, match="immutable"):
            db.execute("UPDATE eval_records SET verdict='ACCEPT' WHERE record_cid=?", (cid,))

    def test_delete_blocked(self, db):
        cid = _admit(db)
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("DELETE FROM eval_records WHERE record_cid=?", (cid,))

    def test_kind_constrained(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            _admit(db, cid="tb1:" + "b" * 64, kind="vibes")


class TestRejectionsAreData:
    def _cand(self, db, ref="skill:42"):
        db.execute(
            "INSERT INTO bench_candidates (candidate_id, source_kind, source_ref, kind)"
            " VALUES ('c1', 'skill_telemetry', ?, 'skill')", (ref,))
        db.commit()

    def test_rejection_without_reason_unrepresentable(self, db):
        self._cand(db)
        with pytest.raises(sqlite3.DatabaseError, match="rejections are data"):
            db.execute("UPDATE bench_candidates SET status='e1_rejected' WHERE candidate_id='c1'")

    def test_rejection_with_reasoning_retained(self, db):
        self._cand(db)
        db.execute(
            "UPDATE bench_candidates SET status='e1_rejected',"
            " e1_json='{\"wilson_lb\": 0.41, \"floor\": 0.60}',"
            " rejection_reason='wilson_lb 0.41 below 0.60 floor'"
            " WHERE candidate_id='c1'")
        db.commit()
        row = db.execute("SELECT * FROM bench_candidates WHERE candidate_id='c1'").fetchone()
        assert row["status"] == "e1_rejected"
        assert "0.41" in row["e1_json"] and "below" in row["rejection_reason"]

    def test_candidates_never_deleted(self, db):
        self._cand(db)
        with pytest.raises(sqlite3.DatabaseError, match="append-forever"):
            db.execute("DELETE FROM bench_candidates WHERE candidate_id='c1'")

    def test_same_dud_never_reharvested(self, db):
        self._cand(db, ref="skill:7")
        with pytest.raises(sqlite3.IntegrityError):  # UNIQUE(source_kind, source_ref)
            db.execute(
                "INSERT INTO bench_candidates (candidate_id, source_kind, source_ref, kind)"
                " VALUES ('c2', 'skill_telemetry', 'skill:7', 'skill')")


class TestTelemetryHonesty:
    def test_self_report_unrepresentable(self, db):
        cid = _admit(db)
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO outcome_telemetry (telemetry_id, record_cid, agent_id,"
                " invoked, outcome, outcome_source) VALUES ('t1', ?, 'a1', 1, 1, 'agent_claim')",
                (cid,))

    def test_runner_outcome_accepted(self, db):
        cid = _admit(db)
        db.execute(
            "INSERT INTO outcome_telemetry (telemetry_id, record_cid, agent_id,"
            " invoked, outcome, outcome_source, shadow) VALUES ('t2', ?, 'a1', 1, 0, 'runner', 1)",
            (cid,))
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM outcome_telemetry").fetchone()[0] == 1


class TestPullLedger:
    def test_withhold_without_reason_unrepresentable(self, db):
        cid = _admit(db)
        db.execute("INSERT INTO bench_pulls (pull_id, agent_id, k) VALUES ('p1','a1',3)")
        with pytest.raises(sqlite3.DatabaseError, match="decisions are data"):
            db.execute(
                "INSERT INTO bench_pull_decisions (pull_id, record_cid, decision)"
                " VALUES ('p1', ?, 'withheld')", (cid,))

    def test_withhold_with_reason_and_empty_pull_logged(self, db):
        cid = _admit(db)
        db.execute("INSERT INTO bench_pulls (pull_id, agent_id, k) VALUES ('p2','a1',3)")
        db.execute(
            "INSERT INTO bench_pull_decisions (pull_id, record_cid, decision, reason, axis)"
            " VALUES ('p2', ?, 'withheld', 'consumed axis absent', 'M1')", (cid,))
        # empty pull = a bench_pulls row with zero served decisions — a success state
        db.execute("INSERT INTO bench_pulls (pull_id, agent_id, k) VALUES ('p3','a2',3)")
        db.commit()
        served = db.execute(
            "SELECT COUNT(*) FROM bench_pull_decisions WHERE pull_id='p3'").fetchone()[0]
        assert served == 0
        wh = db.execute(
            "SELECT reason, axis FROM bench_pull_decisions WHERE decision='withheld'").fetchone()
        assert wh["axis"] == "M1"

    def test_pull_decisions_never_deleted(self, db):
        cid = _admit(db)
        db.execute("INSERT INTO bench_pulls (pull_id, agent_id, k) VALUES ('p4','a1',3)")
        db.execute(
            "INSERT INTO bench_pull_decisions (pull_id, record_cid, decision, weight, fidelity)"
            " VALUES ('p4', ?, 'served', 1.0, 'full')", (cid,))
        with pytest.raises(sqlite3.DatabaseError, match="append-forever"):
            db.execute("DELETE FROM bench_pull_decisions WHERE pull_id='p4'")


class TestAutomaticHistory:
    def test_state_transitions_journaled_with_old_reasoning(self, db):
        cid = _admit(db)
        db.execute("INSERT INTO bench_item_state (record_cid, state, reason_json)"
                   " VALUES (?, 'serving', '{}')", (cid,))
        db.execute("UPDATE bench_item_state SET state='quarantined',"
                   " reason_json='{\"why\": \"lift went negative\"}' WHERE record_cid=?", (cid,))
        db.execute("UPDATE bench_item_state SET state='evicted',"
                   " reason_json='{\"why\": \"confirmed harmful\"}' WHERE record_cid=?", (cid,))
        db.commit()
        events = [r["event_type"] for r in db.execute(
            "SELECT event_type FROM bench_events WHERE entity='item_state' ORDER BY event_seq")]
        assert events == ["enter:serving", "transition:serving->quarantined",
                          "transition:quarantined->evicted"]
        # the quarantine's reasoning survives the later eviction
        mid = db.execute(
            "SELECT payload_json FROM bench_events WHERE event_type LIKE '%quarantined->evicted'"
        ).fetchone()[0]
        assert "lift went negative" in mid

    def test_candidate_decisions_journaled(self, db):
        db.execute("INSERT INTO bench_candidates (candidate_id, source_kind, source_ref, kind)"
                   " VALUES ('cj', 'skill_telemetry', 'skill:99', 'skill')")
        db.execute("UPDATE bench_candidates SET status='e1_rejected',"
                   " rejection_reason='wilson below floor' WHERE candidate_id='cj'")
        db.commit()
        ev = db.execute("SELECT event_type, payload_json FROM bench_events"
                        " WHERE entity='candidate'").fetchone()
        assert ev["event_type"] == "status:harvested->e1_rejected"
        assert "wilson below floor" in ev["payload_json"]

    def test_history_is_immutable(self, db):
        cid = _admit(db)
        db.execute("INSERT INTO bench_item_state (record_cid, state) VALUES (?, 'serving')", (cid,))
        with pytest.raises(sqlite3.DatabaseError, match="append-only|immutable"):
            db.execute("DELETE FROM bench_events")

    def test_error_status_also_needs_reason(self, db):
        db.execute("INSERT INTO bench_candidates (candidate_id, source_kind, source_ref, kind)"
                   " VALUES ('ce', 'experiment', 'exp:5', 'mechanism_eval')")
        with pytest.raises(sqlite3.DatabaseError, match="rejections are data"):
            db.execute("UPDATE bench_candidates SET status='error' WHERE candidate_id='ce'")


class TestStateLattice:
    def test_forward_transitions_allowed(self, db):
        cid = _admit(db)
        db.execute("INSERT INTO bench_item_state (record_cid, state) VALUES (?, 'serving')", (cid,))
        db.execute("UPDATE bench_item_state SET state='quarantined' WHERE record_cid=?", (cid,))
        db.execute("UPDATE bench_item_state SET state='evicted' WHERE record_cid=?", (cid,))
        db.commit()
        assert db.execute("SELECT state FROM bench_item_state").fetchone()[0] == "evicted"

    def test_regression_unrepresentable(self, db):
        cid = _admit(db)
        db.execute("INSERT INTO bench_item_state (record_cid, state) VALUES (?, 'evicted')", (cid,))
        with pytest.raises(sqlite3.DatabaseError, match="monotone"):
            db.execute("UPDATE bench_item_state SET state='serving' WHERE record_cid=?", (cid,))
