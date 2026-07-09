"""v0.10 trust-sweep — credibility guards (tool-count SSOT, CLI smoke, dispatch coverage).

The v0.10 panel (trust-sweep-verify-numerics) found the MCP tool count stated as
17/18/25/45/50/58 across six files simultaneously, a 2,997-line CLI with zero
tests, and schema-vs-dispatch drift. A framework whose pitch is verified
reliability should not contradict itself in its own docs. These tests pin the
single source of truth (build_tool_list) and smoke the CLI surface.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from kaos.mcp.server import build_tool_list, mcp_tool_count, mcp_tool_names
from kaos.cli.main import cli

REPO = Path(__file__).resolve().parent.parent


# ── single source of truth ───────────────────────────────────────────


class TestToolCountSSOT:
    def test_count_helpers_agree_with_list(self):
        tools = build_tool_list()
        assert mcp_tool_count() == len(tools)
        assert len(mcp_tool_names()) == len(tools)

    def test_surface_is_58(self):
        # Pin the current surface. Adding/removing a tool must be a deliberate
        # change to this number AND the docs below — never silent drift.
        assert mcp_tool_count() == 58

    def test_no_duplicate_tool_names(self):
        names = [t.name for t in build_tool_list()]
        assert len(names) == len(set(names)), "duplicate MCP tool name"


# ── docs must not contradict the code ────────────────────────────────

# Current-state surfaces (NOT changelog/blog, which are historical record).
_CURRENT_STATE_DOCS = [
    "README.md",
    "docs/cli-reference.md",
    "docs/mcp-integration.md",
    "docs/README.md",
    "docs/architecture.md",
    "docs/meta-harness.md",
    "docs/tutorial-local-agents.md",
]

# Numbers that were once the count but are now stale as a CURRENT claim.
_STALE = ["17", "18", "25", "45", "50"]


class TestDocConsistency:
    @pytest.mark.parametrize("doc", _CURRENT_STATE_DOCS)
    def test_no_stale_current_tool_count(self, doc: str):
        text = (REPO / doc).read_text(encoding="utf-8")
        count = mcp_tool_count()
        # Historical signals: a match near these is describing the past, not
        # asserting the current surface (e.g. "v0.5 shipped 18 tools",
        # "grew to 50", "50 -> 58"). Only bare present-tense claims are stale.
        hist = re.compile(
            r"shipped|grew|evolution|added|→|->|v0\.[0-8]", re.IGNORECASE)
        for n in _STALE:
            for pat in (rf"\b{n}\s+tools\b", rf"\b{n}\s+MCP\s+tools\b"):
                for m in re.finditer(pat, text, re.IGNORECASE):
                    ctx = text[max(0, m.start() - 60): m.end() + 20]
                    if hist.search(ctx):
                        continue
                    pytest.fail(
                        f"{doc}: stale current tool-count '{n} tools' "
                        f"(surface is {count}): ...{ctx.strip()}..."
                    )

    def test_readme_and_cli_ref_state_current_count(self):
        count = str(mcp_tool_count())
        readme = (REPO / "README.md").read_text(encoding="utf-8")
        cli_ref = (REPO / "docs/cli-reference.md").read_text(encoding="utf-8")
        assert count in readme, f"README does not state the {count}-tool surface"
        assert count in cli_ref, f"cli-reference does not state {count} tools"


# ── every registered tool is dispatchable, and vice versa ────────────


class TestDispatchCoverage:
    def _dispatch_names(self) -> set[str]:
        from kaos.mcp import server
        src = inspect.getsource(server._dispatch)
        return set(re.findall(r'name == "([a-z_]+)"', src))

    def test_every_registered_tool_has_a_dispatch_branch(self):
        registered = set(mcp_tool_names())
        dispatched = self._dispatch_names()
        missing = registered - dispatched
        assert not missing, (
            f"registered tools with no dispatch branch (schema drift): {sorted(missing)}"
        )

    def test_no_dispatch_branch_without_registration(self):
        registered = set(mcp_tool_names())
        dispatched = self._dispatch_names()
        orphan = dispatched - registered
        assert not orphan, (
            f"dispatch branches for unregistered tools (dead code): {sorted(orphan)}"
        )


# ── CLI smoke — the 2,997-line main.py had zero tests ────────────────


class TestCliSmoke:
    def setup_method(self):
        self.runner = CliRunner()

    def test_version(self):
        from kaos import __version__
        r = self.runner.invoke(cli, ["--version"])
        assert r.exit_code == 0
        assert __version__ in r.output

    def test_help(self):
        r = self.runner.invoke(cli, ["--help"])
        assert r.exit_code == 0
        # Command groups should be listed
        for grp in ("run", "ls", "doctor", "eval", "experiment", "serve"):
            assert grp in r.output

    def test_init_and_ls_roundtrip(self, tmp_path):
        db = str(tmp_path / "smoke.db")
        r = self.runner.invoke(cli, ["init", "--db", db])
        assert r.exit_code == 0, r.output
        r = self.runner.invoke(cli, ["ls", "--db", db])
        assert r.exit_code == 0, r.output

    def test_json_ls_is_valid_json(self, tmp_path):
        import json
        db = str(tmp_path / "smoke.db")
        self.runner.invoke(cli, ["init", "--db", db])
        r = self.runner.invoke(cli, ["--json", "ls", "--db", db])
        assert r.exit_code == 0, r.output
        json.loads(r.output)  # must parse

    @pytest.mark.parametrize("group", ["doctor", "eval", "experiment"])
    def test_v09_group_help(self, group):
        r = self.runner.invoke(cli, [group, "--help"])
        assert r.exit_code == 0, r.output

    def test_experiment_log_list_via_cli(self, tmp_path):
        import json
        db = str(tmp_path / "smoke.db")
        self.runner.invoke(cli, ["init", "--db", db])
        r = self.runner.invoke(cli, [
            "experiment", "log", "--name", "cli-smoke", "--verdict", "ACCEPT",
            "--git-sha", "", "--db", db,
        ])
        assert r.exit_code == 0, r.output
        r = self.runner.invoke(cli, ["--json", "experiment", "list", "--db", db])
        assert r.exit_code == 0, r.output
        data = json.loads(r.output)
        assert any(e["name"] == "cli-smoke" for e in data["experiments"])
