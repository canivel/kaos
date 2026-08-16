"""kaos.bench.canon — content-addressing must be byte-exact and reorder-stable.

A second canonicalizer disagreeing on one byte forks record identity silently
across benches (PLAN.md v2 §3.2). These pin the JCS rules that matter for record
bodies.
"""

from __future__ import annotations

import hashlib

import pytest

from kaos.bench.canon import canonical_bytes, record_cid, verify_cid


class TestCanonicalForm:
    def test_keys_sorted(self):
        assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'

    def test_no_whitespace_nested(self):
        assert canonical_bytes({"x": [1, {"z": 3, "y": 2}]}) == b'{"x":[1,{"y":2,"z":3}]}'

    def test_reorder_is_identical(self):
        a = {"schema_id": "s", "mechanism": {"name": "pfa", "family": "audit"}}
        b = {"mechanism": {"family": "audit", "name": "pfa"}, "schema_id": "s"}
        assert canonical_bytes(a) == canonical_bytes(b)
        assert record_cid(a) == record_cid(b)

    def test_unicode_preserved_not_escaped(self):
        # ensure_ascii=False: the − (U+2212) and é survive as UTF-8, not \u escapes
        raw = canonical_bytes({"detail": "sep −0.062 café"})
        assert "−0.062".encode() in raw and "café".encode() in raw
        assert b"\\u" not in raw

    def test_string_quotes_and_backslash_escaped(self):
        assert canonical_bytes({"k": 'a"b\\c'}) == b'{"k":"a\\"b\\\\c"}'


class TestNumbers:
    @pytest.mark.parametrize("val,expected", [
        (42, b"42"),
        (0, b"0"),
        (-7, b"-7"),
        (0.7, b"0.7"),
        (-0.062, b"-0.062"),
        (1.0, b"1"),        # JCS/ES: integral float -> integer form
        (100.0, b"100"),
        (-0.0, b"0"),       # negative zero normalizes
        (0.653, b"0.653"),
    ])
    def test_number_formatting(self, val, expected):
        assert canonical_bytes(val) == expected

    def test_bool_is_not_a_number(self):
        assert canonical_bytes(True) == b"true"
        assert canonical_bytes({"a": True, "b": False}) == b'{"a":true,"b":false}'

    def test_null(self):
        assert canonical_bytes({"threshold": None}) == b'{"threshold":null}'

    def test_non_finite_rejected(self):
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValueError):
                canonical_bytes(bad)


class TestRecordCid:
    def test_prefix_and_length(self):
        cid = record_cid({"schema_id": "transferbench/eval_record/v1"})
        assert cid.startswith("tb1:")
        assert len(cid) == len("tb1:") + 64
        assert all(c in "0123456789abcdef" for c in cid[4:])

    def test_matches_manual_sha256(self):
        body = {"a": 1, "b": [True, None, "x"]}
        expected = "tb1:" + hashlib.sha256(canonical_bytes(body)).hexdigest()
        assert record_cid(body) == expected

    def test_verify_cid_roundtrip(self):
        body = {"mechanism": {"name": "gdl"}, "run": {"verdict": {"status": "REJECT"}}}
        cid = record_cid(body)
        assert verify_cid(body, cid)

    def test_tamper_detected(self):
        body = {"run": {"verdict": {"status": "REJECT"}}}
        cid = record_cid(body)
        tampered = {"run": {"verdict": {"status": "ACCEPT"}}}  # flip the verdict
        assert not verify_cid(tampered, cid)

    def test_non_serializable_rejected(self):
        with pytest.raises(TypeError):
            record_cid({"bad": {1, 2, 3}})  # a set is not JSON
