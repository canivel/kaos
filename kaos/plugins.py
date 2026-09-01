"""KAOS plugin surface (v2.0).

Third-party packages extend KAOS without touching core by declaring a
setuptools entry point in the ``kaos.plugins`` group:

    # pyproject.toml of a plugin package
    [project.entry-points."kaos.plugins"]
    my_plugin = "my_pkg.kaos_plugin:register"

The entry-point target is a callable that receives a :class:`PluginRegistry`
and calls its ``add_*`` hooks. Discovery is lazy and idempotent: core calls
:func:`get_registry` at the few seams that consult plugins (provider
creation, benchmark lookup, MCP tool listing/dispatch). A broken plugin is
reported to stderr and skipped — it never takes KAOS down.

Hooks
-----
- ``add_provider(name, factory)`` — model providers for the GEPA router;
  ``factory(**model_kwargs) -> LLMProvider``.
- ``add_benchmark(name, cls)`` — meta-harness benchmarks.
- ``add_mcp_tools(tools, dispatcher)`` — extra MCP tools; ``tools`` is a
  list of dicts (``name`` / ``description`` / ``input_schema``) so plugins
  don't need the ``mcp`` package to declare them;
  ``dispatcher(name, arguments) -> str``.
- ``add_fleet_adapter(name, factory)`` — external-fleet attach adapters
  (herdr, tmux, ...); reserved for the v2.x ``kaos fleet`` surface.
- ``add_dream_phase(name, fn)`` — extra dream-cycle phases; reserved.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

ENTRY_POINT_GROUP = "kaos.plugins"


@dataclass
class McpToolPack:
    plugin: str
    tools: list[dict[str, Any]]
    dispatcher: Callable[[str, dict[str, Any]], str]


@dataclass
class PluginRegistry:
    """What plugins have contributed. One instance per process."""

    providers: dict[str, Callable[..., Any]] = field(default_factory=dict)
    benchmarks: dict[str, type] = field(default_factory=dict)
    mcp_tool_packs: list[McpToolPack] = field(default_factory=list)
    fleet_adapters: dict[str, Callable[..., Any]] = field(default_factory=dict)
    dream_phases: dict[str, Callable[..., Any]] = field(default_factory=dict)
    loaded: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    _current: str = ""

    # ── hooks (called by plugins' register()) ──────────────────────────
    def add_provider(self, name: str, factory: Callable[..., Any]) -> None:
        self.providers[name] = factory

    def add_benchmark(self, name: str, cls: type) -> None:
        self.benchmarks[name] = cls

    def add_mcp_tools(
        self,
        tools: list[dict[str, Any]],
        dispatcher: Callable[[str, dict[str, Any]], str],
    ) -> None:
        self.mcp_tool_packs.append(
            McpToolPack(plugin=self._current, tools=tools, dispatcher=dispatcher)
        )

    def add_fleet_adapter(self, name: str, factory: Callable[..., Any]) -> None:
        self.fleet_adapters[name] = factory

    def add_dream_phase(self, name: str, fn: Callable[..., Any]) -> None:
        self.dream_phases[name] = fn


_registry: PluginRegistry | None = None


def get_registry(reload: bool = False) -> PluginRegistry:
    """Discover and load all installed plugins (idempotent)."""
    global _registry
    if _registry is not None and not reload:
        return _registry

    reg = PluginRegistry()
    try:
        from importlib.metadata import entry_points
        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # metadata backend unavailable — run pluginless
        eps = []

    for ep in eps:
        reg._current = ep.name
        try:
            target = ep.load()
            target(reg)
            reg.loaded.append(ep.name)
        except Exception as e:  # a broken plugin must never take KAOS down
            reg.errors[ep.name] = f"{type(e).__name__}: {e}"
            print(
                f"[kaos] plugin {ep.name!r} failed to load: "
                f"{type(e).__name__}: {e}",
                file=sys.stderr,
            )
        finally:
            reg._current = ""

    _registry = reg
    return reg


def ensure_probe_paths() -> None:
    """Make probe specs like ``demo_x.probe_adapter:Cls`` importable.

    Adds the working directory and its ``benchmarks/`` subdirectory (where
    the KAOS repo keeps its hash-locked bench suites since v2.0) to
    ``sys.path``. Console scripts don't get CWD on ``sys.path`` the way
    ``python -m`` does, so probe loading must not depend on it.
    """
    for p in (Path.cwd(), Path.cwd() / "benchmarks"):
        s = str(p)
        if p.is_dir() and s not in sys.path:
            sys.path.insert(0, s)
