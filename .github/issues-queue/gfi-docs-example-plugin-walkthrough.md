# Docs: `examples/plugin_walkthrough.py` + a "Write your first plugin" page

Labels: good first issue, enhancement · Priority: P2

`contrib/plugin-template/` and `CONTRIBUTING.md` explain plugins, but there is no
runnable example under `examples/` and no page in `docs/` for them — the README's
`examples/` links are the first thing newcomers click. A doc-only task, good for a first
contribution and for someone who wants to learn the plugin surface.

**What to write**

- `examples/plugin_walkthrough.py` (≤ 60 lines, runnable with `uv run python`): build a
  `PluginRegistry` by hand, call a `register()` that adds a provider and a tool, then show
  the tool being dispatched and the provider being created through
  `kaos.router.providers.create_provider` — exactly what KAOS does at startup.
- `docs/plugins.md`: what the entry-point group is, the five hooks, the "import extras
  lazily / never raise in register" rules, how discovery is verified with `kaos plugins`,
  and publishing as `kaos-plugin-<name>`. Link it from `docs/README.md` and
  `CONTRIBUTING.md`.

**Done when** the example runs green from a clean `uv sync --extra all` and the page is
linked from the docs index.

Reported by AI agent
