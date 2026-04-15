"""Tests for the intake module (dynamic clarifying-question step)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest

from kaos.intake import (
    Question,
    _extract_json_array,
    _strip_code_fences,
    analyze,
    ask_interactively,
    enrich_task,
)


# ── Fake router that returns a pre-canned response ─────────────────


@dataclass
class _FakeResponse:
    content: str


class _FakeRouter:
    """Mimics the parts of GEPARouter that intake.analyze() uses."""

    def __init__(self, response_text: str):
        self.response_text = response_text
        self.last_messages: list[dict] | None = None
        self.last_config: dict | None = None

    async def route(self, agent_id, messages, tools, config):
        self.last_messages = messages
        self.last_config = config
        return _FakeResponse(content=self.response_text)


def _run(coro):
    return asyncio.run(coro)


# ── _strip_code_fences ──────────────────────────────────────────────


class TestStripCodeFences:
    def test_no_fence_passthrough(self):
        assert _strip_code_fences("[]") == "[]"

    def test_generic_fence(self):
        assert _strip_code_fences("```\n[]\n```") == "[]"

    def test_json_fence(self):
        assert _strip_code_fences("```json\n[{\"question\":\"x\"}]\n```") == '[{"question":"x"}]'

    def test_fence_with_trailing_whitespace(self):
        assert _strip_code_fences("```json\n[]\n```   ") == "[]"


# ── _extract_json_array ─────────────────────────────────────────────


class TestExtractJsonArray:
    def test_plain_array(self):
        assert _extract_json_array("[1,2,3]") == "[1,2,3]"

    def test_array_with_prefix(self):
        assert _extract_json_array("Here you go: [1,2,3]") == "[1,2,3]"

    def test_array_with_suffix(self):
        assert _extract_json_array("[1,2,3] — done") == "[1,2,3]"

    def test_no_array_returns_original(self):
        assert _extract_json_array("hello") == "hello"


# ── analyze ─────────────────────────────────────────────────────────


class TestAnalyze:
    def test_empty_array_means_zero_questions(self):
        router = _FakeRouter("[]")
        questions = _run(analyze("Build a hello-world in Python", router))
        assert questions == []

    def test_single_question(self):
        router = _FakeRouter('[{"question":"Which DB?","why":"schema matters"}]')
        questions = _run(analyze("Build a thing", router))
        assert len(questions) == 1
        assert questions[0].question == "Which DB?"
        assert questions[0].why == "schema matters"

    def test_multiple_questions_dynamic_count(self):
        """Dynamic count — the module must not impose any cap on the number."""
        n = 7
        payload = "[" + ",".join(
            f'{{"question":"Q{i}","why":"W{i}"}}' for i in range(n)
        ) + "]"
        router = _FakeRouter(payload)
        questions = _run(analyze("Build a complex thing", router))
        assert len(questions) == n
        assert all(q.question.startswith("Q") for q in questions)

    def test_three_questions_is_not_special(self):
        """Counter-example to the old hardcoded-3 assumption."""
        payload = (
            '[{"question":"A","why":""},'
            '{"question":"B","why":""},'
            '{"question":"C","why":""}]'
        )
        router = _FakeRouter(payload)
        questions = _run(analyze("Build a thing", router))
        assert len(questions) == 3

    def test_code_fence_wrapped_response(self):
        router = _FakeRouter('```json\n[{"question":"x","why":"y"}]\n```')
        questions = _run(analyze("Build a thing", router))
        assert len(questions) == 1
        assert questions[0].question == "x"

    def test_response_with_prose_prefix(self):
        router = _FakeRouter(
            'Sure, here are the ambiguities I found:\n[{"question":"x","why":"y"}]'
        )
        questions = _run(analyze("Build a thing", router))
        assert len(questions) == 1

    def test_malformed_json_returns_empty(self):
        router = _FakeRouter("not valid json at all")
        questions = _run(analyze("Build a thing", router))
        assert questions == []

    def test_non_list_returns_empty(self):
        router = _FakeRouter('{"question": "this should be in an array"}')
        questions = _run(analyze("Build a thing", router))
        assert questions == []

    def test_empty_content_returns_empty(self):
        router = _FakeRouter("")
        questions = _run(analyze("Build a thing", router))
        assert questions == []

    def test_item_without_question_key_skipped(self):
        router = _FakeRouter('[{"why":"no question key"},{"question":"real one"}]')
        questions = _run(analyze("Build a thing", router))
        assert len(questions) == 1
        assert questions[0].question == "real one"

    def test_string_items_accepted(self):
        router = _FakeRouter('["just a string question"]')
        questions = _run(analyze("Build a thing", router))
        assert len(questions) == 1
        assert questions[0].question == "just a string question"
        assert questions[0].why == ""

    def test_task_is_passed_through_to_router(self):
        router = _FakeRouter("[]")
        _run(analyze("my special task text", router))
        assert router.last_messages is not None
        user_msg = next(m for m in router.last_messages if m["role"] == "user")
        assert "my special task text" in user_msg["content"]

    def test_force_model_passed_to_router(self):
        router = _FakeRouter("[]")
        _run(analyze("task", router, force_model="fast-model"))
        assert router.last_config is not None
        assert router.last_config.get("force_model") == "fast-model"

    def test_deterministic_temperature(self):
        router = _FakeRouter("[]")
        _run(analyze("task", router))
        assert router.last_config is not None
        assert router.last_config["temperature"] == 0.0


# ── enrich_task ─────────────────────────────────────────────────────


class TestEnrichTask:
    def test_empty_answers_passthrough(self):
        original = "build a thing"
        assert enrich_task(original, {}) == original

    def test_single_answer_appended(self):
        enriched = enrich_task("build a thing", {"Which DB?": "Postgres"})
        assert "build a thing" in enriched
        assert "Clarifications from user:" in enriched
        assert "Q: Which DB?" in enriched
        assert "A: Postgres" in enriched

    def test_multiple_answers_all_present(self):
        answers = {"Q1?": "A1", "Q2?": "A2", "Q3?": "A3"}
        enriched = enrich_task("task", answers)
        for q, a in answers.items():
            assert f"Q: {q}" in enriched
            assert f"A: {a}" in enriched


# ── ask_interactively ───────────────────────────────────────────────


class TestAskInteractively:
    def test_empty_questions_returns_empty_dict(self, capsys):
        result = ask_interactively([])
        assert result == {}
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_collects_answers_from_stdin(self, monkeypatch, capsys):
        inputs = iter(["yes I have labels", "Okta SSO", ""])
        monkeypatch.setattr("builtins.input", lambda _: next(inputs))

        questions = [
            Question(question="Do you have labels?", why="model needs them"),
            Question(question="Which auth?", why="SSO vs standalone"),
            Question(question="Skippable question?", why="optional"),
        ]
        result = ask_interactively(questions)

        assert result == {
            "Do you have labels?": "yes I have labels",
            "Which auth?": "Okta SSO",
        }
        out = capsys.readouterr().out
        assert "flagged 3 ambiguities" in out
        assert "Do you have labels?" in out

    def test_singular_ambiguity_label(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda _: "answer")
        ask_interactively([Question(question="only one?")])
        out = capsys.readouterr().out
        assert "flagged 1 ambiguity " in out
        assert "ambiguities" not in out
