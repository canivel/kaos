"""Contract tests for the plugin template.

They exercise ``register`` directly against a fresh registry, so they pass
before the package is installed; ``test_discovered_when_installed`` is the
end-to-end check and is skipped until ``pip install -e .`` has been run.
"""

from __future__ import annotations

import asyncio

import pytest

from kaos.plugins import PluginRegistry, get_registry

import kaos_plugin_example as plugin


def test_register_contributes_provider_and_tool_pack():
    reg = PluginRegistry()
    reg._current = "example"
    plugin.register(reg)
    assert "echo" in reg.providers
    assert [t["name"] for p in reg.mcp_tool_packs for t in p.tools] == ["example_word_count"]
    assert reg.mcp_tool_packs[0].plugin == "example"


def test_mcp_tool_dispatch():
    assert plugin.dispatch("example_word_count", {"text": "one two three"}) == "3"
    with pytest.raises(KeyError):
        plugin.dispatch("not_a_tool", {})


def test_echo_provider_round_trip():
    pytest.importorskip("httpx", reason="provider base class lives in the [router] extra")
    p = plugin.make_echo_provider(model_id="echo")
    resp = asyncio.run(p.chat("echo", [{"role": "user", "content": "hello kaos"}]))
    assert resp.choices[0].message.content == "hello kaos"
    asyncio.run(p.close())


def test_discovered_when_installed():
    reg = get_registry(reload=True)
    if "example" not in reg.loaded:
        pytest.skip("run `pip install -e contrib/plugin-template` to test discovery")
    assert not reg.errors.get("example")
    assert "echo" in reg.providers
