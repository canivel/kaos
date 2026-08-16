"""kaos.bench.hooks + runner wiring — the loop closes automatically (brick 8)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from kaos import Kaos
from kaos.bench.config import BenchConfig
from kaos.bench.fingerprint import Grain, Level, anchor_tokens
from kaos.bench.hooks import BenchHooks
from kaos.bench.schema import bench_id, fts_index_record, open_bench
from kaos.ccr.runner import ClaudeCodeRunner


def _admit(bench, *, name, keys, trust=2):
    cid = "tb1:" + "e" * 64
    env = {"consumes": [], "measured": {"M2": int(Level.PRESENT)},
           "m2_grain": int(Grain.EPISODE),
           "retrieval_keys": sorted(anchor_tokens(keys)), "wilson_lb": 0.8}
    bench.execute(
        "INSERT INTO eval_records (record_cid, schema_id, kind, self_test_passed,"
        " verdict, variant, faithful, trust_level, repro_class, envelope_json,"
        " body_json, origin_bench_id) VALUES (?, 'attraktor/eval_record/v1',"
        " 'skill', 1, 'ACCEPT', 'as-is', 1, ?, 'llm_nondeterministic', ?, ?, ?)",
        (cid, trust, json.dumps(env),
         json.dumps({"name": name, "template": "retry with exponential backoff"}),
         bench_id(bench)))
    fts_index_record(bench, cid, name=name, keys_text=keys)
    bench.commit()
    return cid


@pytest.fixture
def ws(tmp_path):
    bench = open_bench(tmp_path / "bench.db")
    _admit(bench, name="retry backoff skill", keys="retry_backoff pipelines/scrape.py")
    bench.close()
    # arms_mode='serve' pins the always-inject behavior these tests assert;
    # probe-mode arm assignment is covered in test_attraktor_probe.py.
    cfg = BenchConfig(enabled=True, local_bench_path="bench.db", arms_mode="serve")
    return tmp_path, BenchHooks(cfg, db_dir=tmp_path)


class TestHooks:
    def test_disabled_is_total_noop(self, tmp_path):
        hooks = BenchHooks(BenchConfig(enabled=False), db_dir=tmp_path)
        assert hooks.on_task_start("a1", "fix retry_backoff in pipelines/scrape.py") is None
        hooks.on_task_end("a1", succeeded=True)  # must not raise, writes nothing
        assert not (tmp_path / "bench.db").exists()

    def test_injection_carries_honesty_surface(self, ws):
        tmp_path, hooks = ws
        inj = hooks.on_task_start("a1", "fix retry_backoff in pipelines/scrape.py")
        assert inj is not None
        assert "trust=T2" in inj and "fidelity=" in inj      # mandatory disclosure
        assert "advisory" in inj                              # not commands
        assert "retry with exponential backoff" in inj        # the payload itself

    def test_end_writes_runner_sourced_outcome(self, ws):
        tmp_path, hooks = ws
        hooks.on_task_start("a1", "fix retry_backoff in pipelines/scrape.py")
        hooks.on_task_end("a1", succeeded=True)
        bench = open_bench(tmp_path / "bench.db")
        row = bench.execute("SELECT outcome, outcome_source, invoked "
                            "FROM outcome_telemetry").fetchone()
        bench.close()
        assert row["outcome"] == 1 and row["outcome_source"] == "runner"

    def test_failure_outcome_recorded(self, ws):
        tmp_path, hooks = ws
        hooks.on_task_start("a1", "fix retry_backoff in pipelines/scrape.py")
        hooks.on_task_end("a1", succeeded=False)
        bench = open_bench(tmp_path / "bench.db")
        assert bench.execute("SELECT outcome FROM outcome_telemetry").fetchone()[0] == 0
        bench.close()

    def test_no_match_no_exposure(self, ws):
        _, hooks = ws
        assert hooks.on_task_start("a1", "unrelated quantum chromodynamics") is None
        hooks.on_task_end("a1", succeeded=True)  # nothing to write, no raise

    def test_hooks_never_raise_on_broken_bench(self, tmp_path):
        cfg = BenchConfig(enabled=True, local_bench_path="dir-not-a-db")
        (tmp_path / "dir-not-a-db").mkdir()      # opening this as sqlite will fail
        hooks = BenchHooks(cfg, db_dir=tmp_path)
        assert hooks.on_task_start("a1", "fix retry_backoff pipelines/scrape.py") is None


class _FakeRouter:
    """Single-turn router: returns a final answer, no tools."""
    clients = {"fake": object()}

    async def route(self, **kw):
        return SimpleNamespace(content="done", tool_calls=[],
                               stop_reason="end_turn", usage={})


class TestRunnerWiring:
    def test_loop_closes_end_to_end(self, ws, tmp_path):
        _, hooks = ws
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        runner = ClaudeCodeRunner(afs, _FakeRouter(), bench_hooks=hooks)
        agent_id = afs.spawn("worker")
        result = asyncio.run(
            runner.run_agent(agent_id, "fix retry_backoff in pipelines/scrape.py"))
        assert result == "done"

        # injection reached the system prompt
        convo = afs.get_state_or(agent_id, "conversation")
        assert "Validated workspace learnings" in convo[0]["content"]
        # and the outcome row closed the loop with a runner-sourced success
        bench = open_bench(tmp_path / "bench.db")
        row = bench.execute("SELECT outcome, outcome_source FROM outcome_telemetry").fetchone()
        bench.close()
        assert row["outcome"] == 1 and row["outcome_source"] == "runner"
        afs.close()

    def test_without_hooks_nothing_changes(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "k2.db"))
        runner = ClaudeCodeRunner(afs, _FakeRouter())     # no hooks param
        agent_id = afs.spawn("worker")
        result = asyncio.run(runner.run_agent(agent_id, "any task"))
        assert result == "done"
        convo = afs.get_state_or(agent_id, "conversation")
        assert "Validated workspace learnings" not in convo[0]["content"]
        afs.close()
