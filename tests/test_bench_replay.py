"""kaos.bench.replay — E2 held-out replay probe + admission minting (brick 6).

No real LLM: completion/judge are injected fakes shaped per scenario. The probe
must be able to KILL (scrambled + B0 self-tests), refuse edited manifests, and
mint a pullable record only on a real, non-vacuous pass.
"""

from __future__ import annotations

import json

import pytest

from kaos import Kaos
from kaos.bench.fingerprint import Grain, Level, TaskShape, anchor_tokens
from kaos.bench.pull import pull
from kaos.bench.replay import (
    build_manifest, manifest_sha256, run_e2, scramble_payload,
    validate_candidate_e2,
)
from kaos.bench.schema import open_bench

PAYLOAD = "use exponential backoff retry {n} times before giving up"
INTACT = "exponential backoff retry"          # destroyed by scrambling


def _seed_tasks(afs, n=20):
    """Tasks across two strata: code_path (file anchors) and identifier."""
    for i in range(n):
        a = afs.spawn(f"t{i}")
        if i % 2 == 0:
            task = f"fix retry_backoff logic in pipelines/scrape_{i}.py"
        else:
            task = f"tune retry_backoff threshold for worker_pool {i}"
        afs.conn.execute(
            "INSERT OR REPLACE INTO state (agent_id, key, value) VALUES (?, 'task', ?)",
            (a, json.dumps(task)))
    afs.conn.commit()


def _candidate(bench, payload=None):
    bench.execute(
        "INSERT INTO bench_candidates (candidate_id, source_kind, source_ref,"
        " kind, status, payload_json) VALUES ('cand1', 'skill_telemetry',"
        " 'skill:999', 'skill', 'e1_passed', ?)",
        (json.dumps(payload or {"name": "retry backoff skill",
                                "template": PAYLOAD,
                                "description": "retry_backoff for flaky pipelines"}),))
    bench.commit()


@pytest.fixture
def ws(tmp_path):
    afs = Kaos(db_path=str(tmp_path / "kaos.db"))
    _seed_tasks(afs)
    bench = open_bench(tmp_path / "bench.db")
    _candidate(bench)
    yield afs, bench
    bench.close()
    afs.close()


def _complete(prompt: str) -> str:
    return prompt          # echo: the judge inspects what the arm was given


def _judge_lift(task, out):
    return 0.9 if INTACT in out else 0.4      # intact payload helps; scrambled doesn't


def _judge_flat(task, out):
    return 0.5                                 # nothing helps


def _judge_harm(task, out):
    return 0.3 if "[Guidance]" in out else 0.8  # any injection hurts


def _judge_padding(task, out):
    return 0.9 if "[Guidance]" in out else 0.4  # ANY padding "helps" — incl. scrambled


class TestScramble:
    def test_placeholders_survive_words_shuffle(self):
        s = scramble_payload(PAYLOAD)
        assert "{n}" in s
        assert sorted(s.replace("{n}", "").split()) == \
               sorted(PAYLOAD.replace("{n}", "").split())
        assert INTACT not in s                 # instruction destroyed (seeded)


class TestE2Outcomes:
    def test_real_lift_passes_and_mints_pullable_record(self, ws):
        afs, bench = ws
        res = validate_candidate_e2(afs.conn, bench, "cand1",
                                    complete=_complete, judge=_judge_lift)
        assert res.status == "passed", res.reason
        assert res.record_cid is not None
        row = bench.execute("SELECT status, record_cid FROM bench_candidates").fetchone()
        assert row["status"] == "admitted" and row["record_cid"] == res.record_cid
        # minted at T2, ACCEPT, and actually PULLABLE:
        shape = TaskShape(m1=Level.UNKNOWN, m2=Level.PRESENT, m4=Level.UNKNOWN,
                          m2_grain=Grain.EPISODE,
                          m3_anchor_tokens=anchor_tokens(
                              "fix retry_backoff in pipelines/scrape.py"))
        pr = pull(bench, agent_id="ax", task_text="fix retry_backoff in pipelines/scrape.py",
                  task_shape=shape, shadow_rate=0.0)
        assert [i.record_cid for i in pr.items] == [res.record_cid]
        assert pr.items[0].trust_level == 2

    def test_no_lift_rejected_with_reasoning(self, ws):
        afs, bench = ws
        res = validate_candidate_e2(afs.conn, bench, "cand1",
                                    complete=_complete, judge=_judge_flat)
        assert res.status == "rejected"
        row = bench.execute("SELECT status, rejection_reason FROM bench_candidates").fetchone()
        assert row["status"] == "e2_rejected"
        assert "G2" in row["rejection_reason"]              # the why is stored (D0.1)
        assert bench.execute("SELECT COUNT(*) FROM eval_records").fetchone()[0] == 0

    def test_harmful_killed_by_g1(self, ws):
        afs, bench = ws
        res = validate_candidate_e2(afs.conn, bench, "cand1",
                                    complete=_complete, judge=_judge_harm)
        assert res.status == "rejected" and "G1" in res.reason

    def test_padding_judge_is_inadmissible(self, ws):
        # scrambled arm also scores high -> the harness measures context-padding
        afs, bench = ws
        res = validate_candidate_e2(afs.conn, bench, "cand1",
                                    complete=_complete, judge=_judge_padding)
        assert res.status == "harness_cannot_kill"
        row = bench.execute("SELECT status FROM bench_candidates").fetchone()
        assert row["status"] == "e2_rejected"               # rejected, reason recorded
        assert "context-padding" in res.reason

    def test_manifest_tamper_refused(self, ws):
        afs, _ = ws
        m = build_manifest(afs.conn, candidate_text=PAYLOAD, exclude_agent_ids=set())
        sha = manifest_sha256(m)
        m["contexts"][0]["task_text"] = "edited after locking"
        res = run_e2(m, sha, payload=PAYLOAD, complete=_complete, judge=_judge_lift)
        assert res.status == "not_runnable" and "refuses" in res.reason

    def test_single_stratum_downgraded(self, ws):
        afs, _ = ws
        m = build_manifest(afs.conn, candidate_text=PAYLOAD, exclude_agent_ids=set())
        for c in m["contexts"]:
            c["stratum"] = "code_path"                       # vacuous harm gate
        res = run_e2(m, manifest_sha256(m), payload=PAYLOAD,
                     complete=_complete, judge=_judge_lift)
        assert res.status == "downgraded_e1" and "vacuous" in res.reason


class TestHeldOut:
    def test_producing_agents_excluded(self, ws):
        afs, _ = ws
        excluded = {f"agent-under-test-{i}" for i in range(3)}
        m = build_manifest(afs.conn, candidate_text=PAYLOAD,
                           exclude_agent_ids=excluded)
        assert m is not None
        assert not ({c["agent_id"] for c in m["contexts"]} & excluded)

    def test_insufficient_contexts_stays_e1(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "k.db"))
        _seed_tasks(afs, n=3)                                # < k=12
        bench = open_bench(tmp_path / "b.db")
        _candidate(bench)
        res = validate_candidate_e2(afs.conn, bench, "cand1",
                                    complete=_complete, judge=_judge_lift)
        assert res.status == "not_runnable" and "held-out contexts" in res.reason
        assert bench.execute("SELECT status FROM bench_candidates").fetchone()[0] == "e1_passed"
        bench.close()
        afs.close()
