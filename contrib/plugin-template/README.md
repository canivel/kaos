# kaos-plugin-example — the KAOS plugin template

Copy this directory, rename it, publish it as `kaos-plugin-<name>`. KAOS finds it
through the `kaos.plugins` entry point; **no change to KAOS core is needed**.

```
contrib/plugin-template/
├── pyproject.toml                        # entry point: example = "kaos_plugin_example:register"
├── src/kaos_plugin_example/__init__.py   # register() adds a provider + an MCP tool
└── tests/test_plugin.py
```

## Try it

```bash
uv pip install -e contrib/plugin-template      # from the KAOS repo, or pip install -e .
uv run kaos plugins                            # "loaded": ["example"], providers: ["echo"], mcp_tools: [...]
uv run python -m pytest contrib/plugin-template/tests -q
```

Use the provider in `kaos.yaml` like any built-in one:

```yaml
models:
  echo:
    provider: echo          # the name you passed to add_provider
    model_id: echo
    use_for: [trivial]
```

The tool pack shows up in `kaos serve` (MCP) next to the built-in tools.

## Make it yours

1. Rename `src/kaos_plugin_example` → `src/kaos_plugin_<name>` and update
   `[project] name`, the `[tool.hatch...] packages` path and the entry point
   `<name> = "kaos_plugin_<name>:register"` in `pyproject.toml`.
2. In `register(registry)` call whichever hooks you need
   (see `kaos/plugins.py` for the full list):
   - `add_provider(name, factory)` — `factory(**model_kwargs) -> LLMProvider`
   - `add_benchmark(name, cls)` — a meta-harness benchmark
   - `add_mcp_tools(tools, dispatcher)` — tools as plain dicts, `dispatcher(name, args) -> str`
   - `add_fleet_adapter(name, factory)`, `add_dream_phase(name, fn)` — reserved surfaces
3. Keep `register` cheap and side-effect free. Import heavy or optional
   dependencies *inside* the factory, not at module import time — a plugin
   that raises during `register` is skipped with a message and never breaks
   `kaos`.
4. `uv build && uv publish`. Users install with `pip install kaos-plugin-<name>`.

The kill-gate discipline described in `CONTRIBUTING.md` applies to KAOS core
mechanisms; a community plugin only needs tests. If your plugin *claims a
measured improvement*, a pre-registered probe is how to make that claim
credible — `kaos eval probe --help`.

MIT, like KAOS.
