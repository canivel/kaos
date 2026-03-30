"""Context compression for managing long conversations within model context windows."""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextCompressor:
    """
    Compresses conversation history to fit within model context windows.

    Strategies:
    1. Truncate early messages (keep system + recent)
    2. Summarize tool call results
    3. Compress repeated patterns
    """

    def __init__(self, max_context_chars: int = 100000):
        self.max_context_chars = max_context_chars

    def estimate_tokens(self, messages: list[dict]) -> int:
        """Rough token estimate: ~4 chars per token."""
        total_chars = sum(len(self._msg_content(m)) for m in messages)
        return total_chars // 4

    def compress(
        self, messages: list[dict], max_tokens: int
    ) -> list[dict]:
        """
        Compress messages to fit within max_tokens.

        Strategy:
        1. Always keep the system message and last N user/assistant turns
        2. Summarize older tool results
        3. Drop middle messages if still over limit
        """
        max_chars = max_tokens * 4
        current_size = sum(len(self._msg_content(m)) for m in messages)

        if current_size <= max_chars:
            return messages

        logger.info(
            "Compressing context: %d chars -> target %d chars",
            current_size, max_chars,
        )

        compressed = list(messages)

        # Step 1: Truncate long tool results
        compressed = self._truncate_tool_results(compressed, max_chars)
        if self._total_size(compressed) <= max_chars:
            return compressed

        # Step 2: Summarize old messages (keep system + last 10 turns)
        compressed = self._drop_middle(compressed, max_chars)

        return compressed

    def _truncate_tool_results(
        self, messages: list[dict], max_chars: int
    ) -> list[dict]:
        """Truncate long tool call results to a summary."""
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                content = self._msg_content(msg)
                if len(content) > 2000:
                    truncated = content[:1000] + "\n...[truncated]...\n" + content[-500:]
                    msg = {**msg, "content": truncated}
            result.append(msg)
        return result

    def _drop_middle(self, messages: list[dict], max_chars: int) -> list[dict]:
        """Keep system message, first user message, and last N messages."""
        if len(messages) <= 6:
            return messages

        # Always keep: system (index 0), first user (index 1), last 8 messages
        keep_start = messages[:2]
        keep_end = messages[-8:]

        dropped_count = len(messages) - len(keep_start) - len(keep_end)

        summary_msg = {
            "role": "system",
            "content": f"[{dropped_count} earlier messages omitted for context management]",
        }

        result = keep_start + [summary_msg] + keep_end

        # If still too large, be more aggressive
        while self._total_size(result) > max_chars and len(result) > 4:
            # Remove the message after the summary
            if len(result) > 3:
                result.pop(3)

        return result

    @staticmethod
    def _msg_content(msg: dict) -> str:
        """Extract text content from a message."""
        content = msg.get("content", "")
        if isinstance(content, list):
            return " ".join(
                c.get("text", "") for c in content if isinstance(c, dict)
            )
        return str(content)

    def _total_size(self, messages: list[dict]) -> int:
        return sum(len(self._msg_content(m)) for m in messages)
