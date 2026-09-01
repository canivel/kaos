"""AgentSDKProvider — tool-calling + session isolation (v2.0.2, red-first).

The 2.0.1 provider dropped OpenAI-style tools (text-only), ran the SDK
session with the user's inherited Claude Code config (their MCP servers
leaked into KAOS agents!), and with ``max_turns=1`` any built-in tool
attempt died as "Reached maximum number of turns (1)".

New contract, pinned here with a fake ``claude_agent_sdk`` module:
  1. tools are serialized into the prompt under the shared <tool_call>
     protocol and parsed back into OpenAI-style tool_calls;
  2. the SDK session is isolated: no MCP inheritance
     (``mcp_servers={}``, ``strict_mcp_config=True``) and no built-in
     tools (``tools=[]``, ``allowed_tools=[]``);
  3. an is_error result whose text was still captured degrades gracefully.
"""

from __future__ import annotations

import sys
import types

import pytest

from kaos.router.agent_sdk import AgentSDKProvider


class _FakeResultMessage:
    def __init__(self, result="", is_error=False):
        self.result = result
        self.is_error = is_error


class _FakeTextBlock:
    def __init__(self, text):
        self.text = text


class _FakeAssistantMessage:
    def __init__(self, texts):
        self.message = types.SimpleNamespace(
            content=[_FakeTextBlock(t) for t in texts]
        )


@pytest.fixture()
def fake_sdk(monkeypatch):
    """Install a fake claude_agent_sdk capturing the options passed in."""
    captured = {}

    mod = types.ModuleType("claude_agent_sdk")

    class ClaudeAgentOptions:
        def __init__(self, **kw):
            captured["options"] = kw

    async def query(prompt, options):
        captured["prompt"] = prompt
        for m in captured.get("stream", []):
            yield m

    mod.query = query
    mod.ClaudeAgentOptions = ClaudeAgentOptions
    mod.ResultMessage = _FakeResultMessage
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", mod)
    return captured


TOOLS = [{
    "type": "function",
    "function": {
        "name": "fs_write",
        "description": "Write a file",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"},
                                      "content": {"type": "string"}}},
    },
}]


async def _chat(captured, stream, tools=TOOLS):
    captured["stream"] = stream
    p = AgentSDKProvider(model_id="sonnet", timeout=30.0)
    return await p.chat("sonnet",
                        [{"role": "user", "content": "write hello"}],
                        tools=tools)


class TestToolCalling:
    async def test_tools_are_advertised_in_prompt(self, fake_sdk):
        await _chat(fake_sdk, [_FakeResultMessage("done")])
        assert "fs_write" in fake_sdk["prompt"]
        assert "<tool_call" in fake_sdk["prompt"]

    async def test_tool_call_text_parsed_to_tool_calls(self, fake_sdk):
        proto = ('<tool_call id="tc_1" name="fs_write">\n'
                 '{"path": "/notes/x.md", "content": "hello"}\n'
                 '</tool_call>')
        r = await _chat(fake_sdk, [_FakeResultMessage(proto)])
        msg = r.choices[0].message
        assert msg.tool_calls and msg.tool_calls[0]["function"]["name"] == "fs_write"
        assert r.choices[0].finish_reason == "tool_calls"

    async def test_plain_text_still_plain(self, fake_sdk):
        r = await _chat(fake_sdk, [_FakeResultMessage("all done, no tools")])
        assert r.choices[0].message.tool_calls is None
        assert r.choices[0].finish_reason == "end_turn"


class TestSessionIsolation:
    async def test_no_mcp_inheritance_and_no_builtin_tools(self, fake_sdk):
        """The 2.0.1 leak: the SDK session inherited the user's Claude Code
        MCP servers (mail, travel, ...) into KAOS agents."""
        await _chat(fake_sdk, [_FakeResultMessage("ok")])
        opts = fake_sdk["options"]
        assert opts.get("mcp_servers") == {}, "user MCP config must not leak in"
        assert opts.get("strict_mcp_config") is True
        assert opts.get("tools") == []
        assert opts.get("allowed_tools") == []


class TestGracefulErrors:
    async def test_max_turns_error_with_captured_text_degrades_gracefully(self, fake_sdk):
        """If the SDK flags is_error (e.g. max turns) but assistant text was
        streamed, return the text instead of raising."""
        r = await _chat(fake_sdk, [
            _FakeAssistantMessage(["partial answer"]),
            _FakeResultMessage("Reached maximum number of turns (1)", is_error=True),
        ])
        assert "partial answer" in (r.choices[0].message.content or "")

    async def test_error_with_no_content_raises(self, fake_sdk):
        with pytest.raises(RuntimeError):
            await _chat(fake_sdk, [
                _FakeResultMessage("some upstream error", is_error=True),
            ])
