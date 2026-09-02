"""kaos-plugin-example — a complete, tiny KAOS plugin.

Copy this directory, rename ``kaos_plugin_example`` and the entry-point name in
``pyproject.toml``, and publish as ``kaos-plugin-<name>``. KAOS discovers it
through the ``kaos.plugins`` entry-point group and calls :func:`register` once
per process with a :class:`kaos.plugins.PluginRegistry`.

Two contributions are shown:

* a model provider (``echo``) selectable in ``kaos.yaml`` as
  ``provider: echo`` — it returns the last user message, which makes it a
  handy deterministic stand-in for tests and demos;
* an MCP tool pack (``example_word_count``) that appears in ``kaos serve``
  next to the 58 built-in tools.

A plugin must never take KAOS down: keep ``register`` cheap and free of
side effects, and import optional extras lazily inside the factory.
"""

from __future__ import annotations

from typing import Any

__version__ = "0.1.0"


# ── Provider ──────────────────────────────────────────────────────────


def make_echo_provider(**model_kwargs: Any):
    """Factory called by the router: ``factory(**model_kwargs) -> LLMProvider``.

    ``kaos.router.providers`` needs the ``[router]`` extra, so import it here
    rather than at module import time — the plugin stays loadable on a slim
    install and only fails (with KAOS's own actionable message) when a model
    actually asks for it.
    """
    from kaos.router.providers import (
        LLMChoice,
        LLMMessage,
        LLMProvider,
        LLMResponse,
        LLMUsage,
    )

    class EchoProvider(LLMProvider):
        def __init__(self, model_id: str = "echo", **_: Any) -> None:
            self.model_id = model_id

        async def chat(
            self,
            model: str,
            messages: list[dict],
            temperature: float = 0.1,
            max_tokens: int = 4096,
            tools: list[dict] | None = None,
            tool_choice: str | None = None,
        ) -> LLMResponse:
            last_user = next(
                (m.get("content") or "" for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            text = str(last_user)[:max_tokens]
            return LLMResponse(
                choices=[LLMChoice(message=LLMMessage(role="assistant", content=text),
                                   finish_reason="stop")],
                usage=LLMUsage(input_tokens=len(text.split()), output_tokens=len(text.split()),
                               total_tokens=2 * len(text.split())),
            )

        async def close(self) -> None:
            return None

    return EchoProvider(**model_kwargs)


# ── MCP tool pack ─────────────────────────────────────────────────────

MCP_TOOLS: list[dict[str, Any]] = [
    {
        "name": "example_word_count",
        "description": "Count words in a piece of text (plugin template demo tool).",
        "input_schema": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "Text to count"}},
            "required": ["text"],
        },
    }
]


def dispatch(name: str, arguments: dict[str, Any]) -> str:
    """``dispatcher(name, arguments) -> str`` for every tool in ``MCP_TOOLS``."""
    if name == "example_word_count":
        return str(len(str(arguments.get("text", "")).split()))
    raise KeyError(f"kaos-plugin-example does not provide tool {name!r}")


# ── Entry point ───────────────────────────────────────────────────────


def register(registry) -> None:
    """Called by KAOS. ``registry`` is a ``kaos.plugins.PluginRegistry``."""
    registry.add_provider("echo", make_echo_provider)
    registry.add_mcp_tools(MCP_TOOLS, dispatch)
