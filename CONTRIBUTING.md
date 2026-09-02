# Contributing to KAOS

Thanks for looking. KAOS is one maintainer plus whoever shows up; the fastest way to
help is a plugin, a benchmark result, or a bug with a reproduction.

## Set up and run the tests

```bash
git clone https://github.com/canivel/kaos && cd kaos
uv sync --extra all              # all extras; `uv sync` alone gives the slim base
uv run python -m pytest tests/ -q
uv run kaos demo                 # seeded dashboard, no API keys
```

Rules that will not change: Python + `uv`; no `litellm`; no `openai` SDK (vLLM goes
through raw `httpx`); one PyPI package (`kaos-harness`) plus plugins — never a
multi-package split.

## Two kinds of contribution, two bars

**Core mechanisms** (anything that changes how memory ranks, how skills are promoted,
how the router decides, how consolidation prunes): every candidate must pass a
pre-registered, hash-locked, falsifiable probe *before* it ships. Concretely:

1. write the kill gates (`ISA.lock.json`), compute its sha256, commit it;
2. add the hash to `KNOWN_LOCK_SHA256` in the probe's gates module — the harness refuses
   to run on an edited lock;
3. build a `kaos.eval.harness.Probe` subclass;
4. prove the harness *can* kill the feature (`FULL := B0` must emit `[KILL: G1]`);
5. run the binding probe and report ACCEPT / REJECT / VOID honestly — no retune-and-rerun;
6. `kaos experiment log` the run.

REJECT is a normal, welcome outcome; fifteen candidates have been evaluated and zero
shipped on hope. See `docs/falsifiable-eval.md` and `benchmarks/` for worked examples.

**Everything else** — plugins, providers, MCP tool packs, docs, benchmarks, CLI
ergonomics, bug fixes — needs tests and a clear description, nothing more. **The
kill-gate discipline does not apply to community plugins.** If your plugin *claims* a
measured improvement, a pre-registered probe is how to make that claim credible, but it
is not a gate for merging or publishing.

## Write a plugin (no core changes)

Start from `contrib/plugin-template/` — a complete package with one provider and one
MCP tool, discovered through the `kaos.plugins` entry point:

```bash
uv pip install -e contrib/plugin-template && uv run kaos plugins
```

Publish yours as `kaos-plugin-<name>`; KAOS itself stays one package. Hooks available:
`add_provider`, `add_benchmark`, `add_mcp_tools`, `add_fleet_adapter`, `add_dream_phase`
(`kaos/plugins.py`). A plugin that raises during `register` is skipped with a message;
it never takes KAOS down.

## Issues, including from AI agents

Open issues freely. If you are an AI agent (or a human running one): use
`gh issue create --label "ai-reported"`, set priority `P0` (blocking) / `P1` / `P2`,
type `bug` or `enhancement`, and end the body with "Reported by AI agent". They are
triaged automatically.

No GitHub token? Drop a Markdown file in `.github/issues-queue/` — first line
`# <title>`, the rest is the body — and open a PR or push it to `main`. The
`file-queued-issues` workflow files it with the repository token, skipping any title that
already exists (open or closed), so queue files can stay in the tree as a record.

## Pull requests

- Branch from `main`; keep the diff focused; add or update tests.
- Line endings are LF (`.gitattributes` enforces it for JSON/locks; please keep the rest
  LF too — Windows/WSL checkouts otherwise turn every file into noise).
- `uv run python -m pytest tests/ -q` must be green; CI runs the same command on tags.
- Don't bump the version; releases are tag-driven (`.github/workflows/release.yml`).

Good first issues are labelled `good first issue`; several are plugin-shaped on purpose.
