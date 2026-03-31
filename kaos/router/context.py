"""Context compression for managing long conversations within model context windows.

Compaction strategy learned from Claude Code's internals (via claw-code analysis):
- Summarize old messages into a system-role continuation block
- Instruct the model to resume without acknowledging the summary
- Preserve recent messages verbatim
- Estimate tokens at len/4 + 1 per block (cheap heuristic, not tokenizer)
- Truncate long tool results before attempting message-level compaction
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Number of recent messages to always preserve verbatim
PRESERVE_RECENT = 8

# Max chars for a tool result before truncation
TOOL_RESULT_MAX = 2000

# Continuation prompt injected when old messages are compacted
CONTINUATION_TEMPLATE = """\
This conversation is being continued from a previous context that was compacted.
The summary below covers the earlier portion of the conversation.

Summary:
{summary}

Recent messages are preserved verbatim below.
Continue from where the conversation left off. Do not acknowledge this summary,
do not recap what was discussed, and do not preface with continuation text.
Resume directly."""


class ContextCompressor:
    """Compresses conversation history to fit within model context windows.

    Three-stage strategy:
    1. Truncate long tool results (>2000 chars)
    2. Compact old messages into a summary continuation block
    3. Aggressive trimming if still over limit
    """

    def __init__(self, max_context_chars: int = 100000):
        self.max_context_chars = max_context_chars

    def estimate_tokens(self, messages: list[dict]) -> int:
        """Estimate token count: len/4 + 1 per content block."""
        total = 0
        for msg in messages:
            content = self._msg_content(msg)
            total += len(content) // 4 + 1
            # Tool calls add extra tokens
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                total += (len(fn.get("name", "")) + len(fn.get("arguments", ""))) // 4 + 1
        return total

    def compress(self, messages: list[dict], max_tokens: int) -> list[dict]:
        """Compress messages to fit within max_tokens."""
        max_chars = max_tokens * 4

        if self._total_size(messages) <= max_chars:
            return messages

        logger.info(
            "Compressing context: %d estimated tokens -> target %d tokens",
            self.estimate_tokens(messages), max_tokens,
        )

        compressed = list(messages)

        # Stage 1: Truncate long tool results
        compressed = self._truncate_tool_results(compressed)
        if self._total_size(compressed) <= max_chars:
            return compressed

        # Stage 2: Compact old messages into a summary continuation block
        compressed = self._compact_with_summary(compressed, max_chars)
        if self._total_size(compressed) <= max_chars:
            return compressed

        # Stage 3: Aggressive trimming — remove messages after summary
        while self._total_size(compressed) > max_chars and len(compressed) > 4:
            # Remove the oldest message after the system/continuation block
            if len(compressed) > 3:
                compressed.pop(2)

        return compressed

    def _truncate_tool_results(self, messages: list[dict]) -> list[dict]:
        """Truncate long tool call results."""
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                content = self._msg_content(msg)
                if len(content) > TOOL_RESULT_MAX:
                    truncated = (
                        content[:1000]
                        + "\n...[truncated "
                        + str(len(content) - 1500)
                        + " chars]...\n"
                        + content[-500:]
                    )
                    msg = {**msg, "content": truncated}
            result.append(msg)
        return result

    def _compact_with_summary(
        self, messages: list[dict], max_chars: int
    ) -> list[dict]:
        """Compact old messages into a summary continuation block.

        Keeps system message (index 0) and last PRESERVE_RECENT messages.
        Everything in between is summarized into a continuation message.
        """
        if len(messages) <= PRESERVE_RECENT + 2:
            return messages

        # Split: system + old messages + recent messages
        system_msg = messages[0] if messages[0].get("role") == "system" else None
        start_idx = 1 if system_msg else 0
        split_idx = len(messages) - PRESERVE_RECENT

        if split_idx <= start_idx:
            return messages

        old_messages = messages[start_idx:split_idx]
        recent_messages = messages[split_idx:]

        # Summarize old messages — one line per message, content truncated
        summary_lines = []
        for msg in old_messages:
            role = msg.get("role", "unknown")
            content = self._msg_content(msg)
            # Strip analysis/thinking tags
            content = re.sub(r"<analysis>.*?</analysis>", "", content, flags=re.DOTALL)
            content = re.sub(r"<summary>.*?</summary>", "", content, flags=re.DOTALL)
            # Truncate each line to 160 chars
            content = content.strip()
            if len(content) > 160:
                content = content[:157] + "..."
            if content:
                summary_lines.append(f"- {role}: {content}")

        summary_text = "\n".join(summary_lines)
        continuation = CONTINUATION_TEMPLATE.format(summary=summary_text)

        # Build compacted message list
        result = []
        if system_msg:
            result.append(system_msg)
        result.append({"role": "system", "content": continuation})
        result.extend(recent_messages)

        removed = len(old_messages)
        logger.info(
            "Compacted %d old messages into summary (%d chars), preserving %d recent",
            removed, len(continuation), len(recent_messages),
        )

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
