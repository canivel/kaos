"""Tests for LLMDiagnoser + fingerprint cache.

Whitepaper §6.4: heuristic diagnoser coverage stops at known error patterns.
This module exercises the opt-in LLM fallback and its cache layer.
"""

from __future__ import annotations

import pytest

from kaos.core import Kaos
from kaos.dream.auto import fingerprint_of
from kaos.dream.diagnosis import (
    Diagnosis,
    LLMDiagnoser,
    _safe_parse_llm_json,
    diagnose,
)


@pytest.fixture
def afs(tmp_path, monkeypatch):
    monkeypatch.setenv("KAOS_DREAM_AUTO", "0")
    fs = Kaos(db_path=str(tmp_path / "d.db"))
    yield fs
    fs.close()


class TestJSONParsing:
    def test_plain_json(self):
        out = _safe_parse_llm_json('{"category":"code","root_cause":"bug"}')
        assert out == {"category": "code", "root_cause": "bug"}

    def test_json_with_prose(self):
        raw = 'Sure! Here is the answer:\n{"category":"code","root_cause":"bug"}\nThanks.'
        assert _safe_parse_llm_json(raw)["category"] == "code"

    def test_json_in_markdown_fence(self):
        raw = '```json\n{"category":"infra","root_cause":"x","suggested_action":"y"}\n```'
        assert _safe_parse_llm_json(raw)["category"] == "infra"

    def test_empty_string_returns_none(self):
        assert _safe_parse_llm_json("") is None

    def test_no_json_returns_none(self):
        assert _safe_parse_llm_json("The error is a bug.") is None

    def test_malformed_json_returns_none(self):
        assert _safe_parse_llm_json("{not valid json}") is None

    def test_non_dict_returns_none(self):
        assert _safe_parse_llm_json("[1, 2, 3]") is None


class TestLLMDiagnoserBasic:
    def test_calls_llm_on_cache_miss(self, afs):
        calls = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return ('{"category":"code","root_cause":"bad import",'
                    '"suggested_action":"add to requirements","confidence":0.8}')

        d = LLMDiagnoser(call_fn=fake_llm, conn=afs.conn)
        result = d.try_diagnose("bash", "ModuleNotFoundError: No module named 'x'", {})
        assert result is not None
        assert result.category == "code"
        assert result.method == "llm"
        assert result.confidence == 0.8
        assert len(calls) == 1

    def test_cache_hit_skips_llm(self, afs):
        calls = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return '{"category":"infra","root_cause":"r","suggested_action":"s","confidence":0.9}'

        d = LLMDiagnoser(call_fn=fake_llm, conn=afs.conn)
        tool, err = "http", "something weird happened"
        # First call: LLM hit
        first = d.try_diagnose(tool, err, {})
        assert first.method == "llm"
        # Second call: cache hit, no new LLM call
        second = d.try_diagnose(tool, err, {})
        assert second is not None
        assert second.method == "llm-cached"
        assert len(calls) == 1

    def test_no_call_fn_serves_cache_only(self, afs):
        # Pre-seed cache
        fp = fingerprint_of("bash", "weird failure")
        afs.conn.execute(
            "INSERT INTO llm_diagnosis_cache (fingerprint, category, root_cause, "
            "suggested_action, confidence, model) "
            "VALUES (?, 'code', 'r', 's', 0.7, 'test')",
            (fp,),
        )
        afs.conn.commit()

        d = LLMDiagnoser(call_fn=None, conn=afs.conn)
        result = d.try_diagnose("bash", "weird failure", {})
        assert result is not None
        assert result.method == "llm-cached"

        # Not in cache → returns None
        miss = d.try_diagnose("bash", "totally different error", {})
        assert miss is None

    def test_llm_returning_garbage_returns_none(self, afs):
        d = LLMDiagnoser(call_fn=lambda p: "this is not json", conn=afs.conn)
        assert d.try_diagnose("bash", "novel failure", {}) is None

    def test_llm_raising_is_swallowed(self, afs):
        def boom(prompt: str) -> str:
            raise RuntimeError("network down")
        d = LLMDiagnoser(call_fn=boom, conn=afs.conn)
        assert d.try_diagnose("bash", "novel failure", {}) is None

    def test_invalid_category_normalised_to_unknown(self, afs):
        def fake_llm(prompt: str) -> str:
            return '{"category":"banana","root_cause":"r","confidence":0.5}'
        d = LLMDiagnoser(call_fn=fake_llm, conn=afs.conn)
        result = d.try_diagnose("bash", "new failure", {})
        assert result.category == "unknown"


class TestDiagnoseIntegration:
    def test_heuristic_short_circuits_llm(self, afs):
        calls = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return '{"category":"code","root_cause":"r","confidence":1.0}'

        d = LLMDiagnoser(call_fn=fake_llm, conn=afs.conn)
        # Connection refused is a known heuristic — LLM must not be consulted.
        result = diagnose("http", "Connection refused on localhost:8000",
                          llm_fallback=d)
        assert result.category == "infra"
        assert result.method == "heuristic"
        assert calls == []

    def test_llm_consulted_when_heuristics_fail(self, afs):
        calls = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return ('{"category":"code","root_cause":"obscure bug",'
                    '"suggested_action":"inspect","confidence":0.65}')

        d = LLMDiagnoser(call_fn=fake_llm, conn=afs.conn)
        result = diagnose("custom-tool",
                          "Strange non-matching failure xyz-quux",
                          llm_fallback=d)
        assert result.category == "code"
        assert result.method == "llm"
        assert len(calls) == 1

    def test_no_llm_falls_through_to_unknown(self):
        result = diagnose("custom-tool",
                          "Strange non-matching failure xyz-quux")
        assert result.category == "unknown"
        assert result.method == "heuristic"

    def test_cache_hit_avoids_llm_even_when_heuristics_miss(self, afs):
        calls = []

        def fake_llm(prompt: str) -> str:
            calls.append(prompt)
            return ('{"category":"config","root_cause":"missing env",'
                    '"suggested_action":"set X","confidence":0.7}')

        d = LLMDiagnoser(call_fn=fake_llm, conn=afs.conn)
        err = "weird failure xyz-quux"
        diagnose("custom-tool", err, llm_fallback=d)
        result = diagnose("custom-tool", err, llm_fallback=d)
        assert result.method == "llm-cached"
        assert len(calls) == 1
