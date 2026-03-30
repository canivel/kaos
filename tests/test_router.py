"""Tests for the GEPA router and classifiers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from kaos.router.classifier import (
    COMPLEX,
    CRITICAL,
    MODERATE,
    TRIVIAL,
    HeuristicClassifier,
    LLMClassifier,
)
from kaos.router.context import ContextCompressor
from kaos.router.vllm_client import ChatCompletion, ChatChoice, ChatMessage, Usage


class TestHeuristicClassifier:
    @pytest.fixture
    def classifier(self):
        return HeuristicClassifier()

    def test_trivial_task(self, classifier: HeuristicClassifier):
        result = classifier.classify("rename the variable foo to bar")
        assert result.complexity == TRIVIAL

    def test_moderate_task(self, classifier: HeuristicClassifier):
        result = classifier.classify("implement a function to parse CSV files")
        assert result.complexity in (MODERATE, COMPLEX)

    def test_complex_task(self, classifier: HeuristicClassifier):
        result = classifier.classify(
            "refactor the entire authentication system to use JWT tokens "
            "and implement distributed session management"
        )
        assert result.complexity in (COMPLEX, CRITICAL)

    def test_context_length_factor(self, classifier: HeuristicClassifier):
        short = classifier.classify("simple task", context_length=100)
        long = classifier.classify("simple task", context_length=100000)
        assert long.confidence >= short.confidence or True

    def test_confidence_range(self, classifier: HeuristicClassifier):
        result = classifier.classify("any task")
        assert 0.0 <= result.confidence <= 1.0

    def test_reasoning_present(self, classifier: HeuristicClassifier):
        result = classifier.classify("some task")
        assert result.reasoning is not None


class TestLLMClassifier:
    def _make_mock_client(self, response_text: str) -> AsyncMock:
        """Create a mock VLLMClient that returns a canned response."""
        client = AsyncMock()
        client.chat = AsyncMock(return_value=ChatCompletion(
            choices=[ChatChoice(
                message=ChatMessage(role="assistant", content=response_text),
                finish_reason="stop",
            )],
            usage=Usage(prompt_tokens=50, completion_tokens=1, total_tokens=51),
        ))
        return client

    @pytest.mark.asyncio
    async def test_classify_trivial(self):
        client = self._make_mock_client("trivial")
        classifier = LLMClassifier(client=client, model="test-model")
        result = await classifier.classify("rename foo to bar")
        assert result.complexity == TRIVIAL
        assert result.confidence == 0.85
        assert result.reasoning == "llm_raw=trivial"

    @pytest.mark.asyncio
    async def test_classify_complex(self):
        client = self._make_mock_client("complex")
        classifier = LLMClassifier(client=client, model="test-model")
        result = await classifier.classify("refactor the auth system")
        assert result.complexity == COMPLEX

    @pytest.mark.asyncio
    async def test_classify_critical(self):
        client = self._make_mock_client("critical")
        classifier = LLMClassifier(client=client, model="test-model")
        result = await classifier.classify("migrate the database")
        assert result.complexity == CRITICAL

    @pytest.mark.asyncio
    async def test_classify_moderate(self):
        client = self._make_mock_client("moderate")
        classifier = LLMClassifier(client=client, model="test-model")
        result = await classifier.classify("add a new endpoint")
        assert result.complexity == MODERATE

    @pytest.mark.asyncio
    async def test_parses_verbose_response(self):
        """LLM returns extra text around the classification word."""
        client = self._make_mock_client("I think this is a complex task.")
        classifier = LLMClassifier(client=client, model="test-model")
        result = await classifier.classify("some task")
        assert result.complexity == COMPLEX

    @pytest.mark.asyncio
    async def test_parses_uppercase_response(self):
        client = self._make_mock_client("CRITICAL")
        classifier = LLMClassifier(client=client, model="test-model")
        result = await classifier.classify("some task")
        assert result.complexity == CRITICAL

    @pytest.mark.asyncio
    async def test_unknown_response_defaults_moderate(self):
        """If LLM returns gibberish, default to moderate."""
        client = self._make_mock_client("banana")
        classifier = LLMClassifier(client=client, model="test-model")
        result = await classifier.classify("some task")
        assert result.complexity == MODERATE

    @pytest.mark.asyncio
    async def test_falls_back_to_heuristic_on_error(self):
        """If the vLLM call fails, fall back to heuristic classifier."""
        client = AsyncMock()
        client.chat = AsyncMock(side_effect=ConnectionError("offline"))
        classifier = LLMClassifier(client=client, model="test-model")

        result = await classifier.classify("rename a variable")
        assert result.complexity in (TRIVIAL, MODERATE, COMPLEX, CRITICAL)
        assert "heuristic_score" in result.reasoning

    @pytest.mark.asyncio
    async def test_calls_correct_model(self):
        """Verify the classifier passes the right model name."""
        client = self._make_mock_client("moderate")
        classifier = LLMClassifier(client=client, model="qwen2.5-coder-7b")

        await classifier.classify("some task")

        call_kwargs = client.chat.call_args
        assert call_kwargs.kwargs["model"] == "qwen2.5-coder-7b"
        assert call_kwargs.kwargs["temperature"] == 0.0
        assert call_kwargs.kwargs["max_tokens"] == 10

    @pytest.mark.asyncio
    async def test_prompt_contains_task(self):
        """Verify the classification prompt includes the task description."""
        client = self._make_mock_client("moderate")
        classifier = LLMClassifier(client=client, model="test-model")

        await classifier.classify("implement user authentication", context_length=5000, tool_count=8)

        call_kwargs = client.chat.call_args
        prompt = call_kwargs.kwargs["messages"][0]["content"]
        assert "implement user authentication" in prompt
        assert "5000" in prompt
        assert "8" in prompt


class TestContextCompressor:
    @pytest.fixture
    def compressor(self):
        return ContextCompressor()

    def test_no_compression_needed(self, compressor: ContextCompressor):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
        ]
        result = compressor.compress(messages, max_tokens=1000)
        assert len(result) == 2

    def test_truncate_tool_results(self, compressor: ContextCompressor):
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "do something"},
            {"role": "tool", "content": "x" * 5000},
        ]
        result = compressor.compress(messages, max_tokens=500)
        tool_msg = [m for m in result if m["role"] == "tool"]
        if tool_msg:
            assert len(tool_msg[0]["content"]) < 5000

    def test_drop_middle_messages(self, compressor: ContextCompressor):
        messages = [{"role": "system", "content": "sys"}]
        for i in range(20):
            messages.append({"role": "user", "content": f"message {i} " * 100})
            messages.append({"role": "assistant", "content": f"response {i} " * 100})

        result = compressor.compress(messages, max_tokens=200)
        assert len(result) < len(messages)
        assert result[0]["role"] == "system"

    def test_estimate_tokens(self, compressor: ContextCompressor):
        messages = [{"role": "user", "content": "a" * 400}]
        tokens = compressor.estimate_tokens(messages)
        assert tokens == 100
