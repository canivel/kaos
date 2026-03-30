"""Checkpoint diff rendering for CLI output."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


def render_diff(diff: dict, console: Console | None = None) -> None:
    """Render a checkpoint diff to the console using Rich."""
    console = console or Console()

    # File changes
    files = diff.get("files", {})
    if files.get("added") or files.get("removed") or files.get("modified"):
        file_table = Table(title="File Changes", show_header=True)
        file_table.add_column("Status", style="bold", width=10)
        file_table.add_column("Path")

        for path in files.get("added", []):
            file_table.add_row(Text("ADDED", style="green"), path)
        for path in files.get("removed", []):
            file_table.add_row(Text("REMOVED", style="red"), path)
        for path in files.get("modified", []):
            file_table.add_row(Text("MODIFIED", style="yellow"), path)

        console.print(file_table)
    else:
        console.print("[dim]No file changes[/dim]")

    console.print()

    # State changes
    state = diff.get("state", {})
    if state.get("added") or state.get("removed") or state.get("modified"):
        state_table = Table(title="State Changes", show_header=True)
        state_table.add_column("Status", style="bold", width=10)
        state_table.add_column("Key")
        state_table.add_column("Value")

        for key, value in state.get("added", {}).items():
            state_table.add_row(
                Text("ADDED", style="green"), key, str(value)[:80]
            )
        for key, value in state.get("removed", {}).items():
            state_table.add_row(
                Text("REMOVED", style="red"), key, str(value)[:80]
            )
        for key, changes in state.get("modified", {}).items():
            state_table.add_row(
                Text("MODIFIED", style="yellow"),
                key,
                f"{str(changes['from'])[:40]} -> {str(changes['to'])[:40]}",
            )

        console.print(state_table)
    else:
        console.print("[dim]No state changes[/dim]")

    console.print()

    # Tool calls between checkpoints
    tool_calls = diff.get("tool_calls", [])
    if tool_calls:
        tc_table = Table(title="Tool Calls Between Checkpoints", show_header=True)
        tc_table.add_column("Tool", style="cyan")
        tc_table.add_column("Status")
        tc_table.add_column("Duration", justify="right")
        tc_table.add_column("Tokens", justify="right")

        for tc in tool_calls:
            status_style = "green" if tc["status"] == "success" else "red"
            tc_table.add_row(
                tc["tool_name"],
                Text(tc["status"], style=status_style),
                f"{tc.get('duration_ms', '?')}ms",
                str(tc.get("token_count", "?")),
            )

        console.print(tc_table)
    else:
        console.print("[dim]No tool calls between checkpoints[/dim]")
