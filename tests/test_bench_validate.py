"""kaos.bench.validate — pending-candidate driver, dream phase, CLI verb."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from kaos import Kaos
from kaos.bench.schema import open_bench
from kaos.bench.validate import dream_phase, heuristic_judge, validate_pending
from kaos.cli.main import cli


def _experiment_candidate(bench, verdict="REJECT: kill gate(s) failed: G1"):
    bench.execute(
        "INSERT INTO bench_candidates (candidate_id, source_kind, source_ref,"
        " kind, status, payload_json) VALUES ('exp1', 'experiment', 'exp:2',"
        " 'mechanism_eval', 'e1_passed', ?)",
        (json.dumps({"name": "pfa-probe", "family": "probe", "verdict": verdict,
                     "lock_sha256": "ab" * 32}),))
    bench.commit()


class TestValidatePending:
    def test_mechanism_eval_mints_directly_reject_included(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "k.db"))
        bench = open_bench(tmp_path / "b.db")
        _experiment_candidate(bench)
        rep = validate_pending(afs.conn, bench)          # no model needed
        assert rep.minted_mechanism_evals == 1
        row = bench.execute("SELECT verdict, trust_level, variant FROM eval_records").fetchone()
        assert row["verdict"] == "REJECT"                 # rejections are data
        assert row["trust_level"] == 1 and row["variant"] == "as-probed"
        cand = bench.execute("SELECT status FROM bench_candidates").fetchone()
        assert cand["status"] == "admitted"
        bench.close()
        afs.close()

    def test_skill_without_model_stays_e1_counted(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "k.db"))
        bench = open_bench(tmp_path / "b.db")
        bench.execute(
            "INSERT INTO bench_candidates (candidate_id, source_kind, source_ref,"
            " kind, status, payload_json) VALUES ('s1', 'skill_telemetry',"
            " 'skill:1', 'skill', 'e1_passed', '{\"name\": \"x\"}')")
        bench.commit()
        rep = validate_pending(afs.conn, bench, complete=None)
        assert rep.skipped_no_model == 1
        assert bench.execute("SELECT status FROM bench_candidates").fetchone()[0] == "e1_passed"
        bench.close()
        afs.close()

    def test_idempotent_second_pass(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "k.db"))
        bench = open_bench(tmp_path / "b.db")
        _experiment_candidate(bench)
        validate_pending(afs.conn, bench)
        rep2 = validate_pending(afs.conn, bench)          # admitted -> not pending
        assert rep2.minted_mechanism_evals == 0
        assert bench.execute("SELECT COUNT(*) FROM eval_records").fetchone()[0] == 1
        bench.close()
        afs.close()


class TestHeuristicJudge:
    def test_shapes(self):
        assert heuristic_judge("fix pipelines/scrape.py", "") == 0.0
        assert heuristic_judge("fix pipelines/scrape.py", "I cannot help with that") == 0.2
        engaged = heuristic_judge("fix pipelines/scrape.py",
                                  "patched pipelines/scrape.py retry logic")
        ignored = heuristic_judge("fix pipelines/scrape.py", "lorem ipsum dolor")
        assert engaged > ignored


class TestDreamPhase:
    def test_harvests_and_mints_without_model(self, tmp_path):
        db = tmp_path / "kaos.db"
        afs = Kaos(db_path=str(db))
        from kaos.experiments import ExperimentStore
        store = ExperimentStore(str(db))
        store.log_run(name="gdl-probe", family="probe", verdict="ACCEPT", git_sha="")
        store.close()
        out = dream_phase(afs.conn, db)
        assert out["harvest"]["experiments_harvested"] == 1
        assert out["validate"]["minted_mechanism_evals"] == 1
        afs.close()

    def test_degrades_on_broken_bench(self, tmp_path):
        db = tmp_path / "kaos.db"
        afs = Kaos(db_path=str(db))
        (tmp_path / "notadb").mkdir()
        out = dream_phase(afs.conn, db, bench_path=tmp_path / "notadb")
        assert "error" in out                             # no raise, honest report
        afs.close()


class TestCLIValidate:
    def test_no_model_path_mints_seeds(self, tmp_path):
        db = tmp_path / "kaos.db"
        afs = Kaos(db_path=str(db))
        from kaos.experiments import ExperimentStore
        store = ExperimentStore(str(db))
        store.log_run(name="pfa-probe", family="probe",
                      verdict="REJECT: kill gate(s) failed: G1", git_sha="")
        store.close()
        afs.close()
        cfg = tmp_path / "kaos.yaml"
        cfg.write_text("bench:\n  enabled: true\n")
        r = CliRunner().invoke(cli, ["--json", "bench", "harvest", "--db", str(db),
                                     "--config-file", str(cfg)])
        assert r.exit_code == 0, r.output
        r2 = CliRunner().invoke(cli, ["--json", "bench", "validate", "--db", str(db),
                                      "--config-file", str(cfg), "--no-model"])
        assert r2.exit_code == 0, r2.output
        rep = json.loads(r2.output)
        assert rep["minted_mechanism_evals"] == 1
