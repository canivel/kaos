"""Brick 10 — schema v2 evidence columns, episode arms, and the pre-registered
binding kill-gate probe (demo_attraktor_loop_bench)."""

from __future__ import annotations

import json
import sqlite3

import pytest

from demo_attraktor_loop_bench.gates import (
    LoopStats,
    compute_gates,
    newcombe_diff_lb,
    p95,
)
from demo_attraktor_loop_bench.probe_adapter import (
    collect_stats,
    falsify,
    run_probe,
    status,
)
from kaos.bench.config import BenchConfig
from kaos.bench.fingerprint import Grain, Level, anchor_tokens
from kaos.bench.hooks import (
    ARM_OFF_RATE,
    ARM_ON_RATE,
    ARM_SCRAMBLED_RATE,
    BenchHooks,
    assign_arm,
)
from kaos.bench.replay import scramble_payload
from kaos.bench.schema import bench_id, fts_index_record, open_bench
from kaos.eval.harness.manifest import LockTamperError, load_lock
from kaos.eval.harness.verdict import compute_verdict


# ── schema v2 migration ──────────────────────────────────────────────

class TestMigration:
    def test_v1_db_gains_probe_columns(self, tmp_path):
        """A pre-v2 bench.db (no latency/arm/pull_id columns) migrates in place."""
        p = tmp_path / "old.db"
        conn = sqlite3.connect(str(p))
        conn.executescript("""
            CREATE TABLE bench_schema_version (version INTEGER NOT NULL);
            INSERT INTO bench_schema_version VALUES (1);
            CREATE TABLE bench_pulls (
                pull_id TEXT PRIMARY KEY, agent_id TEXT NOT NULL, task_hash TEXT,
                fingerprint_json TEXT NOT NULL DEFAULT '{}', k INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
            CREATE TABLE outcome_telemetry (
                telemetry_id TEXT PRIMARY KEY, record_cid TEXT NOT NULL,
                agent_id TEXT NOT NULL, task_hash TEXT,
                invoked INTEGER NOT NULL, outcome INTEGER,
                outcome_source TEXT NOT NULL, fidelity REAL,
                shadow INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')));
        """)
        conn.commit()
        conn.close()

        bench = open_bench(p)
        pulls_cols = {r[1] for r in bench.execute("PRAGMA table_info(bench_pulls)")}
        tel_cols = {r[1] for r in bench.execute("PRAGMA table_info(outcome_telemetry)")}
        version = bench.execute("SELECT version FROM bench_schema_version").fetchone()[0]
        bench.close()
        assert {"latency_ms", "arm"} <= pulls_cols
        assert {"pull_id", "arm"} <= tel_cols
        assert version == 2

    def test_fresh_db_is_v2(self, tmp_path):
        bench = open_bench(tmp_path / "new.db")
        assert bench.execute("SELECT version FROM bench_schema_version").fetchone()[0] == 2
        bench.close()


# ── arm assignment ───────────────────────────────────────────────────

class TestArmAssignment:
    def test_deterministic(self):
        assert assign_arm("agent-1", "abcd1234") == assign_arm("agent-1", "abcd1234")

    def test_rates_approximate_lock(self):
        counts = {"on": 0, "off": 0, "scrambled": 0}
        n = 4000
        for i in range(n):
            counts[assign_arm(f"a{i}", f"t{i}")] += 1
        assert abs(counts["on"] / n - ARM_ON_RATE) < 0.03
        assert abs(counts["off"] / n - ARM_OFF_RATE) < 0.03
        assert abs(counts["scrambled"] / n - ARM_SCRAMBLED_RATE) < 0.02

    def test_all_arms_reachable(self):
        seen = set()
        for i in range(200):
            seen.add(assign_arm(f"a{i}", "same-task"))
        assert seen == {"on", "off", "scrambled"}


# ── hooks in probe mode ──────────────────────────────────────────────

def _admit(bench, *, name="retry backoff skill", keys="retry_backoff pipelines/scrape.py"):
    cid = "tb1:" + "e" * 64
    env = {"consumes": [], "measured": {"M2": int(Level.PRESENT)},
           "m2_grain": int(Grain.EPISODE),
           "retrieval_keys": sorted(anchor_tokens(keys)), "wilson_lb": 0.8}
    bench.execute(
        "INSERT INTO eval_records (record_cid, schema_id, kind, self_test_passed,"
        " verdict, variant, faithful, trust_level, repro_class, envelope_json,"
        " body_json, origin_bench_id) VALUES (?, 'attraktor/eval_record/v1',"
        " 'skill', 1, 'ACCEPT', 'as-is', 1, 2, 'llm_nondeterministic', ?, ?, ?)",
        (cid, json.dumps(env),
         json.dumps({"name": name, "template": "retry with exponential backoff"}),
         bench_id(bench)))
    fts_index_record(bench, cid, name=name, keys_text=keys)
    bench.commit()
    return cid


TASK = "fix retry_backoff in pipelines/scrape.py"


def _agent_for_arm(want: str) -> str:
    """Find an agent_id whose deterministic assignment for TASK is `want`."""
    from kaos.bench.hooks import _task_hash
    th = _task_hash(TASK)
    for i in range(10000):
        if assign_arm(f"agent-{i}", th) == want:
            return f"agent-{i}"
    raise AssertionError(f"no agent found for arm {want}")


@pytest.fixture
def probe_ws(tmp_path):
    bench = open_bench(tmp_path / "bench.db")
    _admit(bench)
    bench.close()
    cfg = BenchConfig(enabled=True, local_bench_path="bench.db")  # arms_mode=probe
    return tmp_path, BenchHooks(cfg, db_dir=tmp_path)


class TestHookArms:
    def test_on_arm_injects_and_ledgers(self, probe_ws):
        tmp_path, hooks = probe_ws
        agent = _agent_for_arm("on")
        inj = hooks.on_task_start(agent, TASK)
        assert inj is not None and "retry with exponential backoff" in inj
        hooks.on_task_end(agent, succeeded=True)
        bench = open_bench(tmp_path / "bench.db")
        row = bench.execute("SELECT arm, invoked, outcome, pull_id "
                            "FROM outcome_telemetry").fetchone()
        pull = bench.execute("SELECT arm, latency_ms FROM bench_pulls").fetchone()
        bench.close()
        assert row["arm"] == "on" and row["invoked"] == 1 and row["outcome"] == 1
        assert row["pull_id"] is not None
        assert pull["arm"] == "on" and pull["latency_ms"] is not None

    def test_off_arm_no_injection_but_counterfactual_recorded(self, probe_ws):
        tmp_path, hooks = probe_ws
        agent = _agent_for_arm("off")
        assert hooks.on_task_start(agent, TASK) is None      # nothing injected
        hooks.on_task_end(agent, succeeded=False)
        bench = open_bench(tmp_path / "bench.db")
        row = bench.execute("SELECT arm, invoked, outcome FROM outcome_telemetry").fetchone()
        n_dec = bench.execute("SELECT COUNT(*) FROM bench_pull_decisions "
                              "WHERE decision IN ('served','shadow')").fetchone()[0]
        bench.close()
        assert row["arm"] == "off" and row["invoked"] == 0 and row["outcome"] == 0
        assert n_dec >= 1                                     # match fully ledgered

    def test_scrambled_arm_injects_placebo(self, probe_ws):
        _, hooks = probe_ws
        agent = _agent_for_arm("scrambled")
        inj = hooks.on_task_start(agent, TASK)
        assert inj is not None
        assert scramble_payload("retry with exponential backoff") in inj
        assert "Validated workspace learnings" in inj          # honesty surface kept

    def test_serve_mode_never_assigns_off(self, tmp_path):
        bench = open_bench(tmp_path / "bench.db")
        _admit(bench)
        bench.close()
        cfg = BenchConfig(enabled=True, local_bench_path="bench.db", arms_mode="serve")
        hooks = BenchHooks(cfg, db_dir=tmp_path)
        agent = _agent_for_arm("off")                          # would be off in probe mode
        assert hooks.on_task_start(agent, TASK) is not None


# ── gates ────────────────────────────────────────────────────────────

def _stats(*, on=(40, 45), off=(20, 45), scr=(4, 10), n_pulls=100,
           matched=100, lat=5.0) -> LoopStats:
    def arm(w, n):
        return [1] * w + [0] * (n - w)
    return LoopStats(
        outcomes={"on": arm(*on), "off": arm(*off), "scrambled": arm(*scr)},
        latencies_ms=[lat] * n_pulls, n_pulls=n_pulls, n_matched_pulls=matched)


class TestGates:
    def test_all_pass_accepts(self):
        gates = compute_gates(_stats())
        assert compute_verdict(gates, judge_kappa=None) == "ACCEPT"

    def test_no_lift_rejects_g1(self):
        gates = compute_gates(_stats(on=(20, 45)))            # on == off
        v = compute_verdict(gates, judge_kappa=None)
        assert v.startswith("REJECT") and "G1" in v

    def test_placebo_kills_g4(self):
        gates = compute_gates(_stats(on=(40, 45), scr=(10, 10)))
        v = compute_verdict(gates, judge_kappa=None)
        assert v.startswith("REJECT") and "G4" in v

    def test_slow_pulls_kill_g2(self):
        gates = compute_gates(_stats(lat=500.0))
        v = compute_verdict(gates, judge_kappa=None)
        assert v.startswith("REJECT") and "G2" in v

    def test_match_famine_kills_g3(self):
        gates = compute_gates(_stats(matched=10))              # 10% < 20% floor
        v = compute_verdict(gates, judge_kappa=None)
        assert v.startswith("REJECT") and "G3" in v

    def test_floors_unmet_voids(self):
        gates = compute_gates(_stats(on=(4, 5), off=(2, 5), scr=(1, 2), n_pulls=12,
                                     matched=12))
        v = compute_verdict(gates, judge_kappa=None)
        assert v.startswith("VOID")

    def test_arm_balance_drift_voids(self):
        # floors met but off-arm hugely over-represented vs locked 0.45
        gates = compute_gates(_stats(on=(25, 30), off=(40, 90), scr=(4, 10)))
        v = compute_verdict(gates, judge_kappa=None)
        assert v.startswith("VOID")

    def test_newcombe_identical_arms_negative(self):
        assert newcombe_diff_lb(20, 45, 20, 45) < 0.0

    def test_p95(self):
        assert p95([1.0] * 94 + [1000.0] * 6) == 1000.0
        assert p95([1.0] * 100 + [1000.0] * 4) == 1.0


# ── lock tamper refusal ──────────────────────────────────────────────

class TestLockDiscipline:
    def test_edited_lock_refused(self, tmp_path):
        from demo_attraktor_loop_bench.gates import KNOWN_LOCK_SHA256, LOCK_PATH
        tampered = tmp_path / "ISA.lock.json"
        data = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
        data["kill_gates"]["G3"]["threshold"] = 0.01           # the classic retune
        tampered.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(LockTamperError):
            load_lock(tampered, KNOWN_LOCK_SHA256)

    def test_registered_lock_loads(self):
        from demo_attraktor_loop_bench.gates import load
        lock = load()
        assert lock["name"] == "attraktor-loop-binding-probe"


# ── adapter end-to-end on a synthetic bench.db ───────────────────────

def _seed_bench(bench, *, on=(40, 45), off=(20, 45), scr=(4, 10)):
    cid = _admit(bench)
    i = 0
    for arm_name, (wins, n) in (("on", on), ("off", off), ("scrambled", scr)):
        for j in range(n):
            pid = f"pull-{arm_name}-{j}"
            bench.execute(
                "INSERT INTO bench_pulls (pull_id, agent_id, task_hash,"
                " k, arm, latency_ms) VALUES (?, ?, ?, 3, ?, 5.0)",
                (pid, f"a{i}", f"t{i}", arm_name))
            bench.execute(
                "INSERT INTO bench_pull_decisions (pull_id, record_cid, decision)"
                " VALUES (?, ?, 'served')", (pid, cid))
            bench.execute(
                "INSERT INTO outcome_telemetry (telemetry_id, record_cid, agent_id,"
                " invoked, outcome, outcome_source, pull_id, arm)"
                " VALUES (?, ?, ?, ?, ?, 'runner', ?, ?)",
                (f"tel-{i}", cid, f"a{i}", 0 if arm_name == "off" else 1,
                 1 if j < wins else 0, pid, arm_name))
            i += 1
    bench.commit()


class TestProbeAdapter:
    def test_collect_stats_matches_seed(self, tmp_path):
        bench = open_bench(tmp_path / "bench.db")
        _seed_bench(bench)
        stats = collect_stats(bench)
        bench.close()
        assert stats.n("on") == 45 and stats.wins("on") == 40
        assert stats.n("off") == 45 and stats.wins("off") == 20
        assert stats.n("scrambled") == 10 and stats.wins("scrambled") == 4
        assert stats.n_pulls == 100 and stats.n_matched_pulls == 100
        assert len(stats.latencies_ms) == 100

    def test_status_reports_progress_void_when_empty(self, tmp_path):
        bench = open_bench(tmp_path / "bench.db")
        rep = status(bench)
        bench.close()
        assert rep["verdict_if_bound_now"].startswith("VOID")
        assert rep["episodes"] == {"on": 0, "off": 0, "scrambled": 0}

    def test_binding_run_accepts_and_persists(self, tmp_path):
        bench = open_bench(tmp_path / "bench.db")
        _seed_bench(bench)
        rep = run_probe(bench, out_dir=tmp_path / "out")
        bench.close()
        assert rep["self_test_passed"] is True
        assert rep["verdict"] == "ACCEPT"
        on_file = json.loads((tmp_path / "out" / "results.json").read_text())
        assert on_file["verdict"] == "ACCEPT"

    def test_falsification_self_test_kills_inert_treatment(self, tmp_path):
        bench = open_bench(tmp_path / "bench.db")
        _seed_bench(bench)
        stats = collect_stats(bench)
        bench.close()
        can_kill, detail = falsify(stats)
        assert can_kill, detail

    def test_no_lift_binding_run_rejects(self, tmp_path):
        bench = open_bench(tmp_path / "bench.db")
        _seed_bench(bench, on=(20, 45))                        # on == off
        rep = run_probe(bench, out_dir=tmp_path / "out")
        bench.close()
        assert rep["verdict"].startswith("REJECT") and "G1" in rep["verdict"]
        assert rep["self_test_passed"] is True                 # harness CAN kill
