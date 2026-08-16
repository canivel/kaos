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
        payload={"family": "probe"}, retrieval_keys_text="gdl probe",
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
