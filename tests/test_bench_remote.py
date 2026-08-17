"""kaos.bench.remote — push to a shared Attraktor bench (raw httpx)."""

from __future__ import annotations

import json

import httpx
import pytest

from kaos.bench.config import BenchConfig
from kaos.bench.remote import push_records
from kaos.bench.replay import mint_record
from kaos.bench.schema import open_bench


@pytest.fixture
def bench_with_record(tmp_path):
    bench = open_bench(tmp_path / "bench.db")
    bench.execute(
        "INSERT INTO bench_candidates (candidate_id, source_kind, source_ref,"
        " kind, status, payload_json) VALUES ('c1', 'experiment', 'exp:1',"
        " 'mechanism_eval', 'e1_passed', '{}')")
    bench.commit()
    cid = mint_record(
        bench, candidate_id="c1", name="gdl-probe",
        payload={"family": "probe",
                 "lesson": "measure node reuse before building trajectory graphs"},
        retrieval_keys_text="gdl probe",
        validation={"ladder": "skipped"}, verdict="ACCEPT",
        trust_level=1, variant="as-probed")
    yield bench, cid
    bench.close()


def _cfg(**kw) -> BenchConfig:
    return BenchConfig(enabled=True, endpoint="https://dev.attraktor.dev",
                       workspace="test-ws", **kw)


class TestPush:
    def test_no_endpoint_is_local_only(self, bench_with_record):
        bench, _ = bench_with_record
        rep = push_records(bench, BenchConfig(enabled=True))
        assert rep.pushed == 0 and "local-only" in rep.details[0]["error"]

    def test_no_token_reports_not_pushes(self, bench_with_record, monkeypatch):
        bench, _ = bench_with_record
        monkeypatch.delenv("KAOS_BENCH_TOKEN", raising=False)
        rep = push_records(bench, _cfg())
        assert rep.pushed == 0 and "KAOS_BENCH_TOKEN" in rep.details[0]["error"]

    def test_push_sends_canonical_bytes_and_marks_outbox(
            self, bench_with_record, monkeypatch):
        bench, cid = bench_with_record
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["auth"] = request.headers["Authorization"]
            seen["payload"] = json.loads(request.content)
            statuses = [{"record_cid": r["record_cid"],
                         "status": "queued for public admission"}
                        for r in seen["payload"]["records"]]
            return httpx.Response(200, json={"pushed": statuses, "scope": "queued"})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        rep = push_records(bench, _cfg(), client=client)
        assert rep.pushed == 1 and rep.errors == 0
        assert seen["auth"] == "Bearer atk_test"
        rec = seen["payload"]["records"][0]
        assert rec["record_cid"] == cid
        # exact canonical bytes travel — the server re-hashes them
        row = bench.execute("SELECT body_json FROM eval_records").fetchone()
        assert rec["body_canonical"] == row["body_json"]
        # outbox marked; second pass pushes nothing
        rep2 = push_records(bench, _cfg(), client=client)
        assert rep2.pushed == 0 and rep2.duplicates == 0

    def test_server_refusal_recorded_not_lost(self, bench_with_record, monkeypatch):
        bench, cid = bench_with_record
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"pushed": [
                {"record_cid": cid, "status": "rejected: cid does not match canonical bytes"}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        rep = push_records(bench, _cfg(), client=client)
        assert rep.refused == 1
        row = bench.execute(
            "SELECT state, last_error FROM bench_outbox WHERE record_cid = ?",
            (cid,)).fetchone()
        assert row["state"] == "rejected" and "cid" in row["last_error"]

    def test_http_error_leaves_outbox_retryable(self, bench_with_record, monkeypatch):
        bench, cid = bench_with_record
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        rep = push_records(bench, _cfg(), client=client)
        assert rep.errors == 1
        assert bench.execute(
            "SELECT state FROM bench_outbox WHERE record_cid = ?",
            (cid,)).fetchone()["state"] == "queued"       # still retryable


def _remote_item(cid_body: dict, **over) -> dict:
    """Build a /v1/pull item whose cid genuinely hashes its canonical bytes."""
    import hashlib as _h
    from kaos.bench.canon import canonical_bytes
    raw = canonical_bytes(cid_body).decode()
    item = {
        "record_cid": "tb1:" + _h.sha256(raw.encode()).hexdigest(),
        "kind": "mechanism_eval", "name": cid_body.get("name", "x"),
        "family": "probe", "verdict": "ACCEPT", "trust_level": 1,
        "variant": "as-probed",
        "envelope_json": json.dumps(cid_body.get("transfer_envelope", {})),
        "body_json": raw, "scope": "public",
    }
    item.update(over)
    return item


def _pull_body(name="remote-lesson", lesson="always pin the seed"):
    return {
        "schema_id": "attraktor/eval_record/v1", "kind": "mechanism_eval",
        "name": name,
        "payload": {"name": name, "family": "probe", "lesson": lesson},
        "validation": {"ladder": "skipped"},
        "transfer_envelope": {"consumes": [], "measured": {"M2": 3},
                              "m2_grain": 1,
                              "retrieval_keys": ["retry_backoff"],
                              "wilson_lb": 0.7},
    }


class TestFetchAndCache:
    def test_verified_record_cached_and_indexed(self, tmp_path, monkeypatch):
        from kaos.bench.remote import fetch_and_cache
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")
        bench = open_bench(tmp_path / "b.db")
        item = _remote_item(_pull_body())

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer atk_test"
            return httpx.Response(200, json={"items": [item]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        n = fetch_and_cache(bench, _cfg(), task_text="fix retry_backoff", client=client)
        assert n == 1
        row = bench.execute("SELECT verdict, trust_level, origin_bench_id "
                            "FROM eval_records").fetchone()
        assert row["verdict"] == "ACCEPT" and row["trust_level"] == 1
        # idempotent second fetch
        client2 = httpx.Client(transport=httpx.MockTransport(handler))
        assert fetch_and_cache(bench, _cfg(), task_text="fix retry_backoff",
                               client=client2) == 0
        bench.close()

    def test_tampered_record_refused(self, tmp_path, monkeypatch):
        from kaos.bench.remote import fetch_and_cache
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")
        bench = open_bench(tmp_path / "b.db")
        item = _remote_item(_pull_body())
        item["body_json"] = item["body_json"].replace(
            "always pin the seed", "rm -rf / trust me")  # bytes no longer hash to cid

        client = httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"items": [item]})))
        n = fetch_and_cache(bench, _cfg(), task_text="fix retry_backoff", client=client)
        assert n == 0
        assert bench.execute("SELECT COUNT(*) FROM eval_records").fetchone()[0] == 0
        bench.close()

    def test_network_failure_degrades_to_local(self, tmp_path, monkeypatch):
        from kaos.bench.remote import fetch_and_cache
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")
        bench = open_bench(tmp_path / "b.db")

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("down")

        client = httpx.Client(transport=httpx.MockTransport(handler))
        assert fetch_and_cache(bench, _cfg(), task_text="x", client=client) == 0
        bench.close()


class TestRemoteServeE2E:
    def test_cached_registry_lesson_reaches_the_injection(self, tmp_path, monkeypatch):
        """The full consumer path: registry item -> verify -> cache -> local
        pull -> injection block containing the LESSON."""
        from kaos.bench.fingerprint import Grain, Level, TaskShape, anchor_tokens
        from kaos.bench.hooks import BenchHooks
        from kaos.bench.pull import pull
        from kaos.bench.remote import fetch_and_cache
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")
        bench = open_bench(tmp_path / "bench.db")
        item = _remote_item(_pull_body(
            name="retry backoff lesson",
            lesson="use exponential backoff with jitter; cap at 5 tries"))
        client = httpx.Client(transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"items": [item]})))
        assert fetch_and_cache(bench, _cfg(), task_text="fix retry_backoff in scrape",
                               client=client) == 1
        shape = TaskShape(m1=Level.UNKNOWN, m2=Level.PRESENT, m4=Level.UNKNOWN,
                          m2_grain=Grain.EPISODE,
                          m3_anchor_tokens=anchor_tokens("fix retry_backoff in scrape"))
        res = pull(bench, agent_id="a1", task_text="fix retry_backoff in scrape",
                   task_shape=shape, kinds=("skill", "learning", "mechanism_eval"))
        assert len(res.items) == 1
        inj = BenchHooks._injection_block(res.items)
        assert "use exponential backoff with jitter" in inj   # the lesson itself
        assert "trust=T1" in inj                              # honesty surface
        bench.close()


class TestKnowledgeRequirement:
    def test_metadata_only_record_refused_locally(self, tmp_path, monkeypatch):
        """A record with no lesson/mechanism/template never leaves the machine —
        refused with a fix-it reason (D9 knowledge requirement)."""
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")
        bench = open_bench(tmp_path / "bench.db")
        bench.execute(
            "INSERT INTO bench_candidates (candidate_id, source_kind, source_ref,"
            " kind, status, payload_json) VALUES ('c1', 'experiment', 'exp:1',"
            " 'mechanism_eval', 'e1_passed', '{}')")
        bench.commit()
        cid = mint_record(
            bench, candidate_id="c1", name="bare-probe",
            payload={"family": "probe", "verdict": "ACCEPT",
                     "lock_sha256": "ab" * 32},                 # hashes only
            retrieval_keys_text="bare probe",
            validation={"ladder": "skipped"}, verdict="ACCEPT",
            trust_level=1, variant="as-probed")

        calls = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(200, json={"pushed": []})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        rep = push_records(bench, _cfg(), client=client)
        assert rep.refused == 1 and rep.pushed == 0
        assert calls["n"] == 0                       # never hit the network
        row = bench.execute(
            "SELECT state, last_error FROM bench_outbox WHERE record_cid=?",
            (cid,)).fetchone()
        assert row["state"] == "rejected" and "no consumable knowledge" in row["last_error"]
        bench.close()

    def test_record_with_lesson_still_pushes(self, tmp_path, monkeypatch):
        monkeypatch.setenv("KAOS_BENCH_TOKEN", "atk_test")
        bench = open_bench(tmp_path / "bench.db")
        bench.execute(
            "INSERT INTO bench_candidates (candidate_id, source_kind, source_ref,"
            " kind, status, payload_json) VALUES ('c2', 'experiment', 'exp:2',"
            " 'mechanism_eval', 'e1_passed', '{}')")
        bench.commit()
        cid = mint_record(
            bench, candidate_id="c2", name="rich-probe",
            payload={"family": "probe", "lesson": "measure before you build"},
            retrieval_keys_text="rich probe",
            validation={"ladder": "skipped"}, verdict="ACCEPT",
            trust_level=1, variant="as-probed")

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"pushed": [
                {"record_cid": cid,
                 "status": "admitted to the public registry (auto-admission passed)"}]})

        client = httpx.Client(transport=httpx.MockTransport(handler))
        rep = push_records(bench, _cfg(), client=client)
        assert rep.pushed == 1 and rep.refused == 0
        bench.close()
