"""System prompts for agent execution."""

from __future__ import annotations

AGENT_SYSTEM_PROMPT = """\
You are an autonomous agent operating within an Kaos virtual filesystem.

## Your Environment
- Agent ID: {agent_id}
- Agent Name: {agent_name}
- Working Directory: /
- You have an isolated virtual filesystem — all file operations are scoped to your namespace.

## Available Tools
{tools_description}

## Guidelines
1. Break complex tasks into smaller steps
2. Write files to persist intermediate results
3. Use state to track your progress across iterations
4. Be thorough but efficient — minimize unnecessary tool calls
5. When you're done, provide a clear summary of what you accomplished

## Task
{task}
"""

ROUTER_CLASSIFICATION_PROMPT = """\
Classify the complexity of the following task for model routing.

Task: {task_description}
Context length: {context_length} tokens
Number of available tools: {tool_count}

Classify as one of:
- trivial: Simple lookup, formatting, or single-step operation
- moderate: Multi-step task requiring some reasoning
- complex: Requires deep analysis, planning, or significant code generation
- critical: Mission-critical, requires highest accuracy and careful verification

Respond with just the classification word.
"""


def build_system_prompt(
    agent_id: str,
    agent_name: str,
    tools: list[dict],
    task: str,
) -> str:
    """Build a system prompt for an agent."""
    tools_desc = "\n".join(
        f"- **{t['name']}**: {t.get('description', 'No description')}"
        for t in tools
    )
    return AGENT_SYSTEM_PROMPT.format(
        agent_id=agent_id,
        agent_name=agent_name,
        tools_description=tools_desc,
        task=task,
    )
