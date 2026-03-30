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


@click.group()
@click.version_option(version="0.1.0", prog_name="kaos")
def cli():
    """KAOS — Kernel for Agent Orchestration & Sandboxing.

    Every agent gets an isolated, auditable, portable virtual
    filesystem backed by SQLite. Embrace the KAOS.
    """
    pass


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
def list_agents(db: str, status: str):
    """List all agents."""
    afs = _get_afs(db)
    agents = afs.list_agents(status_filter=status)

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
def query(sql: str, db: str):
    """Run a read-only SQL query against the agent database."""
    afs = _get_afs(db)
    try:
        results = afs.query(sql)
        if results:
            # Auto-format as table
            table = Table()
            for col in results[0].keys():
                table.add_column(col)
            for row in results:
                table.add_row(*[str(v)[:80] for v in row.values()])
            console.print(table)
        else:
            console.print("[dim]No results[/dim]")
    except PermissionError as e:
        console.print(f"[red]{e}[/red]")
    except Exception as e:
        console.print(f"[red]Query error: {e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--label", "-l", help="Optional checkpoint label")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def checkpoint(agent_id: str, label: str, db: str):
    """Create a checkpoint for an agent."""
    afs = _get_afs(db)
    try:
        cp_id = afs.checkpoint(agent_id, label=label)
        console.print(f"[green]Checkpoint created:[/green] {cp_id}")
        if label:
            console.print(f"  Label: {label}")
    except ValueError as e:
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
def checkpoints(agent_id: str, db: str):
    """List all checkpoints for an agent."""
    afs = _get_afs(db)
    cps = afs.list_checkpoints(agent_id)

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

    if Path(config_file).exists():
        router = GEPARouter.from_config(config_file)
    else:
        console.print(f"[yellow]Config not found, using defaults[/yellow]")
        from kaos.router.gepa import ModelConfig
        router = GEPARouter(
            models={"default": ModelConfig(
                name="default",
                vllm_endpoint="http://localhost:8000/v1",
            )},
        )

    ccr = ClaudeCodeRunner(afs, router)
    mcp_server = init_server(afs, ccr)

    console.print(f"[green]Starting KAOS MCP server ({transport})...[/green]")

    if transport == "stdio":
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
def kill(agent_id: str, db: str):
    """Kill a running agent."""
    afs = _get_afs(db)
    try:
        afs.kill(agent_id)
        console.print(f"[red]Agent {agent_id[:12]}... killed[/red]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command()
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
def status(agent_id: str, db: str):
    """Get detailed status of an agent."""
    afs = _get_afs(db)
    try:
        info = afs.status(agent_id)
        console.print_json(json.dumps(info, indent=2))
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


if __name__ == "__main__":
    cli()
