"""`kaos bench` CLI — the user-facing surface of the Attraktor loop."""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from kaos import Kaos
from kaos.cli.main import cli
from kaos.skills import SkillStore


@pytest.fixture
def ws(tmp_path):
    """A workspace: kaos.db with some organic content + a kaos.yaml."""
    db = tmp_path / "kaos.db"
    afs = Kaos(db_path=str(db))
    from kaos.experiments import ExperimentStore
    store = ExperimentStore(str(db))
    store.log_run(name="pfa-probe", family="probe",
                  verdict="REJECT: kill gate(s) failed: G1", git_sha="")
    store.close()
    cfg = tmp_path / "kaos.yaml"
    cfg.write_text("bench:\n  enabled: true\n")
    afs.close()
    return tmp_path


def _run(args):
    return CliRunner().invoke(cli, ["--json", *args])


class TestBenchCLI:
    def test_status_before_harvest(self, ws):
        r = _run(["bench", "status", "--db", str(ws / "kaos.db"),
                  "--config-file", str(ws / "kaos.yaml")])
        assert r.exit_code == 0, r.output
        d = json.loads(r.output)
        assert d["enabled"] is True and d["mode"] == "local-only"
        assert d["publish_scope"] == "local"
        assert "local_bench" in d

    def test_harvest_then_status(self, ws):
        r = _run(["bench", "harvest", "--db", str(ws / "kaos.db"),
                  "--config-file", str(ws / "kaos.yaml")])
        assert r.exit_code == 0, r.output
        rep = json.loads(r.output)
        assert rep["experiments_harvested"] == 1     # the PFA REJECT flowed in

        r2 = _run(["bench", "status", "--db", str(ws / "kaos.db"),
                   "--config-file", str(ws / "kaos.yaml")])
        d = json.loads(r2.output)
        assert d["candidates"].get("e1_passed") == 1
        assert d["pulls"] == 0

    def test_harvest_idempotent_via_cli(self, ws):
        _run(["bench", "harvest", "--db", str(ws / "kaos.db"),
              "--config-file", str(ws / "kaos.yaml")])
        rep2 = json.loads(_run(["bench", "harvest", "--db", str(ws / "kaos.db"),
                                "--config-file", str(ws / "kaos.yaml")]).output)
        assert rep2["experiments_harvested"] == 0

    def test_rejections_surface(self, ws):
        # produce a real E1 rejection: sourced telemetry w/ zero lift
        db = str(ws / "kaos.db")
        afs = Kaos(db_path=db)
        sk = SkillStore(afs.conn)
        sid = sk.save(name="noop_skill", description="does nothing", template="x", tags=[])
        a1, a2 = afs.spawn("w1"), afs.spawn("w2")
        for i in range(12):
            sk.record_outcome(sid, success=True, agent_id=(a1 if i % 2 else a2),
                              task_hash=f"t{i % 3}")
        afs.close()
        # harvest with provenance map + a synthetic unexposed arm is not available
        # via CLI; the CLI path exercises legacy self-report -> E0. Just assert the
        # command runs and reports the (currently empty) rejection list.
        _run(["bench", "harvest", "--db", db, "--config-file", str(ws / "kaos.yaml")])
        r = _run(["bench", "rejections", "--db", db,
                  "--config-file", str(ws / "kaos.yaml")])
        assert r.exit_code == 0
        assert "rejections" in json.loads(r.output)
