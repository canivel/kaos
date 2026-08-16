"""kaos.bench.pull + config — the feed-back half and the SaaS integration surface."""

from __future__ import annotations

import json
import os

import pytest

from kaos.bench.config import load_bench_config
from kaos.bench.fingerprint import Grain, Level, TaskShape, anchor_tokens
from kaos.bench.pull import pull, report_outcome
from kaos.bench.schema import bench_id, fts_index_record, open_bench


@pytest.fixture
def bench(tmp_path):
    conn = open_bench(tmp_path / "b.bench.db")
    yield conn
    conn.close()


def _admit(bench, cid_suffix, *, name, trust=2, verdict="ACCEPT",
           consumes=(), keys="", wilson=0.8, kind="skill"):
    cid = "tb1:" + cid_suffix * 64
    env = {"consumes": list(consumes), "measured": {"M1": int(Level.PRESENT)},
           "m2_grain": int(Grain.EPISODE),
           "retrieval_keys": sorted(anchor_tokens(keys)), "wilson_lb": wilson}
    bench.execute(
        "INSERT INTO eval_records (record_cid, schema_id, kind, self_test_passed,"
        " verdict, variant, faithful, trust_level, repro_class, envelope_json,"
        " body_json, origin_bench_id) VALUES (?, 'transferbench/eval_record/v1',"
        " ?, 1, ?, 'as-is', 1, ?, 'llm_nondeterministic', ?, ?, ?)",
        (cid, kind, verdict, trust, json.dumps(env),
         json.dumps({"name": name}), bench_id(bench)))
    fts_index_record(bench, cid, name=name, keys_text=keys)
    return cid


def _task(text="fix retry_backoff in pipelines/scrape.py", m2=Level.PRESENT):
    return TaskShape(m1=Level.PRESENT, m2=m2, m4=Level.ABSENT,
                     m2_grain=Grain.EPISODE, m3_anchor_tokens=anchor_tokens(text))


class TestPull:
    def test_serves_relevant_validated_item_with_ledger(self, bench):
        cid = _admit(bench, "a", name="retry backoff skill",
                     keys="retry_backoff pipelines/scrape.py")
        res = pull(bench, agent_id="ag1", task_text="fix retry_backoff in pipelines/scrape.py",
                   task_shape=_task(), shadow_rate=0.0)
        assert [i.record_cid for i in res.items] == [cid]
        dec = bench.execute("SELECT decision, fidelity FROM bench_pull_decisions").fetchone()
        assert dec["decision"] == "served"

    def test_t0_never_served(self, bench):
        _admit(bench, "b", name="retry backoff skill", trust=0,
               keys="retry_backoff pipelines/scrape.py")
        res = pull(bench, agent_id="ag1", task_text="fix retry_backoff in pipelines/scrape.py",
                   task_shape=_task(), shadow_rate=0.0)
        assert res.items == []

    def test_reject_verdict_never_served(self, bench):
        _admit(bench, "c", name="retry backoff skill", verdict="REJECT",
               keys="retry_backoff pipelines/scrape.py")
        res = pull(bench, agent_id="ag1", task_text="fix retry_backoff in pipelines/scrape.py",
                   task_shape=_task(), shadow_rate=0.0)
        assert res.items == []

    def test_quarantined_never_served(self, bench):
        cid = _admit(bench, "d", name="retry backoff skill",
                     keys="retry_backoff pipelines/scrape.py")
        bench.execute("INSERT INTO bench_item_state (record_cid, state)"
                      " VALUES (?, 'quarantined')", (cid,))
        res = pull(bench, agent_id="ag1", task_text="fix retry_backoff in pipelines/scrape.py",
                   task_shape=_task(), shadow_rate=0.0)
        assert res.items == []

    def test_consumed_axis_withheld_and_logged(self, bench):
        cid = _admit(bench, "e", name="retry backoff skill", consumes=("M2",),
                     keys="retry_backoff pipelines/scrape.py")
        # task has M2 unknown -> consumed-axis withhold, logged with reason
        shape = _task(m2=Level.UNKNOWN)
        res = pull(bench, agent_id="ag1", task_text="fix retry_backoff in pipelines/scrape.py",
                   task_shape=shape, shadow_rate=0.0)
        assert res.items == [] and res.withheld_count == 1
        row = bench.execute("SELECT decision, reason, axis FROM bench_pull_decisions"
                            " WHERE record_cid=?", (cid,)).fetchone()
        assert row["decision"] == "withheld" and row["axis"] == "M2"

    def test_k_cap_and_outranked_logged(self, bench):
        for i, s in enumerate("fghij"):
            _admit(bench, s, name=f"retry variant {i}", wilson=0.9 - i * 0.1,
                   keys="retry_backoff pipelines/scrape.py")
        res = pull(bench, agent_id="ag1", task_text="fix retry_backoff in pipelines/scrape.py",
                   task_shape=_task(), shadow_rate=0.0)
        assert len(res.items) == 3          # K=3 (R6)
        decs = {r["decision"] for r in bench.execute(
            "SELECT decision FROM bench_pull_decisions")}
        assert "outranked" in decs           # the not-served are data too

    def test_empty_pull_is_logged_success(self, bench):
        res = pull(bench, agent_id="ag1", task_text="totally unrelated quantum task",
                   task_shape=_task("totally unrelated quantum task"), shadow_rate=0.0)
        assert res.items == []
        n = bench.execute("SELECT COUNT(*) FROM bench_pulls").fetchone()[0]
        assert n == 1                        # the pull itself is recorded

    def test_outcome_closes_loop(self, bench):
        cid = _admit(bench, "k", name="retry backoff skill",
                     keys="retry_backoff pipelines/scrape.py")
        report_outcome(bench, record_cid=cid, agent_id="ag1", invoked=True,
                       outcome=True, outcome_source="runner")
        row = bench.execute("SELECT outcome, outcome_source FROM outcome_telemetry").fetchone()
        assert row["outcome"] == 1 and row["outcome_source"] == "runner"


class TestBenchConfig:
    def test_missing_file_is_disabled(self, tmp_path):
        cfg = load_bench_config(tmp_path / "nope.yaml")
        assert cfg.enabled is False and cfg.resolved_publish_scope() == "local"

    def test_individual_defaults_public_queue(self, tmp_path, monkeypatch):
        p = tmp_path / "kaos.yaml"
        p.write_text("bench:\n  enabled: true\n  endpoint: https://api.tb.dev\n"
                     "  workspace: me\n  tier: individual\n")
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "tok_123")
        cfg = load_bench_config(p)
        assert cfg.resolved_publish_scope() == "public_queue"   # D5: public default
        assert cfg.token() == "tok_123" and cfg.problems == []

    def test_team_defaults_private_workspace(self, tmp_path, monkeypatch):
        p = tmp_path / "kaos.yaml"
        p.write_text("bench:\n  enabled: true\n  endpoint: https://api.tb.dev\n"
                     "  workspace: acme\n  tier: team\n")
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "tok_456")
        assert load_bench_config(p).resolved_publish_scope() == "workspace"

    def test_missing_token_flagged(self, tmp_path, monkeypatch):
        monkeypatch.delenv("KAOS_BENCH_TOKEN", raising=False)
        p = tmp_path / "kaos.yaml"
        p.write_text("bench:\n  enabled: true\n  endpoint: https://api.tb.dev\n"
                     "  workspace: acme\n  tier: team\n")
        cfg = load_bench_config(p)
        assert any("token" in w.lower() for w in cfg.problems)

    def test_token_in_yaml_is_flagged(self, tmp_path):
        p = tmp_path / "kaos.yaml"
        p.write_text("bench:\n  enabled: true\n  token: sk_live_oops\n")
        cfg = load_bench_config(p)
        assert any("environment" in w for w in cfg.problems)
