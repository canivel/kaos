"""M1/M4 of docs/roadmap/v2.1-stars.md: kaos-hook, kaos connect, kaos journal,
the Claude Code plugin files, and `kaos demo --print`."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path

import pytest
from click.testing import CliRunner

from kaos import hook
from kaos._ids import new_ulid
from kaos.cli.main import cli
from kaos.connect import HOOK_SPEC, connect_claude_code
from kaos.core import Kaos
from kaos.memory import MemoryStore

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "claude-code"


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "kaos.db")
    k = Kaos(path)
    aid = k.spawn("seed")
    mem = MemoryStore(k.conn)
    mem.write(aid, "Payment retry double-charge: client timeout != server failure. "
                   "Fix = Idempotency-Key generated once per logical charge.",
              type="insight", key="payment-retry-idempotency")
    mem.write(aid, "payments-service deploy: run migrations before the canary.", type="skill")
    k.close()
    return path


def _payload(**kw):
    base = {"session_id": "sess-123", "transcript_path": "/tmp/t.jsonl", "cwd": "/home/dev/payments-service"}
    base.update(kw)
    return json.dumps(base)


def test_new_ulid_is_format_compatible():
    a, b = new_ulid(), new_ulid()
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", a)
    assert a != b and a[:10] <= b[:10]  # time-sortable prefix


def test_session_start_creates_agent_and_injects(db, capsys, monkeypatch):
    monkeypatch.setenv("KAOS_HOOK_NO_CONSOLIDATE", "1")
    rc = hook.main(["session-start", "--db", db], stdin_text=_payload(hook_event_name="SessionStart"))
    assert rc == 0
    out = capsys.readouterr().out
    assert "<kaos-memory" in out and "payments-service" in out
    conn = sqlite3.connect(db)
    name, status = conn.execute("SELECT name, status FROM agents WHERE name LIKE 'claude-code:%'").fetchone()
    assert name == "claude-code:sess-123" and status == "running"
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type='session_start'").fetchone()[0] == 1
    # plasticity learned that the recalled memory was consulted
    assert conn.execute("SELECT COUNT(*) FROM memory_hits").fetchone()[0] >= 1


def test_tool_hook_records_tool_call_and_file_write(db):
    p = _payload(hook_event_name="PostToolUse", tool_name="Edit",
                 tool_input={"file_path": "/home/dev/payments-service/payments.py", "old_string": "a", "new_string": "b"},
                 tool_result={"ok": True}, tool_use_id="toolu_1")
    assert hook.main(["tool", "--db", db], stdin_text=p) == 0
    conn = sqlite3.connect(db)
    tool, status = conn.execute("SELECT tool_name, status FROM tool_calls").fetchone()
    assert tool == "Edit" and status == "success"
    types = {r[0] for r in conn.execute("SELECT event_type FROM events")}
    assert {"agent_spawn", "tool_call_end", "file_write"} <= types


def test_prompt_hook_journals_but_injects_only_when_enabled(db, capsys, monkeypatch):
    p = _payload(hook_event_name="UserPromptSubmit", user_message="double charge on payment retry timeout")
    monkeypatch.setenv("KAOS_HOOK_PROMPT_INJECT", "0")
    hook.main(["prompt", "--db", db], stdin_text=p)
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("KAOS_HOOK_PROMPT_INJECT", "1")
    hook.main(["prompt", "--db", db], stdin_text=p)
    assert "Idempotency-Key" in capsys.readouterr().out
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type='user_prompt'").fetchone()[0] == 2


def test_stop_and_session_end(db, monkeypatch):
    monkeypatch.setenv("KAOS_HOOK_NO_CONSOLIDATE", "1")
    hook.main(["stop", "--db", db], stdin_text=_payload(last_assistant_message="done"))
    hook.main(["session-end", "--db", db], stdin_text=_payload(reason="exit"))
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status FROM agents WHERE name='claude-code:sess-123'").fetchone()[0] == "completed"
    assert {r[0] for r in conn.execute("SELECT event_type FROM events")} >= {"turn_end", "session_end"}


def test_hook_never_raises_on_garbage(db, capsys):
    assert hook.main(["tool", "--db", db], stdin_text="not json at all") == 0
    assert hook.main(["session-start", "--db", db], stdin_text="[1,2,3]") == 0
    assert hook.main(["bogus"], stdin_text="{}") == 0


def test_hook_resolves_db_to_project_kaos_db_when_present(tmp_path, monkeypatch):
    (tmp_path / "kaos.db").touch()
    assert hook.resolve_db(None, str(tmp_path)) == str(tmp_path / "kaos.db")
    monkeypatch.setenv("KAOS_HOME", str(tmp_path / "home"))
    assert hook.resolve_db(None, str(tmp_path / "other")).endswith("claude-code.db")


def test_fts_query_sanitizes():
    q = hook.fts_query('fix the "payments" webhook: retry(timeout)!! the the')
    assert q == '"fix" OR "payments" OR "webhook" OR "retry" OR "timeout"'
    assert hook.fts_query("a an the") == ""


def test_format_inject_respects_token_cap(db):
    k = Kaos(db)
    hits = MemoryStore(k.conn).search('"payment"', limit=5)
    block = hook.format_inject(hits, token_cap=30)
    assert block.startswith("<kaos-memory") and block.endswith("</kaos-memory>")
    assert len(block) <= 30 * 4 + 200  # header + closing tag overhead
    k.close()


def test_journal_append_cli(db):
    r = CliRunner().invoke(cli, ["--json", "journal", "append", "--session", "s9", "--event", "session_start",
                                 "--payload", '{"cwd": "/x"}', "--db", db])
    assert r.exit_code == 0, r.output
    res = json.loads(r.output)
    assert res["event_type"] == "session_start"
    r2 = CliRunner().invoke(cli, ["journal", "append", "--session", "s9", "--event", "tool_use", "--stdin", "--db", db],
                            input='{"tool_name": "Bash"}')
    assert r2.exit_code == 0, r2.output
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM agents WHERE name='claude-code:s9'").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM events WHERE event_type IN ('session_start','tool_use')").fetchone()[0] == 2


def test_memory_search_inject_format(db):
    r = CliRunner().invoke(cli, ["memory", "search", '"payment"', "--format", "inject", "--token-cap", "200", "--db", db])
    assert r.exit_code == 0, r.output
    assert "<kaos-memory" in r.output and "Idempotency-Key" in r.output


def test_connect_claude_code_writes_and_merges(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash(ls)"]},
                                    "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    res = connect_claude_code(tmp_path, scope="project", prompt_inject=True, home=tmp_path / "home")
    data = json.loads(settings.read_text())
    assert data["permissions"] == {"permissions": {"allow": ["Bash(ls)"]}}["permissions"]
    assert any("echo hi" in h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"])
    assert any("kaos-hook stop" in h["command"] for g in data["hooks"]["Stop"] for h in g["hooks"])
    assert set(data["hooks"]) == {e for e, *_ in HOOK_SPEC}
    mcp = json.loads((tmp_path / ".mcp.json").read_text())
    assert mcp["mcpServers"]["kaos"]["args"] == ["serve", "--transport", "stdio"]
    assert json.loads((tmp_path / "home" / ".kaos" / "hook.json").read_text())["prompt_inject"] is True
    # idempotent
    connect_claude_code(tmp_path, scope="project", home=tmp_path / "home")
    data2 = json.loads(settings.read_text())
    assert sum("kaos-hook" in h["command"] for g in data2["hooks"]["Stop"] for h in g["hooks"]) == 1
    assert len(res["written"]) == 3


def test_connect_cli(tmp_path):
    r = CliRunner().invoke(cli, ["--json", "connect", "claude-code", "--dir", str(tmp_path)])
    assert r.exit_code == 0, r.output
    assert (tmp_path / ".claude" / "settings.json").exists()


def test_plugin_files_are_valid_and_in_sync():
    manifest = json.loads((PLUGIN / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == "kaos" and manifest["version"]
    market = json.loads((REPO / ".claude-plugin" / "marketplace.json").read_text())
    entry = market["plugins"][0]
    assert entry["source"] == "./plugins/claude-code" and (REPO / entry["source"]).is_dir()
    assert entry["version"] == manifest["version"]
    hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
    spec = {e: (sub, t, a) for e, sub, t, a in HOOK_SPEC}
    assert set(hooks) == set(spec)
    for event, groups in hooks.items():
        h = groups[0]["hooks"][0]
        sub, timeout, is_async = spec[event]
        assert h["command"].endswith(f"bin/kaos-hook {sub}")
        assert h["timeout"] == timeout and bool(h.get("async")) == is_async
    mcp = json.loads((PLUGIN / ".mcp.json").read_text())
    assert "kaos" in mcp["mcpServers"]
    assert (PLUGIN / "skills" / "recall" / "SKILL.md").read_text().startswith("---")
    launcher = PLUGIN / "bin" / "kaos-hook"
    assert launcher.read_text().startswith("#!/usr/bin/env bash")


def test_demo_print_is_fast_and_measured(monkeypatch, tmp_path):
    monkeypatch.setenv("KAOS_DEMO_AGENTS", "300")
    monkeypatch.setenv("KAOS_DEMO_PER_AGENT", "10")
    monkeypatch.chdir(tmp_path)
    t0 = time.perf_counter()
    r = CliRunner().invoke(cli, ["demo", "--print"])
    elapsed = time.perf_counter() - t0
    assert r.exit_code == 0, r.output
    assert elapsed < 10
    assert "p95" in r.output and "measured now" in r.output
    assert "3,000 entries" in r.output
    assert "claude plugin marketplace add canivel/kaos" in r.output
    assert list(tmp_path.iterdir()) == []  # --print leaves nothing behind
