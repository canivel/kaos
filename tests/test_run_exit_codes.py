"""Fleet-developer report: idle_timeout unreachable from config + `kaos run`
exits 0 on agent failure. Both fixed; these tests pin the fixes."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from kaos import Kaos
from kaos.ccr.runner import ClaudeCodeRunner
from kaos.cli.main import cli
from kaos.router.gepa import GEPARouter
from kaos.router.providers import ClaudeCodeProvider, create_provider


# ── idle_timeout: config -> ModelConfig -> provider (3 links) ────────

class TestIdleTimeoutPlumbing:
    def test_yaml_reaches_provider(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ClaudeCodeProvider, "_find_claude", lambda self: "claude")
        cfg = tmp_path / "kaos.yaml"
        cfg.write_text(
            "models:\n"
            "  opus:\n"
            "    provider: claude_code\n"
            "    model_id: claude-opus-5\n"
            "    timeout: 1800\n"
            "    idle_timeout: 420\n"
            "    use_for: [complex]\n"
            "router:\n  fallback_model: opus\n")
        router = GEPARouter.from_config(str(cfg))
        p = router.clients["opus"]
        assert p.timeout == 1800.0
        assert p.idle_timeout == 420.0          # was pinned at 60 before the fix

    def test_default_stays_60(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ClaudeCodeProvider, "_find_claude", lambda self: "claude")
        cfg = tmp_path / "kaos.yaml"
        cfg.write_text(
            "models:\n"
            "  opus:\n"
            "    provider: claude_code\n"
            "    model_id: claude-opus-5\n"
            "    use_for: [complex]\n"
            "router:\n  fallback_model: opus\n")
        router = GEPARouter.from_config(str(cfg))
        assert router.clients["opus"].idle_timeout == 60.0

    def test_create_provider_forwards(self, monkeypatch):
        monkeypatch.setattr(ClaudeCodeProvider, "_find_claude", lambda self: "claude")
        p = create_provider("claude_code", model_id="m", timeout=100.0,
                            idle_timeout=333.0)
        assert p.idle_timeout == 333.0


# ── exit codes: the CLI must not report success on failure ───────────

class _FailingRouter:
    clients = {"fake": object()}

    async def route(self, **kw):
        raise RuntimeError("provider blew up")


class _OkRouter:
    clients = {"fake": object()}

    async def route(self, **kw):
        return SimpleNamespace(content="done", tool_calls=[],
                               stop_reason="end_turn", usage={})


def _invoke_run(tmp_path, monkeypatch, router):
    cfg = tmp_path / "kaos.yaml"
    cfg.write_text("models: {}\nrouter: {}\n")
    monkeypatch.setattr(GEPARouter, "from_config",
                        classmethod(lambda cls, path: router))
    return CliRunner().invoke(
        cli, ["run", "some task", "--name", "w",
              "--db", str(tmp_path / "k.db"), "--config-file", str(cfg)])

class TestRunExitCode:
    def test_failure_exits_nonzero(self, tmp_path, monkeypatch):
        r = _invoke_run(tmp_path, monkeypatch, _FailingRouter())
        assert r.exit_code == 1, r.output       # was 0 before the fix
        assert "failed" in r.output.lower()

    def test_success_exits_zero(self, tmp_path, monkeypatch):
        r = _invoke_run(tmp_path, monkeypatch, _OkRouter())
        assert r.exit_code == 0, r.output


class TestRunParallelDetailed:
    def test_reports_ok_and_failed_distinctly(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "k.db"))

        class _Half:
            clients = {"fake": object()}
            calls = 0

            async def route(self, **kw):
                _Half.calls += 1
                if _Half.calls % 2 == 0:
                    raise RuntimeError("boom")
                return SimpleNamespace(content="done", tool_calls=[],
                                       stop_reason="end_turn", usage={})

        runner = ClaudeCodeRunner(afs, _Half())
        out = asyncio.run(runner.run_parallel_detailed(
            [{"name": "a", "prompt": "x"}, {"name": "b", "prompt": "y"}]))
        assert len(out) == 2
        assert sorted(o["ok"] for o in out) == [False, True]
        failed = next(o for o in out if not o["ok"])
        assert failed["status"] == "failed"
        afs.close()
