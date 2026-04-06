"""Claude Agent SDK provider — uses the Agent SDK for LLM calls.

Runs within a Claude Code session context. No subprocess spawning,
no conversation replay, no rate limit competition with active sessions.

Usage in kaos.yaml:
    models:
      claude-sonnet:
        provider: agent_sdk
        model_id: claude-sonnet-4-6
        timeout: 120
        use_for: [trivial, moderate, complex, critical]

Requires: uv pip install claude-agent-sdk
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
    this uses the SDK directly:
    - No subprocess spawning or conversation replay
    - No rate limit competition with active Claude Code sessions
    - Native async streaming
    - System prompt support via SDK parameter
    """

    def __init__(self, model_id: str = "claude-sonnet-4-6", timeout: float = 120.0):
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

        # Extract system prompt and build user prompt
        system_prompt, user_prompt = self._split_messages(messages)
        effective_model = model or self.model_id

        result_text = ""
        content_parts: list[str] = []

        max_retries = 2
        last_error = None
        for attempt in range(max_retries):
            result_text = ""
            content_parts.clear()
            try:
                async def _run():
                    nonlocal result_text
                    async for message in query(
                        prompt=user_prompt,
                        options=ClaudeAgentOptions(
                            model=effective_model,
                            system_prompt=system_prompt or None,
                            max_turns=1,
                            tools=[],
                            permission_mode="bypassPermissions",
                        ),
                    ):
                        if isinstance(message, ResultMessage):
                            result_text = message.result or ""
                        elif hasattr(message, "message") and hasattr(message.message, "content"):
                            for block in (message.message.content or []):
                                if hasattr(block, "text") and block.text:
                                    content_parts.append(block.text)

                await asyncio.wait_for(_run(), timeout=self.timeout)
                break  # success

            except asyncio.TimeoutError:
                raise TimeoutError(f"Agent SDK call timed out after {self.timeout}s")
            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    logger.warning(
                        "Agent SDK attempt %d/%d failed: %s. Retrying in 3s...",
                        attempt + 1, max_retries, e,
                    )
                    await asyncio.sleep(3)
                else:
                    raise RuntimeError(f"Agent SDK error after {max_retries} attempts: {e}")

        # Use result_text if available, otherwise join content parts
        final_text = result_text or "\n".join(content_parts)

        if not final_text.strip():
            raise RuntimeError(
                "Agent SDK returned empty response. "
                "Check that ANTHROPIC_API_KEY is set or Claude Code is authenticated."
            )

        return LLMResponse(
            choices=[LLMChoice(
                message=LLMMessage(role="assistant", content=final_text),
                finish_reason="end_turn",
            )],
        )

    @staticmethod
    def _split_messages(messages: list[dict]) -> tuple[str, str]:
        """Split messages into system prompt and user prompt."""
        system_parts = []
        user_parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content") or ""
            if role == "system":
                system_parts.append(content)
            elif role == "user":
                user_parts.append(content)
            elif role == "assistant" and content:
                user_parts.append(f"[Prior assistant response]\n{content}")
            elif role == "tool" and content:
                user_parts.append(f"[Tool result]\n{content}")
        return "\n\n".join(system_parts), "\n\n".join(user_parts)

    async def close(self) -> None:
        pass
