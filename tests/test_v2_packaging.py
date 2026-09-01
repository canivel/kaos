"""v2.0 packaging gates (roadmap v0.11-adoption, P1 — BINDING).

G1.1 — base install is small: ≤ 5 third-party deps, and ``import kaos``
       works without any extra installed.
G1.2 — layering: core/CLI import-time must not pull an extra's package;
       a missing extra produces one actionable message, not a traceback.
G1.3 — a third-party plugin distributed as a separate package is discovered
       through the ``kaos.plugins`` entry-point group with zero core changes.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

BASE_DEPS = {"click", "ulid-py", "zstandard", "pyyaml", "rich"}


def _project() -> dict:
    with open(ROOT / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]


class TestG11BaseFootprint:
    def test_dist_is_kaos_harness_import_is_kaos(self):
        assert _project()["name"] == "kaos-harness"

    def test_base_deps_are_exactly_the_small_clean_set(self):
        names = {
            d.split(">")[0].split("=")[0].split("[")[0].strip()
            for d in _project()["dependencies"]
        }
        assert names == BASE_DEPS, (
            f"base deps drifted: {sorted(names)}. Heavy deps belong in an "
            f"extra (G1.1: base ≤ 5 third-party deps)."
        )

    def test_extras_cover_the_moved_deps(self):
        extras = _project()["optional-dependencies"]
        assert any("mcp" in d for d in extras["mcp"])
        assert any("httpx" in d for d in extras["router"])
        assert any("textual" in d for d in extras["ui"])
        assert any("starlette" in d for d in extras["ui"])
        assert "eval" in extras and "all" in extras

    def test_version_is_consistent(self):
        import kaos
        assert _project()["version"] == kaos.__version__


class TestG12Layering:
    def test_core_and_cli_import_without_touching_extras(self):
        """The real G1.2 check: importing the base surface must not import
        httpx / mcp / textual, even when they happen to be installed."""
        code = textwrap.dedent("""
            import sys
            import kaos, kaos.core, kaos.memory, kaos.skills, kaos.shared_log
            import kaos.cli.main
            leaked = [m for m in ("httpx", "mcp", "textual", "starlette") if m in sys.modules]
            assert not leaked, f"base import pulled extras: {leaked}"
            print("layering ok")
        """)
        r = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True,
            cwd=ROOT,
        )
        assert r.returncode == 0, r.stderr
        assert "layering ok" in r.stdout

    def test_missing_extra_message_is_actionable(self):
        from kaos._extras import MissingExtraError, require
        with pytest.raises(MissingExtraError) as ei:
            require("kaos_definitely_not_installed_mod", "router", "The frobnicator")
        msg = str(ei.value)
        assert "pip install 'kaos-harness[router]'" in msg
        assert "The frobnicator" in msg

    def test_cli_entry_point_prints_one_line_not_traceback(self, monkeypatch, capsys):
        import kaos.cli.main as m
        from kaos._extras import MissingExtraError

        def boom():
            raise MissingExtraError("X requires 'kaos-harness[ui]'")

        monkeypatch.setattr(m, "cli", boom)
        with pytest.raises(SystemExit) as ei:
            m.main()
        assert ei.value.code == 1
        assert "kaos-harness[ui]" in capsys.readouterr().err


class TestG13PluginDiscovery:
    @pytest.fixture()
    def toy_plugin(self, tmp_path, monkeypatch):
        """A separate 'installed' distribution: package + .dist-info with an
        entry point in the kaos.plugins group. Nothing in kaos core knows it."""
        pkg = tmp_path / "kaos_toy_plugin"
        pkg.mkdir()
        (pkg / "__init__.py").write_text(textwrap.dedent("""
            class ToyProvider:
                def __init__(self, **kw):
                    self.kw = kw

            class ToyBenchmark:
                def __init__(self, **kw):
                    self.kw = kw

            def _dispatch(name, args):
                return f"toy:{name}:{args.get('x')}"

            def register(reg):
                reg.add_provider("toy", ToyProvider)
                reg.add_benchmark("toy_bench", ToyBenchmark)
                reg.add_mcp_tools(
                    [{"name": "toy_echo",
                      "description": "echo",
                      "input_schema": {"type": "object",
                                       "properties": {"x": {"type": "string"}}}}],
                    _dispatch,
                )
        """))
        dist = tmp_path / "kaos_toy_plugin-0.1.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: kaos-toy-plugin\nVersion: 0.1\n"
        )
        (dist / "entry_points.txt").write_text(
            "[kaos.plugins]\ntoy = kaos_toy_plugin:register\n"
        )
        (dist / "RECORD").write_text("")
        monkeypatch.syspath_prepend(str(tmp_path))

        import kaos.plugins as kp
        reg = kp.get_registry(reload=True)
        yield reg
        # drop the toy plugin for later tests
        sys.modules.pop("kaos_toy_plugin", None)
        kp._registry = None

    def test_plugin_is_discovered(self, toy_plugin):
        assert "toy" in toy_plugin.loaded
        assert not toy_plugin.errors

    def test_plugin_provider_reachable_via_create_provider(self, toy_plugin):
        pytest.importorskip("httpx")
        from kaos.router.providers import create_provider
        p = create_provider("toy", model_id="m1")
        assert type(p).__name__ == "ToyProvider"
        assert p.kw["model_id"] == "m1"

    def test_plugin_benchmark_reachable_via_get_benchmark(self, toy_plugin):
        from kaos.metaharness.benchmarks import get_benchmark
        b = get_benchmark("toy_bench")
        assert type(b).__name__ == "ToyBenchmark"

    def test_plugin_mcp_tools_listed_and_dispatched(self, toy_plugin):
        pytest.importorskip("mcp")
        from kaos.mcp.server import build_tool_list
        names = [t.name for t in build_tool_list()]
        assert "toy_echo" in names
        pack = toy_plugin.mcp_tool_packs[0]
        assert pack.dispatcher("toy_echo", {"x": "hi"}) == "toy:toy_echo:hi"

    def test_broken_plugin_never_takes_kaos_down(self, tmp_path, monkeypatch):
        dist = tmp_path / "kaos_broken_plugin-0.1.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: kaos-broken-plugin\nVersion: 0.1\n"
        )
        (dist / "entry_points.txt").write_text(
            "[kaos.plugins]\nbroken = kaos_broken_plugin_missing:register\n"
        )
        (dist / "RECORD").write_text("")
        monkeypatch.syspath_prepend(str(tmp_path))
        import kaos.plugins as kp
        reg = kp.get_registry(reload=True)
        assert "broken" in reg.errors
        assert "broken" not in reg.loaded
        kp._registry = None
