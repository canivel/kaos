"""KAOS CLI — command-line interface for the Kernel for Agent Orchestration & Sandboxing."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table
from rich.text import Text

from kaos.core import Kaos

console = Console()

DEFAULT_DB = os.environ.get("KAOS_DB", "./kaos.db")
DEFAULT_CONFIG = os.environ.get("KAOS_CONFIG", "./kaos.yaml")


def _get_afs(db: str) -> Kaos:
    """Get or create an Kaos instance."""
    return Kaos(db_path=db)


def _json_out(ctx, data):
    """Output data as JSON if --json is set, otherwise return False."""
    if ctx.obj.get("json"):
        click.echo(json.dumps(data, indent=2, default=str))
        return True
    return False


def _json_err(ctx, msg: str):
    """Output error as JSON if --json is set, otherwise return False."""
    if ctx.obj.get("json"):
        click.echo(json.dumps({"error": msg}))
        ctx.exit(1)
        return True
    return False


@click.group()
@click.version_option(version="0.3.0", prog_name="kaos")
@click.option("--json", "json_output", is_flag=True, default=False,
              help="Output structured JSON (auto-enabled when piped)")
@click.pass_context
def cli(ctx, json_output):
    """KAOS — Kernel for Agent Orchestration & Sandboxing.

    Every agent gets an isolated, auditable, portable virtual
    filesystem backed by SQLite. Embrace the KAOS.
    """
    ctx.ensure_object(dict)
    ctx.obj["json"] = json_output or not sys.stdout.isatty()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def init(db: str):
    """Initialize a new Kaos database."""
    if Path(db).exists():
        console.print(f"[yellow]Database already exists:[/yellow] {db}")
        return

    afs = _get_afs(db)
    afs.close()
    console.print(f"[green]Initialized KAOS database:[/green] {db}")


@cli.command()
@click.option("-o", "--output", default="./kaos.yaml", help="Output config file path")
def setup(output: str):
    """Interactive setup wizard — configure KAOS for your project."""
    from kaos.cli.setup import run_setup
    run_setup(output_path=output)


@cli.command()
@click.argument("task")
@click.option("--name", "-n", required=True, help="Agent name")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option("--model", "-m", help="Force a specific model")
@click.option("--checkpoint-interval", default=10, help="Auto-checkpoint every N iterations")
def run(task: str, name: str, db: str, config_file: str, model: str, checkpoint_interval: int):
    """Spawn and run an agent with a task."""
    from kaos.router.gepa import GEPARouter
    from kaos.ccr.runner import ClaudeCodeRunner

    afs = _get_afs(db)

    if not Path(config_file).exists():
        console.print(f"[red]Config file not found:[/red] {config_file}")
        console.print("Run: cp kaos.yaml.example kaos.yaml")
        return

    router = GEPARouter.from_config(config_file)
    ccr = ClaudeCodeRunner(
        afs, router, checkpoint_interval=checkpoint_interval
    )

    agent_config = {}
    if model:
        agent_config["force_model"] = model

    agent_id = afs.spawn(name=name, config=agent_config)
    console.print(f"[cyan]Spawned agent:[/cyan] {agent_id} ({name})")

    try:
        result = asyncio.run(ccr.run_agent(agent_id, task))
        console.print(f"\n[green]Result:[/green]\n{result}")
    except Exception as e:
        console.print(f"\n[red]Agent failed:[/red] {e}")
    finally:
        afs.close()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option(
    "--task", "-t", multiple=True, nargs=2, metavar="NAME PROMPT",
    help="Task as --task NAME PROMPT (can specify multiple)"
)
def parallel(db: str, config_file: str, task: tuple):
    """Run multiple agents in parallel."""
    from kaos.router.gepa import GEPARouter
    from kaos.ccr.runner import ClaudeCodeRunner

    if not task:
        console.print("[red]No tasks specified. Use --task NAME PROMPT[/red]")
        return

    afs = _get_afs(db)
    router = GEPARouter.from_config(config_file)
    ccr = ClaudeCodeRunner(afs, router)

    tasks = [{"name": t[0], "prompt": t[1]} for t in task]

    console.print(f"[cyan]Running {len(tasks)} agents in parallel...[/cyan]")
    results = asyncio.run(ccr.run_parallel(tasks))

    for i, result in enumerate(results):
        console.print(f"\n[bold]Agent {tasks[i]['name']}:[/bold]")
        console.print(result[:500])

    afs.close()


@cli.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--status", "-s", help="Filter by status")
@click.pass_context
def list_agents(ctx, db: str, status: str):
    """List all agents."""
    afs = _get_afs(db)
    agents = afs.list_agents(status_filter=status)

    if _json_out(ctx, agents):
        afs.close()
        return

    if not agents:
        console.print("[dim]No agents found[/dim]")
        return

    table = Table(title="Agents")
    table.add_column("ID", style="cyan", max_width=14)
    table.add_column("Name", style="bold")
    table.add_column("Status")
    table.add_column("Created")

    for agent in agents:
        status_text = Text(agent["status"])
        if agent["status"] == "running":
            status_text.stylize("bold green")
        elif agent["status"] == "completed":
            status_text.stylize("green")
        elif agent["status"] in ("failed", "killed"):
            status_text.stylize("red")

        table.add_row(
            agent["agent_id"][:12] + "...",
            agent["name"],
            status_text,
            agent["created_at"][:19] if agent["created_at"] else "",
        )

    console.print(table)
    afs.close()


@cli.command()
@click.argument("sql")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def query(ctx, sql: str, db: str):
    """Run a read-only SQL query against the agent database."""
    afs = _get_afs(db)
    try:
        results = afs.query(sql)
        if _json_out(ctx, results):
            return
        if results:
            table = Table()
            for col in results[0].keys():
                table.add_column(col)
            for row in results:
                table.add_row(*[str(v)[:80] for v in row.values()])
            console.print(table)
        else:
            console.print("[dim]No results[/dim]")
    except PermissionError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    except Exception as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]Query error: {e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--label", "-l", help="Optional checkpoint label")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def checkpoint(ctx, agent_id: str, label: str, db: str):
    """Create a checkpoint for an agent."""
    afs = _get_afs(db)
    try:
        cp_id = afs.checkpoint(agent_id, label=label)
        if _json_out(ctx, {"checkpoint_id": cp_id, "agent_id": agent_id, "label": label}):
            return
        console.print(f"[green]Checkpoint created:[/green] {cp_id}")
        if label:
            console.print(f"  Label: {label}")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--checkpoint", "checkpoint_id", required=True, help="Checkpoint ID to restore")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def restore(agent_id: str, checkpoint_id: str, db: str):
    """Restore an agent to a previous checkpoint."""
    afs = _get_afs(db)
    try:
        afs.restore(agent_id, checkpoint_id)
        console.print(f"[green]Agent {agent_id} restored to checkpoint {checkpoint_id}[/green]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--from", "from_cp", required=True, help="Source checkpoint ID")
@click.option("--to", "to_cp", required=True, help="Target checkpoint ID")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def diff(agent_id: str, from_cp: str, to_cp: str, db: str):
    """Compare two checkpoints of an agent."""
    from kaos.cli.diff import render_diff

    afs = _get_afs(db)
    try:
        result = afs.diff_checkpoints(agent_id, from_cp, to_cp)
        render_diff(result, console)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def checkpoints(ctx, agent_id: str, db: str):
    """List all checkpoints for an agent."""
    afs = _get_afs(db)
    cps = afs.list_checkpoints(agent_id)

    if _json_out(ctx, cps):
        afs.close()
        return

    if not cps:
        console.print("[dim]No checkpoints found[/dim]")
        return

    table = Table(title=f"Checkpoints for {agent_id[:12]}...")
    table.add_column("ID", style="cyan", max_width=14)
    table.add_column("Label")
    table.add_column("Created")
    table.add_column("Event ID", justify="right")

    for cp in cps:
        table.add_row(
            cp["checkpoint_id"][:12] + "...",
            cp.get("label") or "-",
            cp["created_at"][:19],
            str(cp.get("event_id") or "-"),
        )

    console.print(table)
    afs.close()


@cli.command("export")
@click.argument("agent_id")
@click.option("-o", "--output", required=True, help="Output file path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def export_agent(agent_id: str, output: str, db: str):
    """Export an agent to a standalone database file."""
    import shutil
    import sqlite3

    afs = _get_afs(db)

    # Verify agent exists
    try:
        afs.status(agent_id)
    except ValueError:
        console.print(f"[red]Agent not found: {agent_id}[/red]")
        return

    # Create a new database with just this agent's data
    shutil.copy2(db, output)

    # Remove other agents from the copy
    export_conn = sqlite3.connect(output)
    other_agents = export_conn.execute(
        "SELECT agent_id FROM agents WHERE agent_id != ?", (agent_id,)
    ).fetchall()

    for (other_id,) in other_agents:
        for table in ("files", "tool_calls", "state", "events", "checkpoints"):
            export_conn.execute(f"DELETE FROM {table} WHERE agent_id = ?", (other_id,))
        export_conn.execute("DELETE FROM agents WHERE agent_id = ?", (other_id,))

    # Clean up orphaned blobs
    export_conn.execute(
        "DELETE FROM blobs WHERE content_hash NOT IN (SELECT content_hash FROM files WHERE content_hash IS NOT NULL)"
    )
    export_conn.execute("VACUUM")
    export_conn.commit()
    export_conn.close()

    console.print(f"[green]Exported agent {agent_id[:12]}... to {output}[/green]")
    afs.close()


@cli.command("import")
@click.argument("file_path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--merge/--replace", default=True, help="Merge or replace existing data")
def import_agent(file_path: str, db: str, merge: bool):
    """Import an agent from a standalone database file."""
    import sqlite3

    if not Path(file_path).exists():
        console.print(f"[red]File not found: {file_path}[/red]")
        return

    afs = _get_afs(db)
    source = sqlite3.connect(file_path)

    agents = source.execute("SELECT agent_id, name FROM agents").fetchall()
    for agent_id, name in agents:
        console.print(f"[cyan]Importing agent:[/cyan] {agent_id[:12]}... ({name})")

    # Attach source database
    afs.conn.execute(f"ATTACH DATABASE '{file_path}' AS import_db")

    try:
        for table in ("agents", "blobs", "files", "tool_calls", "state", "events", "checkpoints"):
            afs.conn.execute(f"INSERT OR IGNORE INTO {table} SELECT * FROM import_db.{table}")
        afs.conn.commit()
        console.print(f"[green]Import complete — {len(agents)} agent(s) imported[/green]")
    except Exception as e:
        console.print(f"[red]Import failed: {e}[/red]")
    finally:
        afs.conn.execute("DETACH DATABASE import_db")
        source.close()
        afs.close()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--port", default=3100, help="MCP server port")
@click.option("--host", default="127.0.0.1", help="MCP server host")
@click.option("--transport", default="stdio", type=click.Choice(["stdio", "sse"]), help="Transport")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
def serve(db: str, port: int, host: str, transport: str, config_file: str):
    """Start the Kaos MCP server."""
    from kaos.mcp.server import init_server
    from kaos.router.gepa import GEPARouter
    from kaos.ccr.runner import ClaudeCodeRunner

    afs = _get_afs(db)

    # Try config file first, then fall back to claude_code provider (no API key needed)
    _cfg_paths = [config_file, os.environ.get("KAOS_CONFIG", ""), "./kaos.yaml"]
    _loaded = False
    for _cfg in _cfg_paths:
        if _cfg and Path(_cfg).exists():
            router = GEPARouter.from_config(_cfg)
            _loaded = True
            break

    if not _loaded:
        # Default: use claude_code provider (Claude Code subscription, no API key)
        from kaos.router.gepa import ModelConfig
        from kaos.router.providers import ClaudeCodeProvider
        _provider = ClaudeCodeProvider(model_id="claude-sonnet-4-6")
        from kaos.router.gepa import GEPARouter as _GR
        router = _GR(
            models={"claude-sonnet": ModelConfig(
                name="claude-sonnet",
                provider="claude_code",
                model_id="claude-sonnet-4-6",
                use_for=["trivial", "moderate", "complex", "critical"],
            )},
        )
        # Inject the provider directly since GEPARouter.__init__ creates it from config
        router.clients["claude-sonnet"] = _provider

    ccr = ClaudeCodeRunner(afs, router)
    mcp_server = init_server(afs, ccr)

    console.print(f"[green]Starting KAOS MCP server ({transport})...[/green]")

    if transport == "stdio":
        # Redirect stdout → stderr so any library logging to stdout
        # (e.g., benchmark modules, print statements) doesn't corrupt
        # the MCP JSON-RPC stdio protocol. The MCP library uses its own
        # write stream from stdio_server(), not sys.stdout.
        sys.stdout = sys.stderr
        from mcp.server.stdio import stdio_server
        asyncio.run(_run_stdio(mcp_server))
    else:
        console.print(f"[cyan]Listening on {host}:{port}[/cyan]")
        from mcp.server.sse import SseServerTransport
        asyncio.run(_run_sse(mcp_server, host, port))


async def _run_stdio(mcp_server):
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read, write):
        await mcp_server.run(read, write, mcp_server.create_initialization_options())


async def _run_sse(mcp_server, host: str, port: int):
    from mcp.server.sse import SseServerTransport
    from starlette.applications import Starlette
    from starlette.routing import Route
    import uvicorn

    sse = SseServerTransport("/messages")

    async def handle_sse(request):
        async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
            await mcp_server.run(
                streams[0], streams[1], mcp_server.create_initialization_options()
            )

    app = Starlette(routes=[
        Route("/sse", endpoint=handle_sse),
        Route("/messages", endpoint=sse.handle_post_message, methods=["POST"]),
    ])

    config = uvicorn.Config(app, host=host, port=port)
    server = uvicorn.Server(config)
    await server.serve()


@cli.command()
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def dashboard(db: str):
    """Launch the TUI dashboard for real-time agent monitoring."""
    from kaos.cli.dashboard import KaosDashboard

    afs = _get_afs(db)
    app = KaosDashboard(afs)
    app.run()
    afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def kill(ctx, agent_id: str, db: str):
    """Kill a running agent."""
    afs = _get_afs(db)
    try:
        afs.kill(agent_id)
        if _json_out(ctx, {"agent_id": agent_id, "status": "killed"}):
            return
        console.print(f"[red]Agent {agent_id[:12]}... killed[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def status(ctx, agent_id: str, db: str):
    """Get detailed status of an agent."""
    afs = _get_afs(db)
    try:
        info = afs.status(agent_id)
        if _json_out(ctx, info):
            return
        console.print_json(json.dumps(info, indent=2))
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


# ── Meta-Harness Commands ────────────────────────────────────────


@cli.group()
def mh():
    """Meta-Harness — automated harness optimization."""
    pass


@mh.command("search")
@click.option("--benchmark", "-b", required=True,
              type=click.Choice(["text_classify", "math_rag", "agentic_coding"]),
              help="Benchmark to optimize for")
@click.option("--iterations", "-n", default=20, help="Number of search iterations")
@click.option("--candidates", "-k", default=3, help="Candidates per iteration")
@click.option("--seed", "-s", multiple=True, help="Seed harness file paths")
@click.option("--proposer-model", help="Force model for proposer agent")
@click.option("--eval-model", help="Force model for evaluation")
@click.option("--max-parallel", default=4, help="Max parallel evaluations")
@click.option("--eval-subset", type=int, help="Subsample problems for faster search")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
@click.option("--background/--foreground", default=False, help="Run as detached background process")
@click.option("--dry-run", is_flag=True, default=False, help="Evaluate seeds only, report baseline scores")
@click.pass_context
def mh_search(ctx, benchmark, iterations, candidates, seed, proposer_model,
              eval_model, max_parallel, eval_subset, db, config_file, background, dry_run):
    """Run a meta-harness search to optimize a harness for a benchmark."""
    import subprocess as _sp

    if not Path(config_file).exists():
        if not _json_err(ctx, f"Config file not found: {config_file}"):
            console.print(f"[red]Config file not found:[/red] {config_file}")
        return

    if background:
        # Launch as detached worker process
        cmd = [
            sys.executable, "-m", "kaos.metaharness.worker",
            "--db", db,
            "--config-file", config_file,
            "--benchmark", benchmark,
            "--iterations", str(iterations),
            "--candidates", str(candidates),
            "--max-parallel", str(max_parallel),
        ]
        if eval_subset:
            cmd += ["--eval-subset", str(eval_subset)]
        if proposer_model:
            cmd += ["--proposer-model", proposer_model]
        for s in seed:
            cmd += ["--seed", s]

        kwargs: dict = {}
        if sys.platform == "win32":
            kwargs["creationflags"] = (
                _sp.CREATE_NEW_PROCESS_GROUP | _sp.DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True

        import time as _time
        log_path = os.path.join(os.path.dirname(os.path.abspath(db)), f"kaos-worker-{int(_time.time())}.log")
        log_file = open(log_path, "w")
        proc = _sp.Popen(cmd, stdout=log_file, stderr=log_file, **kwargs)

        result = {
            "status": "running",
            "pid": proc.pid,
            "log_path": log_path,
            "message": f"Worker launched (PID {proc.pid}). Log: {log_path}",
        }
        if _json_out(ctx, result):
            return
        console.print(f"[green]Worker launched[/green] (PID {proc.pid})")
        console.print(f"  Log: {log_path}")
        console.print(f"  Poll with: kaos mh status <search_agent_id>")
        return

    # Foreground mode — run in-process
    from kaos.metaharness.search import MetaHarnessSearch
    from kaos.metaharness.harness import SearchConfig
    from kaos.metaharness.benchmarks import get_benchmark
    import kaos.metaharness.benchmarks.text_classify  # noqa: F401
    import kaos.metaharness.benchmarks.math_rag  # noqa: F401
    import kaos.metaharness.benchmarks.agentic_coding  # noqa: F401
    from kaos.router.gepa import GEPARouter

    afs = _get_afs(db)
    router = GEPARouter.from_config(config_file)

    config = SearchConfig(
        benchmark=benchmark,
        max_iterations=iterations,
        candidates_per_iteration=candidates,
        seed_harnesses=list(seed),
        proposer_model=proposer_model,
        evaluator_model=eval_model,
        max_parallel_evals=max_parallel,
        eval_subset_size=eval_subset,
    )

    bench = get_benchmark(benchmark)

    if not ctx.obj.get("json"):
        console.print(f"[cyan]Starting meta-harness search[/cyan]")
        console.print(f"  Benchmark: {benchmark}")
        console.print(f"  Iterations: {iterations}")
        console.print(f"  Candidates/iter: {candidates}")
        console.print(f"  Max parallel: {max_parallel}")

    search = MetaHarnessSearch(afs, router, bench, config)
    if ctx.params.get("dry_run"):
        if not ctx.obj.get("json"):
            console.print("[cyan]Dry-run: evaluating seeds only[/cyan]")
        result = asyncio.run(search.run_seeds_only())
    else:
        result = asyncio.run(search.run())

    result_data = {
        "search_agent_id": result.search_agent_id,
        "status": "completed",
        "summary": result.summary(),
        "total_harnesses": result.total_harnesses_evaluated,
        "duration_seconds": round(result.total_duration_seconds, 1),
        "frontier_size": len(result.frontier.points),
    }
    if not _json_out(ctx, result_data):
        console.print(f"\n[green]{result.summary()}[/green]")
    afs.close()


@mh.command("frontier")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_frontier(ctx, search_agent_id, db):
    """Show the Pareto frontier of a meta-harness search."""
    afs = _get_afs(db)
    try:
        data = afs.read(search_agent_id, "/pareto/frontier.json")
        frontier = json.loads(data)

        if _json_out(ctx, frontier):
            return

        table = Table(title="Pareto Frontier")
        table.add_column("Harness ID", style="cyan", max_width=16)
        table.add_column("Iteration", justify="right")
        for obj in frontier.get("objectives", {}):
            table.add_column(obj.capitalize(), justify="right")

        for point in frontier.get("points", []):
            row = [point["harness_id"][:14] + "...", str(point.get("iteration", "?"))]
            for obj in frontier.get("objectives", {}):
                val = point.get("scores", {}).get(obj, 0)
                row.append(f"{val:.4f}")
            table.add_row(*row)

        console.print(table)
    except FileNotFoundError:
        if not _json_err(ctx, "No frontier found"):
            console.print("[red]No frontier found. Is this a valid search agent?[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("inspect")
@click.argument("search_agent_id")
@click.argument("harness_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def mh_inspect(search_agent_id, harness_id, db):
    """Inspect a specific harness — source, scores, and trace summary."""
    afs = _get_afs(db)
    try:
        base = f"/harnesses/{harness_id}"

        # Source
        source = afs.read(search_agent_id, f"{base}/source.py").decode()
        console.print("[bold]Source Code:[/bold]")
        console.print(source)

        # Scores
        scores = json.loads(afs.read(search_agent_id, f"{base}/scores.json"))
        console.print(f"\n[bold]Scores:[/bold]")
        for k, v in scores.items():
            console.print(f"  {k}: {v:.4f}")

        # Metadata
        meta = json.loads(afs.read(search_agent_id, f"{base}/metadata.json"))
        console.print(f"\n[bold]Metadata:[/bold]")
        console.print(f"  Iteration: {meta.get('iteration', '?')}")
        console.print(f"  Parents: {meta.get('parent_ids', [])}")
        console.print(f"  Duration: {meta.get('duration_ms', 0)}ms")
        if meta.get("metadata", {}).get("rationale"):
            console.print(f"  Rationale: {meta['metadata']['rationale'][:200]}")

        # Trace summary
        try:
            trace_data = afs.read(search_agent_id, f"{base}/trace.jsonl").decode()
            lines = [l for l in trace_data.split("\n") if l.strip()]
            console.print(f"\n[bold]Trace:[/bold] {len(lines)} entries")
            for line in lines[:10]:
                entry = json.loads(line)
                console.print(f"  {entry.get('type', '?')}: {str(entry)[:80]}")
            if len(lines) > 10:
                console.print(f"  ... and {len(lines) - 10} more")
        except FileNotFoundError:
            console.print("\n[dim]No trace available[/dim]")

    except FileNotFoundError as e:
        console.print(f"[red]Not found: {e}[/red]")
    finally:
        afs.close()


@mh.command("status")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_status(ctx, search_agent_id, db):
    """Show the status of a meta-harness search."""
    afs = _get_afs(db)
    try:
        info = afs.status(search_agent_id)
        iteration = afs.get_state_or(search_agent_id, "current_iteration", 0)
        harnesses = afs.ls(search_agent_id, "/harnesses")

        result = {
            "search_agent_id": search_agent_id,
            "status": info["status"],
            "pid": info.get("pid"),
            "current_iteration": iteration,
            "harnesses_evaluated": len(harnesses),
        }

        try:
            frontier = json.loads(
                afs.read(search_agent_id, "/pareto/frontier.json")
            )
            result["frontier_size"] = len(frontier.get("points", []))
        except FileNotFoundError:
            result["frontier_size"] = 0

        if _json_out(ctx, result):
            return

        console.print(f"[bold]Search Agent:[/bold] {search_agent_id[:14]}...")
        console.print(f"  Status: {info['status']}")
        console.print(f"  Current iteration: {iteration}")
        console.print(f"  Harnesses evaluated: {len(harnesses)}")
        console.print(f"  Frontier size: {result['frontier_size']}")

    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("resume")
@click.argument("search_agent_id")
@click.option("--benchmark", "-b", required=True,
              help="Benchmark name (must match original search)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--config-file", default=DEFAULT_CONFIG, help="Config file path")
def mh_resume(search_agent_id, benchmark, db, config_file):
    """Resume an interrupted meta-harness search from its last iteration."""
    from kaos.metaharness.search import MetaHarnessSearch
    from kaos.metaharness.harness import SearchConfig
    from kaos.metaharness.benchmarks import get_benchmark
    import kaos.metaharness.benchmarks.text_classify  # noqa: F401
    import kaos.metaharness.benchmarks.math_rag  # noqa: F401
    import kaos.metaharness.benchmarks.agentic_coding  # noqa: F401
    import kaos.metaharness.benchmarks.paper_datasets  # noqa: F401
    from kaos.router.gepa import GEPARouter

    afs = _get_afs(db)

    if not Path(config_file).exists():
        console.print(f"[red]Config file not found:[/red] {config_file}")
        return

    router = GEPARouter.from_config(config_file)
    bench = get_benchmark(benchmark)
    config = SearchConfig(benchmark=benchmark)
    search = MetaHarnessSearch(afs, router, bench, config)

    console.print(f"[cyan]Resuming search {search_agent_id[:14]}...[/cyan]")

    result = asyncio.run(search.resume(search_agent_id))

    console.print(f"\n[green]{result.summary()}[/green]")
    afs.close()


if __name__ == "__main__":
    cli()
