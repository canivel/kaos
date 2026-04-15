"""KAOS CLI — command-line interface for the Kernel for Agent Orchestration & Sandboxing."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

# Fix Windows cp1252 encoding crash — force UTF-8 for stdout/stderr
if sys.platform == "win32" and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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
@click.version_option(version="0.7.0", prog_name="kaos")
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

    if transport == "stdio":
        # The MCP protocol uses stdout for JSON-RPC responses.
        # But stray print() calls and library logging also go to stdout,
        # corrupting the protocol. Fix: redirect sys.stdout to stderr
        # for all Python code, but pass the ORIGINAL stdout to
        # stdio_server so MCP responses go to the right place.
        import io
        _original_stdout = sys.stdout
        sys.stdout = sys.stderr
        logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
        from mcp.server.stdio import stdio_server
        asyncio.run(_run_stdio(mcp_server, _original_stdout))
    else:
        console.print(f"[cyan]Listening on {host}:{port}[/cyan]")
        from mcp.server.sse import SseServerTransport
        asyncio.run(_run_sse(mcp_server, host, port))


async def _run_stdio(mcp_server, original_stdout=None):
    from mcp.server.stdio import stdio_server
    # If we redirected sys.stdout, temporarily restore it so
    # stdio_server() binds to the real stdout file descriptor.
    if original_stdout:
        saved = sys.stdout
        sys.stdout = original_stdout
    async with stdio_server() as (read, write):
        if original_stdout:
            sys.stdout = saved  # re-redirect after binding
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
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--port", default=8765, help="UI server port")
@click.option("--host", default="127.0.0.1", help="UI server host")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser automatically")
def ui(db: str, port: int, host: str, no_browser: bool):
    """Launch the web UI dashboard (agent graph, events, tool calls)."""
    import threading
    import time as _time
    from kaos.ui.server import run as _run_ui

    db_abs = str(Path(db).resolve())

    if not no_browser:
        def _open():
            _time.sleep(1.2)
            import webbrowser
            webbrowser.open(f"http://{host}:{port}/?db={db_abs}")
        threading.Thread(target=_open, daemon=True).start()

    console.print(f"[bold cyan]KAOS UI[/bold cyan]  →  [link=http://{host}:{port}/?db={db_abs}]http://{host}:{port}/[/link]")
    console.print(f"[dim]Project: {db_abs}[/dim]")
    console.print("[dim]Ctrl+C to stop[/dim]")
    try:
        _run_ui(host=host, port=port, db=db_abs)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


@cli.command()
@click.option("--port", default=8765, help="UI server port")
@click.option("--host", default="127.0.0.1", help="UI server host")
@click.option("--no-browser", is_flag=True, default=False, help="Don't open browser automatically")
def demo(port: int, host: str, no_browser: bool):
    """Seed a demo database and open the live dashboard.

    Creates demo.db with realistic agent data (code review swarm, parallel
    refactors, failed migrations) so you can explore the UI without running
    real agents.
    """
    import random
    import threading
    import time as _time
    from kaos.ui.server import run as _run_ui

    demo_db = str(Path("./demo.db").resolve())

    # ── Seed demo data ────────────────────────────────────────────────────
    console.print("[bold cyan]KAOS Demo[/bold cyan]  Seeding demo.db…")

    if Path(demo_db).exists():
        try:
            Path(demo_db).unlink()
        except PermissionError:
            # File locked (old server still running) — use a timestamped name
            import time as _ts
            demo_db = str(Path(f"./demo_{int(_ts.time())}.db").resolve())

    db_obj = Kaos(db_path=demo_db)

    waves = [
        {
            "goal": "Code review swarm: security + perf + style analysis of payments module",
            "agents": [
                ("security-reviewer", "completed", 4, 18,
                 "Scan payments module for SQL injection, auth bypass, and hardcoded secrets"),
                ("perf-reviewer", "completed", 3, 12,
                 "Profile payments module for N+1 queries, missing indexes, and slow loops"),
                ("style-reviewer", "completed", 3, 10,
                 "Enforce PEP 8, naming conventions, and docstring coverage"),
                ("test-writer", "completed", 5, 22,
                 "Write pytest unit tests for all payment endpoints"),
                ("doc-writer", "completed", 4, 8,
                 "Generate API reference docs from code and write usage examples"),
            ],
        },
        {
            "goal": "Parallel refactor: auth module + legacy parser + API redesign",
            "agents": [
                ("auth-refactor", "completed", 6, 28,
                 "Refactor auth.py to use JWT tokens, remove session-based auth"),
                ("legacy-parser", "failed", 2, 9,
                 "Parse legacy CSV format and migrate to Parquet — fails on encoding edge cases"),
                ("api-redesign", "running", 4, 20,
                 "Redesign REST API to follow OpenAPI 3.1 spec with versioned endpoints"),
                ("migration-agent", "running", 3, 15,
                 "Run database migration: add user_preferences table, backfill defaults"),
            ],
        },
        {
            "goal": "Post-deploy triage: investigate prod anomaly in checkout flow",
            "agents": [
                ("log-analyst", "completed", 2, 6,
                 "Parse production logs from last 2 hours, find spike in 500 errors"),
                ("runaway-agent", "killed", 1, 5,
                 "Attempt auto-rollback — terminated after exceeding 30-minute budget"),
                ("data-pipeline", "paused", 3, 11,
                 "Backfill missing orders from cache into PostgreSQL — paused awaiting approval"),
            ],
        },
    ]

    tool_names = ["fs_read", "fs_write", "fs_ls", "shell_exec", "state_set", "state_get", "fs_mkdir"]
    total_agents = 0

    for wave in waves:
        for name, target_status, num_files, num_calls, task in wave["agents"]:
            aid = db_obj.spawn(name)
            db_obj.set_state(aid, "task", task)

            db_obj.write(aid, "/src/main.py",
                         f"# {name}\n\ndef main():\n    pass\n".encode())
            db_obj.write(aid, "/README.md", f"# {name}\n\n{task}\n".encode())
            if "reviewer" in name:
                db_obj.write(aid, "/review.md",
                             f"# Review by {name}\n\n## Findings\n- Issue 1: SQL injection risk\n".encode())
            if "test" in name:
                db_obj.write(aid, "/tests/test_main.py",
                             b"import pytest\n\ndef test_basic():\n    assert True\n")
            for i in range(max(0, num_files - 2)):
                db_obj.write(aid, f"/src/module_{i}.py", f"# module {i}\n".encode())

            db_obj.set_state(aid, "progress",
                             100 if target_status == "completed" else random.randint(15, 70))
            db_obj.set_state(aid, "iteration", random.randint(5, 50))

            for i in range(num_calls):
                tool = random.choice(tool_names)
                call_id = db_obj.log_tool_call(aid, tool, {"path": f"/src/file_{i}.py"})
                db_obj.start_tool_call(call_id)
                if target_status == "failed" and i >= num_calls - 2:
                    db_obj.complete_tool_call(
                        call_id, {"error": "ConnectionError"},
                        status="error", error_message="ConnectionError",
                        token_count=random.randint(50, 300),
                    )
                else:
                    db_obj.complete_tool_call(
                        call_id, {"result": "ok"},
                        status="success", token_count=random.randint(400, 4500),
                    )

            db_obj.checkpoint(aid, label=f"{name}-initial")
            if target_status == "completed":
                db_obj.checkpoint(aid, label=f"{name}-final")
                db_obj.complete(aid)
            elif target_status == "running":
                db_obj.set_status(aid, "running", pid=12345)
                db_obj.heartbeat(aid)
            elif target_status == "failed":
                db_obj.fail(aid, error="ConnectionError: endpoint unreachable")
            elif target_status == "killed":
                db_obj.kill(aid)
            elif target_status == "paused":
                db_obj.set_status(aid, "running", pid=12345)
                db_obj.pause(aid)

            total_agents += 1

    db_obj.close()
    console.print(f"[green]✓[/green] Seeded {total_agents} agents across {len(waves)} execution waves")

    # ── Open UI ───────────────────────────────────────────────────────────
    if not no_browser:
        def _open():
            _time.sleep(1.2)
            import webbrowser
            webbrowser.open(f"http://{host}:{port}/?db={demo_db}")
        threading.Thread(target=_open, daemon=True).start()

    console.print(f"[bold cyan]Dashboard[/bold cyan]  →  [link=http://{host}:{port}/]http://{host}:{port}/[/link]")
    console.print("[dim]Ctrl+C to stop[/dim]\n")
    try:
        _run_ui(host=host, port=port, db=demo_db)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/dim]")


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


@cli.command("read")
@click.argument("agent_id")
@click.argument("path")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def read_file(ctx, agent_id: str, path: str, db: str):
    """Read a file from an agent's virtual filesystem."""
    afs = _get_afs(db)
    try:
        content = afs.read(agent_id, path)
        text = content.decode("utf-8", errors="replace")
        if ctx.obj.get("json"):
            click.echo(json.dumps({"agent_id": agent_id, "path": path, "content": text}))
        else:
            click.echo(text)
    except FileNotFoundError:
        if not _json_err(ctx, f"File not found: {agent_id}:{path}"):
            console.print(f"[red]File not found: {agent_id}:{path}[/red]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("logs")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--tail", "-n", type=int, help="Show last N events")
@click.pass_context
def logs(ctx, agent_id: str, db: str, tail: int):
    """View an agent's conversation history and event log."""
    afs = _get_afs(db)
    try:
        # Try conversation first
        conversation = afs.get_state_or(agent_id, "conversation")
        events = afs.query(
            "SELECT timestamp, event_type, payload FROM events "
            "WHERE agent_id = ? ORDER BY timestamp",
            (agent_id,),
        )
        if tail:
            events = events[-tail:]

        result = {
            "agent_id": agent_id,
            "conversation_turns": len(conversation) if conversation else 0,
            "events": events,
        }
        if conversation:
            result["conversation"] = conversation

        if _json_out(ctx, result):
            return

        # Pretty print
        info = afs.status(agent_id)
        console.print(f"[bold]{info['name']}[/bold] [{info['status']}]")
        if conversation:
            console.print(f"\n[cyan]Conversation ({len(conversation)} turns):[/cyan]")
            for msg in conversation:
                role = msg.get("role", "?")
                content = str(msg.get("content", ""))[:200]
                console.print(f"  [{role}] {content}")
        console.print(f"\n[cyan]Events ({len(events)}):[/cyan]")
        for evt in events[-20:]:
            console.print(f"  {evt['timestamp'][:19]} {evt['event_type']}")
        if len(events) > 20:
            console.print(f"  ... ({len(events) - 20} more, use --json for all)")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("index")
@click.argument("agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def build_index(ctx, agent_id: str, db: str):
    """Build an /index.md for an agent's VFS."""
    afs = _get_afs(db)
    try:
        content = afs.build_index(agent_id)
        if ctx.obj.get("json"):
            click.echo(json.dumps({"agent_id": agent_id, "index": content}))
        else:
            console.print(content)
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@cli.command("search")
@click.argument("query_text")
@click.option("--agent", "-a", help="Scope to one agent")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.option("--limit", "-n", default=50, help="Max results")
@click.pass_context
def search_files(ctx, query_text: str, agent: str, db: str, limit: int):
    """Full-text search across agent VFS file contents."""
    afs = _get_afs(db)
    try:
        results = afs.search(query_text, agent_id=agent, limit=limit)
        if _json_out(ctx, results):
            return
        if not results:
            console.print("[dim]No matches[/dim]")
            return
        from rich.table import Table as _T
        table = _T(title=f"Search: {query_text}")
        table.add_column("Agent", style="cyan", max_width=14)
        table.add_column("Path")
        table.add_column("Line", justify="right")
        table.add_column("Content", max_width=60)
        for r in results:
            table.add_row(r["agent_id"][:12] + "...", r["path"], str(r["line"]), r["content"][:60])
        console.print(table)
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


@mh.command("lint")
@click.argument("search_agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_lint(ctx, search_agent_id, db):
    """Health-check a search archive for issues."""
    afs = _get_afs(db)
    try:
        info = afs.status(search_agent_id)
        harness_dirs = afs.ls(search_agent_id, "/harnesses")
        issues_found = []

        # Check for harnesses with empty scores
        empty_scores = 0
        failed_harnesses = 0
        all_scores = {}
        for entry in harness_dirs:
            if not entry.get("is_dir"):
                continue
            hid = entry["name"]
            try:
                scores = json.loads(afs.read(search_agent_id, f"/harnesses/{hid}/scores.json").decode())
                meta = json.loads(afs.read(search_agent_id, f"/harnesses/{hid}/metadata.json").decode())
                if not scores:
                    empty_scores += 1
                if meta.get("error"):
                    failed_harnesses += 1
                all_scores[hid] = scores
            except FileNotFoundError:
                issues_found.append(f"Missing scores/metadata for harness {hid[:12]}")

        if empty_scores:
            issues_found.append(f"{empty_scores} harnesses have empty scores (evaluation failed)")
        if failed_harnesses:
            issues_found.append(f"{failed_harnesses} harnesses have errors in metadata")

        # Check for iteration errors
        iter_dirs = afs.ls(search_agent_id, "/iterations")
        error_iters = 0
        for entry in iter_dirs:
            if entry.get("is_dir"):
                try:
                    afs.read(search_agent_id, f"{entry['path']}/error.json")
                    error_iters += 1
                except FileNotFoundError:
                    pass
        if error_iters:
            issues_found.append(f"{error_iters} iterations had errors (proposer timeout or eval failure)")

        # Check frontier
        try:
            frontier = json.loads(afs.read(search_agent_id, "/pareto/frontier.json").decode())
            frontier_size = len(frontier.get("points", []))
            if frontier_size == 0:
                issues_found.append("Pareto frontier is empty — no successful harnesses")
        except FileNotFoundError:
            issues_found.append("No Pareto frontier found")
            frontier_size = 0

        result = {
            "search_agent_id": search_agent_id,
            "status": info["status"],
            "total_harnesses": len(harness_dirs),
            "frontier_size": frontier_size,
            "issues": issues_found,
            "health": "clean" if not issues_found else f"{len(issues_found)} issues",
        }
        if _json_out(ctx, result):
            return

        console.print(f"[bold]Lint: {search_agent_id[:14]}...[/bold]")
        console.print(f"  Status: {info['status']}")
        console.print(f"  Harnesses: {len(harness_dirs)}, Frontier: {frontier_size}")
        if issues_found:
            console.print(f"\n[yellow]{len(issues_found)} issues found:[/yellow]")
            for issue in issues_found:
                console.print(f"  - {issue}")
        else:
            console.print(f"\n[green]Clean — no issues found[/green]")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


@mh.command("knowledge")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def mh_knowledge(ctx, db):
    """Show the persistent knowledge base — discoveries from all prior searches."""
    afs = _get_afs(db)
    try:
        knowledge_id = afs.get_or_create_singleton("kaos-knowledge")
        files = afs.ls(knowledge_id, "/discoveries") if afs.exists(knowledge_id, "/discoveries") else []

        benchmarks = []
        for entry in files:
            if entry.get("is_dir"):
                bname = entry["name"]
                try:
                    latest = json.loads(
                        afs.read(knowledge_id, f"/discoveries/{bname}/latest_search.json").decode()
                    )
                except FileNotFoundError:
                    latest = {}
                harnesses = afs.ls(knowledge_id, f"/discoveries/{bname}/harnesses") if afs.exists(knowledge_id, f"/discoveries/{bname}/harnesses") else []
                benchmarks.append({
                    "benchmark": bname,
                    "harnesses_stored": len(harnesses),
                    "latest_search": latest,
                })

        result = {"knowledge_agent_id": knowledge_id, "benchmarks": benchmarks}
        if _json_out(ctx, result):
            return

        console.print(f"[bold]Knowledge Agent:[/bold] {knowledge_id[:14]}...")
        if not benchmarks:
            console.print("[dim]No discoveries yet — run a search first[/dim]")
        for b in benchmarks:
            console.print(f"\n  [cyan]{b['benchmark']}[/cyan]")
            console.print(f"    Harnesses stored: {b['harnesses_stored']}")
            if b["latest_search"]:
                console.print(f"    Best scores: {b['latest_search'].get('best_scores', {})}")
    except ValueError as e:
        if not _json_err(ctx, str(e)):
            console.print(f"[red]{e}[/red]")
    finally:
        afs.close()


# ── Memory CLI (kaos memory ...) ──────────────────────────────────────────

@cli.group()
def memory():
    """Cross-agent memory store — write and search shared knowledge."""


@memory.command("write")
@click.argument("agent_id")
@click.argument("content")
@click.option("--type", "-t", "mem_type", default="observation",
              type=click.Choice(["observation", "result", "skill", "insight", "error"]),
              help="Memory type")
@click.option("--key", "-k", default=None, help="Optional human-readable key")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_write(ctx, agent_id: str, content: str, mem_type: str, key: str, db: str):
    """Write a memory entry for AGENT_ID with CONTENT."""
    from kaos.memory import MemoryStore
    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        mid = mem.write(agent_id=agent_id, content=content, type=mem_type, key=key)
        result = {"memory_id": mid, "agent_id": agent_id, "type": mem_type, "key": key}
        if _json_out(ctx, result):
            return
        console.print(f"[green]Memory #{mid} written[/green]  agent={agent_id[:14]}  type={mem_type}"
                      + (f"  key={key}" if key else ""))
    finally:
        afs.close()


@memory.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results")
@click.option("--type", "-t", "mem_type", default=None,
              type=click.Choice(["observation", "result", "skill", "insight", "error"]),
              help="Filter by type")
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_search(ctx, query: str, limit: int, mem_type: str, agent: str, db: str):
    """Full-text search across shared memory (FTS5 + porter stemming)."""
    from kaos.memory import MemoryStore
    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        hits = mem.search(query=query, limit=limit, type=mem_type, agent_id=agent)
        if _json_out(ctx, [h.to_dict() for h in hits]):
            return
        if not hits:
            console.print("[dim]No results[/dim]")
            return
        for h in hits:
            key_str = f"  [dim]key={h.key}[/dim]" if h.key else ""
            console.print(f"[bold cyan]#{h.memory_id}[/bold cyan]  "
                          f"[yellow]{h.type}[/yellow]  "
                          f"[dim]{h.agent_id[:14]}[/dim]  "
                          f"[dim]{h.created_at[:19]}[/dim]{key_str}")
            console.print(f"  {h.content[:120]}" + ("..." if len(h.content) > 120 else ""))
    finally:
        afs.close()


@memory.command("ls")
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option("--type", "-t", "mem_type", default=None,
              type=click.Choice(["observation", "result", "skill", "insight", "error"]),
              help="Filter by type")
@click.option("--limit", "-n", default=20, help="Max results")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def memory_ls(ctx, agent: str, mem_type: str, limit: int, db: str):
    """List memory entries (most recent first)."""
    from kaos.memory import MemoryStore
    afs = _get_afs(db)
    try:
        mem = MemoryStore(afs.conn)
        entries = mem.list(agent_id=agent, type=mem_type, limit=limit)
        if _json_out(ctx, [e.to_dict() for e in entries]):
            return
        stats = mem.stats()
        console.print(f"[bold]Memory Store[/bold]  total={stats['total']}  "
                      + "  ".join(f"{k}={v}" for k, v in stats["by_type"].items()))
        if not entries:
            console.print("[dim]No entries[/dim]")
            return
        for e in entries:
            key_str = f"  [dim]{e.key}[/dim]" if e.key else ""
            console.print(f"  [cyan]#{e.memory_id}[/cyan]  [yellow]{e.type}[/yellow]  "
                          f"[dim]{e.agent_id[:14]}[/dim]  [dim]{e.created_at[:19]}[/dim]{key_str}")
            console.print(f"    {e.content[:100]}" + ("..." if len(e.content) > 100 else ""))
    finally:
        afs.close()


# ── Shared Log CLI (kaos log ...) ─────────────────────────────────────────

@cli.group("log")
def shared_log_group():
    """Shared coordination log — LogAct intent/vote/decide protocol."""


@shared_log_group.command("tail")
@click.option("--n", "-n", "count", default=20, help="Number of entries to show")
@click.option("--type", "-t", "log_type", default=None, help="Filter by entry type")
@click.option("--agent", "-a", default=None, help="Filter by agent_id")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def log_tail(ctx, count: int, log_type: str, agent: str, db: str):
    """Show the last N entries from the shared coordination log."""
    from kaos.shared_log import SharedLog
    afs = _get_afs(db)
    try:
        log = SharedLog(afs.conn)
        if log_type or agent:
            entries = log.read(type=log_type, agent_id=agent, limit=count)
        else:
            entries = log.tail(count)
        if _json_out(ctx, [e.to_dict() for e in entries]):
            return
        if not entries:
            console.print("[dim]Log is empty[/dim]")
            return
        TYPE_COLORS = {
            "intent": "cyan", "vote": "yellow", "decision": "green",
            "commit": "bold green", "result": "magenta", "abort": "red",
            "policy": "bold white", "mail": "blue",
        }
        for e in entries:
            color = TYPE_COLORS.get(e.type, "white")
            ref_str = f"  [dim]ref={e.ref_id}[/dim]" if e.ref_id else ""
            console.print(f"[dim]{e.position:4d}[/dim]  [{color}]{e.type:8s}[/{color}]  "
                          f"[dim]{e.agent_id[:14]}[/dim]  [dim]{e.created_at[:19]}[/dim]{ref_str}")
            payload_str = str(e.payload)
            console.print(f"       {payload_str[:100]}" + ("..." if len(payload_str) > 100 else ""))
    finally:
        afs.close()


@shared_log_group.command("ls")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def log_ls(ctx, db: str):
    """Show shared log statistics."""
    from kaos.shared_log import SharedLog
    afs = _get_afs(db)
    try:
        log = SharedLog(afs.conn)
        stats = log.stats()
        if _json_out(ctx, stats):
            return
        console.print(f"[bold]Shared Log[/bold]  total={stats['total']}")
        for t, n in stats["by_type"].items():
            console.print(f"  {t:12s} {n}")
    finally:
        afs.close()


# ── Skills CLI (kaos skills ...) ──────────────────────────────────────────

@cli.group("skills")
def skills_group():
    """Cross-agent skill library — save and search reusable solution patterns."""


@skills_group.command("save")
@click.option("--name", "-n", required=True, help="Skill name (snake_case)")
@click.option("--description", "-d", required=True, help="What the skill does and when to use it")
@click.option("--template", "-t", required=True, help="Prompt template (use {param} for variables)")
@click.option("--agent", "-a", default=None, help="Source agent_id")
@click.option("--tags", default=None, help="Comma-separated tags (e.g. classification,ensemble)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_save(ctx, name: str, description: str, template: str, agent: str, tags: str, db: str):
    """Save a reusable skill to the shared library."""
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        tag_list = [t.strip() for t in tags.split(",")] if tags else []
        sid = sk.save(name=name, description=description, template=template,
                      source_agent_id=agent, tags=tag_list)
        skill = sk.get(sid)
        result = skill.to_dict() if skill else {"skill_id": sid}
        if _json_out(ctx, result):
            return
        params_str = ", ".join(skill.params()) if skill and skill.params() else "(no params)"
        console.print(f"[green]Skill #{sid} saved[/green]  name={name}  params=[{params_str}]")
        if tag_list:
            console.print(f"  tags: {', '.join(tag_list)}")
    finally:
        afs.close()


@skills_group.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results")
@click.option("--tag", default=None, help="Filter by tag")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_search(ctx, query: str, limit: int, tag: str, db: str):
    """Full-text search across the skill library (FTS5 + BM25)."""
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        hits = sk.search(query=query, limit=limit, tag=tag)
        if _json_out(ctx, [s.to_dict() for s in hits]):
            return
        if not hits:
            console.print("[dim]No skills found[/dim]")
            return
        for s in hits:
            rate = f"{s.success_count}/{s.use_count}" if s.use_count else "unused"
            tags_str = f"  [dim]{', '.join(s.tags)}[/dim]" if s.tags else ""
            console.print(f"[bold cyan]#{s.skill_id}[/bold cyan]  [yellow]{s.name}[/yellow]  "
                          f"[dim]{rate}[/dim]{tags_str}")
            console.print(f"  {s.description[:120]}" + ("..." if len(s.description) > 120 else ""))
            params = s.params()
            if params:
                console.print(f"  params: {{{', '.join(params)}}}")
    finally:
        afs.close()


@skills_group.command("ls")
@click.option("--tag", default=None, help="Filter by tag")
@click.option("--agent", "-a", default=None, help="Filter by source agent_id")
@click.option("--order", default="created_at",
              type=click.Choice(["created_at", "success_count", "use_count", "name"]),
              help="Sort order")
@click.option("--limit", "-n", default=20, help="Max results")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_ls(ctx, tag: str, agent: str, order: str, limit: int, db: str):
    """List skills in the library (most recent first)."""
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        skills = sk.list(tag=tag, source_agent_id=agent, order_by=order, limit=limit)
        if _json_out(ctx, [s.to_dict() for s in skills]):
            return
        stats = sk.stats()
        console.print(f"[bold]Skill Library[/bold]  total={stats['total']}")
        if not skills:
            console.print("[dim]No skills[/dim]")
            return
        t = Table(show_header=True, header_style="bold")
        t.add_column("ID", style="cyan", width=5)
        t.add_column("Name", style="yellow", width=24)
        t.add_column("Tags", width=20)
        t.add_column("Used", width=6)
        t.add_column("OK%", width=6)
        t.add_column("Description", width=40)
        for s in skills:
            rate = f"{s.success_count/s.use_count*100:.0f}%" if s.use_count else "-"
            t.add_row(
                str(s.skill_id),
                s.name,
                ", ".join(s.tags[:3]),
                str(s.use_count),
                rate,
                s.description[:40] + ("..." if len(s.description) > 40 else ""),
            )
        console.print(t)
    finally:
        afs.close()


@skills_group.command("apply")
@click.argument("skill_id", type=int)
@click.option("--param", "-p", "params", multiple=True,
              help="Template param as key=value (repeat for multiple)")
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_apply(ctx, skill_id: int, params: tuple, db: str):
    """Render a skill template with parameters and print the result.

    Example: kaos skills apply 3 -p model=gpt4 -p voting=majority
    """
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        skill = sk.get(skill_id)
        if not skill:
            console.print(f"[red]Skill #{skill_id} not found[/red]")
            return
        kv: dict[str, str] = {}
        for p in params:
            if "=" in p:
                k, v = p.split("=", 1)
                kv[k.strip()] = v.strip()
        rendered = skill.apply(**kv)
        if _json_out(ctx, {"skill_id": skill_id, "name": skill.name, "rendered": rendered}):
            return
        console.print(f"[bold]Skill #{skill_id} — {skill.name}[/bold]")
        console.print(rendered)
    finally:
        afs.close()


@skills_group.command("delete")
@click.argument("skill_id", type=int)
@click.option("--db", default=DEFAULT_DB, help="Database file path")
@click.pass_context
def skills_delete(ctx, skill_id: int, db: str):
    """Delete a skill by ID."""
    from kaos.skills import SkillStore
    afs = _get_afs(db)
    try:
        sk = SkillStore(afs.conn)
        removed = sk.delete(skill_id)
        result = {"skill_id": skill_id, "deleted": removed}
        if _json_out(ctx, result):
            return
        if removed:
            console.print(f"[green]Skill #{skill_id} deleted[/green]")
        else:
            console.print(f"[yellow]Skill #{skill_id} not found[/yellow]")
    finally:
        afs.close()


if __name__ == "__main__":
    cli()
