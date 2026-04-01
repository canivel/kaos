"""Provider-agnostic LLM clients.

Supports three provider types — all using raw httpx (no SDK dependencies):
  - openai:    OpenAI API, Azure OpenAI, or any OpenAI-compatible endpoint
  - anthropic: Anthropic Claude API (/v1/messages format)
  - local:     vLLM, ollama, llama.cpp, or any local /v1/chat/completions server

API keys are read from environment variables — never stored in config files.

Usage in kaos.yaml:
    models:
      claude-sonnet:
        provider: anthropic
        api_key_env: ANTHROPIC_API_KEY
        model_id: claude-sonnet-4-20250514
        max_context: 200000
        use_for: [complex, critical]

      gpt-4o:
        provider: openai
        api_key_env: OPENAI_API_KEY
        model_id: gpt-4o
        max_context: 128000
        use_for: [moderate]

      local-qwen:
        provider: local
        endpoint: http://localhost:8000/v1
        max_context: 32768
        use_for: [trivial]
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)


# ── Response types (shared across providers) ─────────────────────

@dataclass
class LLMMessage:
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None

@dataclass
class LLMChoice:
    message: LLMMessage
    finish_reason: str | None = None

@dataclass
class LLMUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

@dataclass
class LLMResponse:
    choices: list[LLMChoice]
    usage: LLMUsage | None = None


# ── Abstract provider ────────────────────────────────────────────

class LLMProvider(ABC):
    """Base class for LLM providers."""

    @abstractmethod
    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        """Send a chat completion request."""

    @abstractmethod
    async def close(self) -> None:
        """Close the HTTP client."""


# ── OpenAI-compatible provider ───────────────────────────────────

class OpenAIProvider(LLMProvider):
    """OpenAI API, Azure OpenAI, or any OpenAI-compatible endpoint.

    Raw httpx — no openai SDK.
    """

    def __init__(self, base_url: str = "https://api.openai.com/v1", api_key: str = "", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(timeout=self.timeout, headers=headers)
        return self._client

    async def chat(self, model, messages, temperature=0.1, max_tokens=4096, tools=None, tool_choice=None) -> LLMResponse:
        client = await self._get_client()
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        response = await client.post(f"{self.base_url}/chat/completions", json=payload)
        response.raise_for_status()
        return self._parse(response.json())

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        choices = []
        for c in data.get("choices", []):
            msg = c.get("message", {})
            tool_calls = None
            if msg.get("tool_calls"):
                tool_calls = [
                    {
                        "id": tc.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", "{}"),
                        },
                    }
                    for tc in msg["tool_calls"]
                ]
            choices.append(LLMChoice(
                message=LLMMessage(
                    role=msg.get("role", "assistant"),
                    content=msg.get("content"),
                    tool_calls=tool_calls,
                ),
                finish_reason=c.get("finish_reason"),
            ))

        usage = None
        if data.get("usage"):
            u = data["usage"]
            usage = LLMUsage(
                input_tokens=u.get("prompt_tokens", 0),
                output_tokens=u.get("completion_tokens", 0),
                total_tokens=u.get("total_tokens", 0),
            )
        return LLMResponse(choices=choices, usage=usage)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── Anthropic provider ───────────────────────────────────────────

class AnthropicProvider(LLMProvider):
    """Anthropic Claude API (/v1/messages format).

    Raw httpx — no anthropic SDK.
    """

    def __init__(self, api_key: str = "", timeout: float = 120.0):
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
            )
        return self._client

    async def chat(self, model, messages, temperature=0.1, max_tokens=4096, tools=None, tool_choice=None) -> LLMResponse:
        client = await self._get_client()

        # Convert OpenAI-format messages to Anthropic format
        system_prompt = ""
        anthropic_messages = []
        for msg in messages:
            if msg.get("role") == "system":
                system_prompt += msg.get("content", "") + "\n"
            elif msg.get("role") == "tool":
                # Anthropic uses tool_result content blocks
                anthropic_messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": msg.get("tool_call_id", ""),
                        "content": msg.get("content", ""),
                    }],
                })
            elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                # Convert tool calls to Anthropic content blocks
                content = []
                if msg.get("content"):
                    content.append({"type": "text", "text": msg["content"]})
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    try:
                        input_data = json.loads(fn.get("arguments", "{}"))
                    except json.JSONDecodeError:
                        input_data = {}
                    content.append({
                        "type": "tool_use",
                        "id": tc.get("id", ""),
                        "name": fn.get("name", ""),
                        "input": input_data,
                    })
                anthropic_messages.append({"role": "assistant", "content": content})
            else:
                anthropic_messages.append({
                    "role": msg.get("role", "user"),
                    "content": msg.get("content", ""),
                })

        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "messages": anthropic_messages,
        }
        if system_prompt.strip():
            payload["system"] = system_prompt.strip()
        if temperature != 0.1:
            payload["temperature"] = temperature
        if tools:
            # Convert OpenAI tool format to Anthropic
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools
            ]

        response = await client.post("https://api.anthropic.com/v1/messages", json=payload)
        response.raise_for_status()
        return self._parse(response.json())

    @staticmethod
    def _parse(data: dict) -> LLMResponse:
        content_text = ""
        tool_calls = []

        for block in data.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        finish_reason = data.get("stop_reason", "end_turn")
        if finish_reason == "tool_use":
            finish_reason = "tool_calls"

        choices = [LLMChoice(
            message=LLMMessage(
                role="assistant",
                content=content_text or None,
                tool_calls=tool_calls or None,
            ),
            finish_reason=finish_reason,
        )]

        usage = None
        if data.get("usage"):
            u = data["usage"]
            inp = u.get("input_tokens", 0)
            out = u.get("output_tokens", 0)
            usage = LLMUsage(input_tokens=inp, output_tokens=out, total_tokens=inp + out)

        return LLMResponse(choices=choices, usage=usage)

    async def close(self):
        if self._client and not self._client.is_closed:
            await self._client.aclose()


# ── Local provider (vLLM, ollama, llama.cpp) ─────────────────────

class LocalProvider(OpenAIProvider):
    """Local vLLM/ollama/llama.cpp — same as OpenAI format, no API key."""

    def __init__(self, endpoint: str = "http://localhost:8000/v1", timeout: float = 120.0):
        super().__init__(base_url=endpoint, api_key="", timeout=timeout)


# ── Factory ──────────────────────────────────────────────────────

def create_provider(provider_type: str, **kwargs) -> LLMProvider:
    """Create an LLM provider from config.

    Args:
        provider_type: "openai", "anthropic", or "local"
        **kwargs: Provider-specific config (api_key, endpoint, etc.)
    """
    if provider_type == "anthropic":
        api_key = kwargs.get("api_key") or os.environ.get(kwargs.get("api_key_env", "ANTHROPIC_API_KEY"), "")
        if not api_key:
            raise ValueError(
                "Anthropic API key required. Set ANTHROPIC_API_KEY environment variable "
                "or add api_key_env to your model config."
            )
        return AnthropicProvider(api_key=api_key, timeout=kwargs.get("timeout", 120.0))

    elif provider_type == "openai":
        api_key = kwargs.get("api_key") or os.environ.get(kwargs.get("api_key_env", "OPENAI_API_KEY"), "")
        if not api_key:
            raise ValueError(
                "OpenAI API key required. Set OPENAI_API_KEY environment variable "
                "or add api_key_env to your model config."
            )
        base_url = kwargs.get("endpoint", "https://api.openai.com/v1")
        return OpenAIProvider(base_url=base_url, api_key=api_key, timeout=kwargs.get("timeout", 120.0))

    elif provider_type == "local":
        endpoint = kwargs.get("endpoint", "http://localhost:8000/v1")
        return LocalProvider(endpoint=endpoint, timeout=kwargs.get("timeout", 120.0))

    else:
        raise ValueError(f"Unknown provider: {provider_type}. Use 'openai', 'anthropic', or 'local'.")
