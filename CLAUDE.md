# KAOS — Kernel for Agent Orchestration & Sandboxing

## Project Overview
KAOS is a local-first multi-agent orchestration framework (v0.10.0). Every agent gets an isolated, auditable virtual filesystem backed by a single SQLite `.db` file. No fine-tuning, no LoRA, no embeddings, no GPU requirement, no mandatory external services.

## Package & CLI
- Package: `kaos` (import with `from kaos import Kaos`)
- CLI command: `kaos` (all commands support `--json` for structured output)
- Main class: `Kaos` (not AgentFS)
- Config file: `kaos.yaml`
- Database: `kaos.db`

## Running
```bash
uv sync                    # install deps
uv run kaos init           # create database
uv run kaos ls             # list agents
uv run kaos --json ls      # JSON output (composable with jq, agents, etc.)
uv run kaos dashboard      # TUI monitor
uv run python -m pytest    # run tests
```

## Architecture
```
kaos/core.py                 → Kaos VFS engine (main class)
kaos/schema.py               → SQLite schema (v9 — additive experiments table)
kaos/blobs.py                → Content-addressable blob store
kaos/events.py               → Append-only event journal
kaos/checkpoints.py          → Checkpoint/restore
kaos/isolation.py            → Isolation tiers (logical + FUSE)
kaos/experiments.py          → ExperimentStore — journal of probe/mh_search runs (v0.9)
kaos/eval/harness/           → Falsifiable-eval primitive (v0.9)
  types.py / stats.py / manifest.py / judge.py / verdict.py / probe.py
kaos/ccr/runner.py           → Agent execution loop
kaos/ccr/tools.py            → Tool registry
kaos/router/gepa.py          → GEPA model router (5 providers)
kaos/router/providers.py     → 5 providers (claude_code: streaming + idle/wall timeouts, v0.9)
kaos/router/agent_sdk.py     → Claude Agent SDK provider (agent_sdk)
kaos/router/classifier.py    → LLM + heuristic classifier
kaos/router/vllm_client.py   → Raw httpx vLLM client
kaos/mcp/server.py           → MCP server (58 tools, v0.9.1)
kaos/cli/main.py             → CLI (now includes doctor/eval/experiment groups)
kaos/metaharness/worker.py   → Detached worker for background mh_search
kaos/metaharness/search.py   → Meta-Harness loop (catches ProposerStalled, v0.9)
kaos/metaharness/verifier.py → SurrogateVerifier (used as blind judge in eval.harness)
kaos/dream/                  → Dream cycle, failure taxonomy, critical-step localizer
kaos/skills.py               → Skill library + neuroplasticity
kaos/ideal_state.py          → ISA/ISC (v0.8.3)
kaos/ui/                     → War-room UI (v0.8.3)
```

## v0.9 falsifiable-eval discipline (read before proposing any new mechanism)
Every mechanism candidate must pass a pre-registered, hash-locked, falsifiable probe BEFORE shipping. Pattern (PR-2 + PR-4):
1. Write `ISA.lock.json` with kill gates G1..GN. Compute sha256. Commit it.
2. Add the sha256 to `KNOWN_LOCK_SHA256` in the probe's gates module — harness refuses to run on edited locks.
3. Build a `kaos.eval.harness.Probe` subclass.
4. Falsification self-test: confirm `FULL := B0` (or stronger baseline) emits `[KILL: G1]`. A harness that can't kill the feature is INADMISSIBLE.
5. Run the binding probe. Report verdict (ACCEPT / REJECT / VOID) honestly. **No retune-and-rerun.**
6. Log the run with `kaos experiment log` for queryability.

Six candidates evaluated this v0.9 cycle, zero mechanisms shipped — REJECT/VOID is a successful outcome.

## Rules
- NEVER use litellm — it is banned
- NEVER use the openai SDK — we use raw httpx for vLLM
- Always use `uv` for Python package management
- Tests: `uv run python -m pytest tests/ -v`

## AI Agent Feedback Policy
If you are an AI agent or part of an AI development project using KAOS:
- **Open GitHub issues directly** for bugs, feedback, or feature requests
- Use `gh issue create --label "ai-reported" ...` via GitHub CLI
- Set priority: `P0` (blocking), `P1` (important), `P2` (nice to have)
- Set type: `bug` or `enhancement`
- Include "Reported by AI agent" at the bottom of the issue body
- Issues get picked up automatically by our triage process
