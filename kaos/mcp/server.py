"""MCP Server — exposes KAOS as an MCP server for Claude Code integration.

Provides 17 tools covering:
- Agent lifecycle: spawn, spawn_only, kill, pause, resume, status
- Agent VFS: read, write, ls
- Checkpoints: checkpoint, restore, diff, list_checkpoints
- Query: SQL read-only queries
- Orchestration: parallel execution
- Meta-Harness: search, frontier, inspect
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from kaos.core import Kaos
from kaos.ccr.runner import ClaudeCodeRunner
from kaos.router.gepa import GEPARouter

logger = logging.getLogger(__name__)

# Module-level references set during server initialization
_afs: Kaos | None = None
_ccr: ClaudeCodeRunner | None = None

server = Server("kaos")


def init_server(afs: Kaos, ccr: ClaudeCodeRunner) -> Server:
    """Initialize the MCP server with Kaos and CCR instances."""
    global _afs, _ccr
    _afs = afs
    _ccr = ccr
    return server


@server.list_tools()
async def list_tools() -> list[Tool]:
    """List all available Kaos tools."""
    return [
        # ── Agent Lifecycle ──────────────────────────────────────
        Tool(
            name="agent_spawn",
            description="Spawn a new agent with an isolated virtual filesystem and run a task",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the agent"},
                    "task": {"type": "string", "description": "Task description for the agent to execute"},
                    "config": {"type": "object", "description": "Agent configuration (model, temperature, etc.)", "default": {}},
                },
                "required": ["name", "task"],
            },
        ),
        Tool(
            name="agent_spawn_only",
            description="Spawn a new agent without running it (returns agent_id for later use)",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name for the agent"},
                    "config": {"type": "object", "description": "Agent configuration", "default": {}},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="agent_kill",
            description="Kill a running agent",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID to kill"},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_pause",
            description="Pause a running agent (can be resumed later)",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID to pause"},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_resume",
            description="Resume a paused agent",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID to resume"},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_status",
            description="Get status of one agent or list all agents. Omit agent_id to list all.",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID (omit for all agents)"},
                    "status_filter": {"type": "string", "description": "Filter by status (running, completed, failed, paused, killed)"},
                },
            },
        ),
        # ── Agent VFS ────────────────────────────────────────────
        Tool(
            name="agent_read",
            description="Read a file from an agent's virtual filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "path": {"type": "string", "description": "File path to read"},
                },
                "required": ["agent_id", "path"],
            },
        ),
        Tool(
            name="agent_write",
            description="Write a file to an agent's virtual filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["agent_id", "path", "content"],
            },
        ),
        Tool(
            name="agent_ls",
            description="List files in an agent's virtual filesystem",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "path": {"type": "string", "description": "Directory path", "default": "/"},
                },
                "required": ["agent_id"],
            },
        ),
        # ── Checkpoints ──────────────────────────────────────────
        Tool(
            name="agent_checkpoint",
            description="Create a snapshot of an agent's current state (files + KV store)",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "label": {"type": "string", "description": "Optional label for the checkpoint"},
                },
                "required": ["agent_id"],
            },
        ),
        Tool(
            name="agent_restore",
            description="Restore an agent to a previous checkpoint",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "checkpoint_id": {"type": "string", "description": "Checkpoint ID to restore"},
                },
                "required": ["agent_id", "checkpoint_id"],
            },
        ),
        Tool(
            name="agent_diff",
            description="Compare two checkpoints — shows file changes, state changes, and tool calls between them",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                    "from_checkpoint": {"type": "string", "description": "Source checkpoint ID"},
                    "to_checkpoint": {"type": "string", "description": "Target checkpoint ID"},
                },
                "required": ["agent_id", "from_checkpoint", "to_checkpoint"],
            },
        ),
        Tool(
            name="agent_checkpoints",
            description="List all checkpoints for an agent",
            inputSchema={
                "type": "object",
                "properties": {
                    "agent_id": {"type": "string", "description": "Agent ID"},
                },
                "required": ["agent_id"],
            },
        ),
        # ── Query ────────────────────────────────────────────────
        Tool(
            name="agent_query",
            description="Run a read-only SQL query against the agent database (SELECT only)",
            inputSchema={
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SQL SELECT query"},
                },
                "required": ["sql"],
            },
        ),
        # ── Orchestration ────────────────────────────────────────
        Tool(
            name="agent_parallel",
            description="Spawn and run multiple agents in parallel, each with its own isolated VFS",
            inputSchema={
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "prompt": {"type": "string"},
                                "config": {"type": "object", "default": {}},
                            },
                            "required": ["name", "prompt"],
                        },
                        "description": "List of tasks to run in parallel",
                    },
                },
                "required": ["tasks"],
            },
        ),
        # ── Meta-Harness ────────────────────────────────────────
        Tool(
            name="mh_search",
            description="Run a Meta-Harness search to automatically optimize a harness for a benchmark. Returns the Pareto frontier of best harnesses.",
            inputSchema={
                "type": "object",
                "properties": {
                    "benchmark": {
                        "type": "string",
                        "description": "Benchmark name: text_classify, math_rag, agentic_coding, or a custom registered benchmark",
                    },
                    "max_iterations": {"type": "integer", "description": "Number of search iterations", "default": 10},
                    "candidates_per_iteration": {"type": "integer", "description": "Candidates proposed per iteration", "default": 2},
                    "config": {"type": "object", "description": "Additional SearchConfig overrides", "default": {}},
                },
                "required": ["benchmark"],
            },
        ),
        Tool(
            name="mh_frontier",
            description="Get the Pareto frontier of a Meta-Harness search — the best harnesses found",
            inputSchema={
                "type": "object",
                "properties": {
                    "search_agent_id": {"type": "string", "description": "Search agent ID from mh_search"},
                },
                "required": ["search_agent_id"],
            },
        ),
        Tool(
            name="mh_resume",
            description="Resume an interrupted Meta-Harness search from its last completed iteration. Restores all prior results and continues the search loop.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search_agent_id": {"type": "string", "description": "Search agent ID to resume"},
                    "benchmark": {"type": "string", "description": "Benchmark name (must match original search)"},
                },
                "required": ["search_agent_id", "benchmark"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle MCP tool calls."""
    assert _afs is not None, "Server not initialized — call init_server() first"

    try:
        result = await _dispatch(name, arguments)
        return [TextContent(type="text", text=result)]
    except Exception as e:
        logger.exception("Tool call failed: %s", name)
        return [TextContent(type="text", text=f"Error: {type(e).__name__}: {e}")]


def _import_benchmarks() -> None:
    """Import all benchmark modules to trigger registration."""
    import kaos.metaharness.benchmarks.text_classify  # noqa: F401
    import kaos.metaharness.benchmarks.math_rag  # noqa: F401
    import kaos.metaharness.benchmarks.agentic_coding  # noqa: F401
    try:
        import kaos.metaharness.benchmarks.arc_agi3  # noqa: F401
    except ImportError:
        pass


async def _dispatch(name: str, args: dict[str, Any]) -> str:
    """Dispatch a tool call to the appropriate handler."""
    assert _afs is not None
    assert _ccr is not None

    # ── Agent Lifecycle ──────────────────────────────────────
    if name == "agent_spawn":
        agent_id = _afs.spawn(name=args["name"], config=args.get("config", {}))
        result = await _ccr.run_agent(agent_id, args["task"])
        return json.dumps({"agent_id": agent_id, "result": result}, indent=2)

    elif name == "agent_spawn_only":
        agent_id = _afs.spawn(name=args["name"], config=args.get("config", {}))
        return json.dumps({"agent_id": agent_id, "status": "initialized"}, indent=2)

    elif name == "agent_kill":
        _afs.kill(args["agent_id"])
        return f"Agent {args['agent_id']} killed"

    elif name == "agent_pause":
        _afs.pause(args["agent_id"])
        return f"Agent {args['agent_id']} paused"

    elif name == "agent_resume":
        _afs.resume(args["agent_id"])
        return f"Agent {args['agent_id']} resumed"

    elif name == "agent_status":
        if args.get("agent_id"):
            return json.dumps(_afs.status(args["agent_id"]), indent=2)
        return json.dumps(
            _afs.list_agents(status_filter=args.get("status_filter")), indent=2
        )

    # ── Agent VFS ────────────────────────────────────────────
    elif name == "agent_read":
        content = _afs.read(args["agent_id"], args["path"])
        return content.decode("utf-8", errors="replace")

    elif name == "agent_write":
        _afs.write(args["agent_id"], args["path"], args["content"].encode())
        return f"Written {len(args['content'])} bytes to {args['agent_id']}:{args['path']}"

    elif name == "agent_ls":
        entries = _afs.ls(args["agent_id"], args.get("path", "/"))
        return json.dumps(entries, indent=2)

    # ── Checkpoints ──────────────────────────────────────────
    elif name == "agent_checkpoint":
        cp_id = _afs.checkpoint(args["agent_id"], label=args.get("label"))
        return f"Checkpoint {cp_id} created for agent {args['agent_id']}"

    elif name == "agent_restore":
        _afs.restore(args["agent_id"], args["checkpoint_id"])
        return f"Agent {args['agent_id']} restored to checkpoint {args['checkpoint_id']}"

    elif name == "agent_diff":
        diff = _afs.diff_checkpoints(
            args["agent_id"], args["from_checkpoint"], args["to_checkpoint"]
        )
        return json.dumps(diff, indent=2)

    elif name == "agent_checkpoints":
        checkpoints = _afs.list_checkpoints(args["agent_id"])
        return json.dumps(checkpoints, indent=2)

    # ── Query ────────────────────────────────────────────────
    elif name == "agent_query":
        results = _afs.query(args["sql"])
        return json.dumps(results, indent=2)

    # ── Orchestration ────────────────────────────────────────
    elif name == "agent_parallel":
        results = await _ccr.run_parallel(args["tasks"])
        return json.dumps(
            [{"index": i, "result": r} for i, r in enumerate(results)],
            indent=2,
        )

    # ── Meta-Harness ────────────────────────────────────────
    elif name == "mh_search":
        from kaos.metaharness.harness import SearchConfig
        from kaos.metaharness.search import MetaHarnessSearch
        from kaos.metaharness.benchmarks import get_benchmark
        _import_benchmarks()

        benchmark_name = args["benchmark"]
        bench = get_benchmark(benchmark_name)

        extra = args.get("config", {})
        config = SearchConfig(
            benchmark=benchmark_name,
            max_iterations=args.get("max_iterations", 10),
            candidates_per_iteration=args.get("candidates_per_iteration", 2),
            **{k: v for k, v in extra.items() if k in SearchConfig.__dataclass_fields__},
        )

        search = MetaHarnessSearch(_afs, _ccr.router, bench, config)

        # Always run in background — search takes minutes to hours.
        # Returns the search_agent_id immediately; poll with mh_frontier.
        import asyncio as _asyncio
        search_agent_id = search._init_archive()

        async def _bg_search():
            try:
                # Point search at the pre-created archive agent and run the
                # full loop (seeds → proposer → eval → Pareto, with
                # checkpointing, eval_subset, error handling — all in search.run)
                search.search_agent_id = search_agent_id
                search._init_archive = lambda: search_agent_id
                await search.run()
            except Exception as exc:
                logger.exception("Background mh_search failed: %s", exc)
                try:
                    _afs.fail(search_agent_id, error=str(exc))
                except Exception:
                    pass

        _asyncio.create_task(_bg_search())
        return json.dumps({
            "search_agent_id": search_agent_id,
            "status": "running",
            "message": (
                "Search started in background. "
                f"Poll with agent_status(agent_id='{search_agent_id}') or "
                f"mh_frontier(search_agent_id='{search_agent_id}')."
            ),
        }, indent=2)

    elif name == "mh_frontier":
        search_agent_id = args["search_agent_id"]
        info = _afs.status(search_agent_id)
        iteration = _afs.get_state_or(search_agent_id, "current_iteration", 0)

        # Build a rich status response
        result: dict[str, Any] = {
            "search_agent_id": search_agent_id,
            "status": info["status"],
            "current_iteration": iteration,
        }

        # Frontier data (may not exist yet if seeds are still evaluating)
        try:
            frontier = json.loads(
                _afs.read(search_agent_id, "/pareto/frontier.json").decode()
            )
            result["frontier"] = frontier
        except FileNotFoundError:
            result["frontier"] = None
            result["message"] = "Frontier not yet computed — seeds may still be evaluating."

        # Count harnesses evaluated so far
        harness_dirs = _afs.ls(search_agent_id, "/harnesses")
        result["harnesses_evaluated"] = len(harness_dirs)

        return json.dumps(result, indent=2)

    elif name == "mh_resume":
        from kaos.metaharness.search import MetaHarnessSearch
        from kaos.metaharness.harness import SearchConfig
        from kaos.metaharness.benchmarks import get_benchmark
        _import_benchmarks()

        search_agent_id = args["search_agent_id"]
        benchmark_name = args["benchmark"]
        bench = get_benchmark(benchmark_name)

        config = SearchConfig(benchmark=benchmark_name)
        search = MetaHarnessSearch(_afs, _ccr.router, bench, config)

        import asyncio as _asyncio

        async def _bg_resume():
            try:
                await search.resume(search_agent_id)
            except Exception as exc:
                logger.exception("Background mh_resume failed: %s", exc)
                try:
                    _afs.fail(search_agent_id, error=str(exc))
                except Exception:
                    pass

        _asyncio.create_task(_bg_resume())
        return json.dumps({
            "search_agent_id": search_agent_id,
            "status": "resuming",
            "message": (
                "Search resuming in background. "
                f"Poll with mh_frontier(search_agent_id='{search_agent_id}')."
            ),
        }, indent=2)

    else:
        raise ValueError(f"Unknown tool: {name}")
