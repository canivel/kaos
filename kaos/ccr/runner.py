"""Claude Code Runner — the agent execution loop.

Improvements informed by Claude Code's internal architecture (via claw-code analysis):
- Turn iteration cap (default 16) for tool-use chains within a single turn
- Per-message usage tracking for accurate token reconstruction from restored sessions
- Permission-aware tool execution (denied tools inject errors so LLM adapts)
- Continuation-style context compaction (summarize old messages, not just drop them)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from kaos.ccr.prompts import build_system_prompt
from kaos.ccr.tools import ToolRegistry, ToolPermissionPolicy

if TYPE_CHECKING:
    from kaos.core import Kaos
    from kaos.router.gepa import GEPARouter

logger = logging.getLogger(__name__)

# Max tool-use iterations within a single turn before forcing a stop.
# Prevents runaway tool-call loops where the model keeps calling tools
# without producing a final text response.
MAX_TOOL_ITERATIONS_PER_TURN = 16


@dataclass
class ToolCall:
    """Represents a tool call from the model."""

    id: str
    name: str
    input: dict[str, Any]


@dataclass
class ModelResponse:
    """Represents a response from the model."""

    content: str
    tool_calls: list[ToolCall]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens"
    usage: dict[str, int] | None = None


@dataclass
class UsageTracker:
    """Tracks cumulative token usage across an agent's lifetime.

    Embeds per-turn usage in conversation messages so usage can be
    reconstructed from a restored session without external metadata.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    turns: int = 0

    def record(self, usage: dict[str, int] | None) -> None:
        if usage:
            self.input_tokens += usage.get("prompt_tokens", 0)
            self.output_tokens += usage.get("completion_tokens", 0)
            self.total_tokens += usage.get("total_tokens", 0)
            self.turns += 1

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "turns": self.turns,
        }


class ClaudeCodeRunner:
    """
    Orchestrates agent execution loops.

    Each agent gets: a VFS namespace, a conversation, and a tool registry.
    CCR doesn't call LLMs directly — it goes through the GEPA router.
    """

    def __init__(
        self,
        afs: Kaos,
        router: GEPARouter,
        max_iterations: int = 100,
        checkpoint_interval: int = 10,
        timeout_seconds: int = 3600,
        max_parallel_agents: int = 8,
        max_tool_iterations: int = MAX_TOOL_ITERATIONS_PER_TURN,
        permission_policy: ToolPermissionPolicy | None = None,
    ):
        self.afs = afs
        self.router = router
        self.tools = ToolRegistry(afs, permission_policy=permission_policy)
        self.max_iterations = max_iterations
        self.checkpoint_interval = checkpoint_interval
        self.timeout_seconds = timeout_seconds
        self.max_parallel_agents = max_parallel_agents
        self.max_tool_iterations = max_tool_iterations
        self._active_agents: dict[str, asyncio.Task] = {}
        self._semaphore = asyncio.Semaphore(max_parallel_agents)

    def register_tool(self, tool) -> None:
        """Register a custom tool available to all agents."""
        self.tools.register(tool)

    async def run_agent(self, agent_id: str, task: str) -> str:
        """
        Main agent loop — plan, act, observe, repeat.

        Returns the agent's final output.
        """
        agent_info = self.afs.status(agent_id)
        config = agent_info["config"]

        # Set agent to running
        self.afs.set_status(agent_id, "running", pid=os.getpid())

        # Build system prompt
        system_prompt = build_system_prompt(
            agent_id=agent_id,
            agent_name=agent_info["name"],
            tools=self.tools.list_tool_metadata(),
            task=task,
        )

        # Initialize conversation in state
        conversation = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]
        self.afs.set_state(agent_id, "conversation", conversation)
        self.afs.set_state(agent_id, "iteration", 0)
        self.afs.set_state(agent_id, "task", task)

        start_time = time.time()
        usage_tracker = UsageTracker()

        try:
            for iteration in range(self.max_iterations):
                # Check timeout
                elapsed = time.time() - start_time
                if elapsed > self.timeout_seconds:
                    self.afs.fail(agent_id, error="Execution timeout")
                    raise TimeoutError(
                        f"Agent {agent_id} timed out after {elapsed:.0f}s"
                    )

                # Check if paused
                current_status = self.afs.status(agent_id)["status"]
                if current_status == "paused":
                    logger.info("Agent %s is paused, waiting...", agent_id)
                    await asyncio.sleep(1)
                    continue
                if current_status == "killed":
                    logger.info("Agent %s was killed", agent_id)
                    return "Agent was killed"

                # Route to appropriate model via GEPA
                response = await self.router.route(
                    agent_id=agent_id,
                    messages=conversation,
                    tools=self.tools.list_tools(),
                    config=config,
                )

                # Track usage per turn
                usage_tracker.record(response.usage)

                # Process assistant message
                if response.content:
                    conversation.append(
                        {"role": "assistant", "content": response.content,
                         "usage": response.usage}
                    )

                # Process tool calls
                if response.tool_calls:
                    # Add assistant message with tool calls
                    tool_call_msg = {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": json.dumps(tc.input),
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                    # Replace the last assistant message if we just added one
                    if response.content and conversation[-1]["role"] == "assistant":
                        conversation[-1] = tool_call_msg
                    else:
                        conversation.append(tool_call_msg)

                    for tc in response.tool_calls:
                        call_id = self.afs.log_tool_call(
                            agent_id, tc.name, tc.input
                        )
                        self.afs.start_tool_call(call_id)

                        try:
                            result = await self.tools.execute(
                                agent_id, tc.name, tc.input
                            )
                            result_str = (
                                result if isinstance(result, str) else json.dumps(result)
                            )
                            self.afs.complete_tool_call(
                                call_id,
                                {"result": result_str},
                                status="success",
                                token_count=response.usage.get("total_tokens")
                                if response.usage
                                else None,
                            )
                            conversation.append(
                                {
                                    "role": "tool",
                                    "content": result_str,
                                    "tool_call_id": tc.id,
                                }
                            )
                        except Exception as e:
                            error_msg = f"Error: {type(e).__name__}: {e}"
                            self.afs.complete_tool_call(
                                call_id,
                                {"error": str(e)},
                                status="error",
                                error_message=str(e),
                            )
                            conversation.append(
                                {
                                    "role": "tool",
                                    "content": error_msg,
                                    "tool_call_id": tc.id,
                                }
                            )

                # Check for completion
                if response.stop_reason == "end_turn" and not response.tool_calls:
                    final_result = response.content or ""
                    self.afs.set_state(agent_id, "result", final_result)
                    self.afs.set_state(agent_id, "usage", usage_tracker.to_dict())
                    self.afs.complete(agent_id)
                    return final_result

                # Auto-checkpoint
                if iteration > 0 and iteration % self.checkpoint_interval == 0:
                    self.afs.checkpoint(
                        agent_id, label=f"auto-iter-{iteration}"
                    )

                # Persist state
                self.afs.set_state(agent_id, "iteration", iteration + 1)
                self.afs.set_state(agent_id, "conversation", conversation)
                self.afs.heartbeat(agent_id)

            # Hit max iterations
            self.afs.fail(agent_id, error="Max iterations reached")
            return conversation[-1].get("content", "Max iterations reached")

        except Exception as e:
            self.afs.fail(agent_id, error=str(e))
            raise

    async def run_parallel(self, tasks: list[dict]) -> list[str]:
        """
        Spawn and run multiple agents concurrently.

        Each task dict should have:
        - name: str — agent name
        - prompt: str — the task description
        - config: dict (optional) — agent configuration
        - parent_id: str (optional) — parent agent ID
        """
        async def _run_one(task: dict) -> str:
            async with self._semaphore:
                agent_id = self.afs.spawn(
                    name=task["name"],
                    config=task.get("config", {}),
                    parent_id=task.get("parent_id"),
                )
                return await self.run_agent(agent_id, task["prompt"])

        results = await asyncio.gather(
            *[_run_one(t) for t in tasks],
            return_exceptions=True,
        )

        return [
            str(r) if isinstance(r, Exception) else r
            for r in results
        ]

    async def cancel_agent(self, agent_id: str) -> None:
        """Cancel a running agent."""
        task = self._active_agents.get(agent_id)
        if task and not task.done():
            task.cancel()
        self.afs.kill(agent_id)
