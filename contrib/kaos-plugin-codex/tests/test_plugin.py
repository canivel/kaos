"""Contract tests for kaos-plugin-codex. No network, no real codex binary."""

from __future__ import annotations

import asyncio
import os
import stat
import sys
import textwrap

import pytest

from kaos.plugins import PluginRegistry

import kaos_plugin_codex as plugin


def test_register_contributes_codex_provider():
    reg = PluginRegistry()
    reg._current = "codex"
    plugin.register(reg)
    assert "codex" in reg.providers


def test_build_command_contract(tmp_path):
    cmd = plugin.build_command(
        "/bin/codex", "gpt-6-astra", str(tmp_path / "out.md"),
        sandbox="read-only", cwd="/repo", reasoning_effort="high",
        extra_args=["--json"],
    )
    assert cmd[:2] == ["/bin/codex", "exec"]
    assert cmd[cmd.index("-m") + 1] == "gpt-6-astra"
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in cmd and "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("-o") + 1].endswith("out.md")
    assert cmd[cmd.index("-C") + 1] == "/repo"
    assert 'model_reasoning_effort="high"' in cmd
    assert cmd[-1] == "-"  # prompt on stdin
    assert "--json" in cmd


def test_build_command_rejects_bad_sandbox():
    with pytest.raises(ValueError):
        plugin.build_command("/bin/codex", "m", "/tmp/x", sandbox="yolo")


def _fake_codex(tmp_path, body: str) -> str:
    """Write a stand-in `codex` script that mimics `codex exec ... -o FILE -`."""
    script = tmp_path / "codex"
    script.write_text(textwrap.dedent(body))
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def test_round_trip_reads_last_message_file(tmp_path):
    pytest.importorskip("httpx", reason="provider base lives in the [router] extra")
    exe = _fake_codex(tmp_path, """\
        #!/usr/bin/env python3
        import sys
        args = sys.argv[1:]
        out = args[args.index("-o") + 1]
        prompt = sys.stdin.read()
        print("sandbox: read-only\\nuser\\n" + prompt + "\\ncodex\\nignored stdout")
        open(out, "w").write("PONG from " + args[args.index("-m") + 1])
        """)
    p = plugin.make_codex_provider(model_id="gpt-6-astra", codex_executable=exe,
                                   timeout=20, idle_timeout=10)
    r = asyncio.run(p.chat("gpt-6-astra", [{"role": "user", "content": "ping"}]))
    assert r.choices[0].message.content == "PONG from gpt-6-astra"
    assert r.choices[0].finish_reason == "end_turn"


def test_tool_call_protocol_parsed(tmp_path):
    pytest.importorskip("httpx")
    exe = _fake_codex(tmp_path, """\
        #!/usr/bin/env python3
        import sys
        args = sys.argv[1:]
        out = args[args.index("-o") + 1]
        sys.stdin.read()
        open(out, "w").write('<tool_call id="c1" name="fs_read">{"path": "/a.txt"}</tool_call>')
        """)
    p = plugin.make_codex_provider(codex_executable=exe, timeout=20)
    r = asyncio.run(p.chat("m", [{"role": "user", "content": "read it"}],
                           tools=[{"name": "fs_read", "description": "", "parameters": {}}]))
    msg = r.choices[0].message
    assert r.choices[0].finish_reason == "tool_calls"
    assert msg.tool_calls and msg.tool_calls[0]["function"]["name"] == "fs_read"


def test_nonzero_exit_raises(tmp_path):
    pytest.importorskip("httpx")
    exe = _fake_codex(tmp_path, """\
        #!/usr/bin/env python3
        import sys
        sys.stdin.read()
        sys.stderr.write("not logged in")
        sys.exit(3)
        """)
    p = plugin.make_codex_provider(codex_executable=exe, timeout=20)
    with pytest.raises(RuntimeError, match="exited 3.*not logged in"):
        asyncio.run(p.chat("m", [{"role": "user", "content": "x"}]))


def test_wall_timeout_kills(tmp_path):
    pytest.importorskip("httpx")
    exe = _fake_codex(tmp_path, """\
        #!/usr/bin/env python3
        import sys, time
        sys.stdin.read()
        time.sleep(30)
        """)
    p = plugin.make_codex_provider(codex_executable=exe, timeout=1.0, idle_timeout=5.0)
    with pytest.raises(TimeoutError):
        asyncio.run(p.chat("m", [{"role": "user", "content": "x"}]))
