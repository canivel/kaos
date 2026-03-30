"""Tool registry and sandboxed tool execution for agents."""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, TYPE_CHECKING

if TYPE_CHECKING:
    from kaos.core import Kaos


@dataclass
class ToolDefinition:
    """Definition of a tool available to agents."""

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any] | Callable[..., Awaitable[Any]]
    is_async: bool = False
    timeout_seconds: int = 60


class ToolRegistry:
    """Registry of tools available to agents with sandboxed execution."""

    def __init__(self, afs: Kaos):
        self.afs = afs
        self._tools: dict[str, ToolDefinition] = {}
        self._register_builtins()

    def register(self, tool: ToolDefinition) -> None:
        """Register a tool."""
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        """Get a tool definition by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[dict]:
        """List all registered tools as OpenAI-compatible tool definitions."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def list_tool_metadata(self) -> list[dict]:
        """List tool names and descriptions."""
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    async def execute(
        self, agent_id: str, tool_name: str, arguments: dict[str, Any]
    ) -> Any:
        """Execute a tool with sandboxing and timeout."""
        tool = self._tools.get(tool_name)
        if not tool:
            raise ValueError(f"Unknown tool: {tool_name}")

        # Inject agent_id for filesystem tools
        if tool_name.startswith("fs_") or tool_name.startswith("state_"):
            arguments["agent_id"] = agent_id

        try:
            if tool.is_async:
                result = await asyncio.wait_for(
                    tool.handler(**arguments),
                    timeout=tool.timeout_seconds,
                )
            else:
                result = tool.handler(**arguments)
            return result
        except asyncio.TimeoutError:
            raise TimeoutError(
                f"Tool {tool_name} timed out after {tool.timeout_seconds}s"
            )

    def _register_builtins(self) -> None:
        """Register built-in filesystem and state tools."""
        self.register(ToolDefinition(
            name="fs_read",
            description="Read a file from the agent's virtual filesystem",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["path"],
            },
            handler=self._fs_read,
        ))

        self.register(ToolDefinition(
            name="fs_write",
            description="Write content to a file in the agent's virtual filesystem",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
            handler=self._fs_write,
        ))

        self.register(ToolDefinition(
            name="fs_ls",
            description="List files and directories at a path",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path", "default": "/"},
                },
            },
            handler=self._fs_ls,
        ))

        self.register(ToolDefinition(
            name="fs_delete",
            description="Delete a file from the agent's virtual filesystem",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to delete"},
                },
                "required": ["path"],
            },
            handler=self._fs_delete,
        ))

        self.register(ToolDefinition(
            name="fs_mkdir",
            description="Create a directory in the agent's virtual filesystem",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path to create"},
                },
                "required": ["path"],
            },
            handler=self._fs_mkdir,
        ))

        self.register(ToolDefinition(
            name="state_get",
            description="Get a state value by key",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "State key"},
                },
                "required": ["key"],
            },
            handler=self._state_get,
        ))

        self.register(ToolDefinition(
            name="state_set",
            description="Set a state value",
            parameters={
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "State key"},
                    "value": {"description": "Value to store (any JSON-serializable type)"},
                },
                "required": ["key", "value"],
            },
            handler=self._state_set,
        ))

        self.register(ToolDefinition(
            name="shell_exec",
            description="Execute a shell command (sandboxed)",
            parameters={
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command to execute"},
                    "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
                },
                "required": ["command"],
            },
            handler=self._shell_exec,
            timeout_seconds=120,
        ))

    # ── Built-in tool handlers ───────────────────────────────────────

    def _fs_read(self, agent_id: str, path: str) -> str:
        content = self.afs.read(agent_id, path)
        return content.decode("utf-8", errors="replace")

    def _fs_write(self, agent_id: str, path: str, content: str) -> str:
        self.afs.write(agent_id, path, content.encode("utf-8"))
        return f"Written {len(content)} bytes to {path}"

    def _fs_ls(self, agent_id: str, path: str = "/") -> str:
        entries = self.afs.ls(agent_id, path)
        return json.dumps(entries, indent=2)

    def _fs_delete(self, agent_id: str, path: str) -> str:
        self.afs.delete(agent_id, path)
        return f"Deleted {path}"

    def _fs_mkdir(self, agent_id: str, path: str) -> str:
        self.afs.mkdir(agent_id, path)
        return f"Created directory {path}"

    def _state_get(self, agent_id: str, key: str) -> str:
        value = self.afs.get_state_or(agent_id, key)
        return json.dumps(value)

    def _state_set(self, agent_id: str, key: str, value: Any) -> str:
        self.afs.set_state(agent_id, key, value)
        return f"State '{key}' updated"

    def _shell_exec(self, command: str, timeout: int = 30, **kwargs) -> str:
        """Execute a shell command with timeout and output capture."""
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nSTDERR:\n{result.stderr}"
            if result.returncode != 0:
                output += f"\nExit code: {result.returncode}"
            return output[:10000]  # Cap output size
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout}s"
