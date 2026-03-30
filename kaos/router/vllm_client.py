"""Lightweight async vLLM client using raw httpx. No openai SDK needed."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    role: str
    content: str | None = None
    tool_calls: list[dict] | None = None
    tool_call_id: str | None = None


@dataclass
class ChatChoice:
    message: ChatMessage
    finish_reason: str | None = None


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class ChatCompletion:
    choices: list[ChatChoice] = field(default_factory=list)
    usage: Usage | None = None


class VLLMClient:
    """
    Async HTTP client for vLLM's OpenAI-compatible /v1/chat/completions endpoint.

    Pure httpx — no openai SDK, no litellm, no dspy.
    """

    def __init__(self, base_url: str, timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> ChatCompletion:
        """Send a chat completion request to vLLM."""
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

        url = f"{self.base_url}/chat/completions"
        response = await client.post(url, json=payload)
        response.raise_for_status()

        data = response.json()
        return self._parse(data)

    @staticmethod
    def _parse(data: dict) -> ChatCompletion:
        """Parse raw JSON into a ChatCompletion dataclass."""
        choices = []
        for c in data.get("choices", []):
            msg_data = c.get("message", {})

            # Parse tool calls if present
            tool_calls = None
            raw_tc = msg_data.get("tool_calls")
            if raw_tc:
                tool_calls = [
                    {
                        "id": tc.get("id", ""),
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": tc.get("function", {}).get("name", ""),
                            "arguments": tc.get("function", {}).get("arguments", "{}"),
                        },
                    }
                    for tc in raw_tc
                ]

            message = ChatMessage(
                role=msg_data.get("role", "assistant"),
                content=msg_data.get("content"),
                tool_calls=tool_calls,
                tool_call_id=msg_data.get("tool_call_id"),
            )
            choices.append(ChatChoice(
                message=message,
                finish_reason=c.get("finish_reason"),
            ))

        usage = None
        usage_data = data.get("usage")
        if usage_data:
            usage = Usage(
                prompt_tokens=usage_data.get("prompt_tokens", 0),
                completion_tokens=usage_data.get("completion_tokens", 0),
                total_tokens=usage_data.get("total_tokens", 0),
            )

        return ChatCompletion(choices=choices, usage=usage)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
