"""Claude Agent SDK provider — uses the Agent SDK for LLM calls.

Runs within a Claude Code session context. Shares auth with the parent
session so there's no rate limit competition. Supports tool use
(Bash, Read, Glob, Grep) natively.

Usage in kaos.yaml:
    models:
      claude-sonnet:
        provider: agent_sdk
        model_id: sonnet        # "sonnet", "opus", "haiku"
        timeout: 120
        use_for: [trivial, moderate, complex, critical]

Requires: pip install claude-agent-sdk
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from kaos.router.providers import (
    LLMProvider, LLMResponse, LLMChoice, LLMMessage, LLMUsage,
)

logger = logging.getLogger(__name__)


class AgentSDKProvider(LLMProvider):
    """LLM provider using the Claude Agent SDK.

    Unlike ClaudeCodeProvider (which shells out to `claude --print`),
    this uses the SDK directly. Benefits:
    - No subprocess spawning
    - No conversation replay (SDK manages context)
    - Shares parent session auth (no rate limit competition)
    - Supports streaming
    """

    def __init__(self, model_id: str = "sonnet", timeout: float = 120.0):
        self.model_id = model_id
        self.timeout = timeout

    async def chat(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.1,
        max_tokens: int = 4096,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
    ) -> LLMResponse:
        try:
            from claude_agent_sdk import query, ClaudeAgentOptions, ResultMessage
        except ImportError:
            raise ImportError(
                "claude-agent-sdk not installed. Install with: uv pip install claude-agent-sdk\n"
                "Or use a different provider: claude_code, anthropic, openai, local"
            )

        # Build prompt from messages
        prompt = self._messages_to_prompt(messages)
        effective_model = model or self.model_id

        # Collect the result
        result_text = ""

        try:
            async def _run():
                nonlocal result_text
                async for message in query(
                    prompt=prompt,
                    options=ClaudeAgentOptions(
                        model=effective_model,
                        allowed_tools=[],  # no tools for simple completion
                        permission_mode="bypassPermissions",
                    ),
                ):
                    if isinstance(message, ResultMessage):
                        result_text = message.result or ""

            await asyncio.wait_for(_run(), timeout=self.timeout)

        except asyncio.TimeoutError:
            raise TimeoutError(f"Agent SDK call timed out after {self.timeout}s")
        except Exception as e:
            if "claude-agent-sdk" in str(type(e).__module__ or ""):
                raise RuntimeError(f"Agent SDK error: {e}")
            raise

        if not result_text.strip():
            raise RuntimeError(
                "Agent SDK returned empty response. Check API key and model availability."
            )

        return LLMResponse(
            choices=[LLMChoice(
                message=LLMMessage(
                    role="assistant",
                    content=result_text,
                ),
                finish_reason="end_turn",
            )],
        )

    @staticmethod
    def _messages_to_prompt(messages: list[dict]) -> str:
        """Convert message list to a single prompt string."""
        parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "system":
                parts.append(content)
            elif role == "user":
                parts.append(content)
            elif role == "assistant":
                parts.append(f"[Previous response]\n{content}")
        return "\n\n".join(parts)

    async def close(self) -> None:
        pass
