"""TUI Dashboard for KAOS — real-time agent monitoring."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Header, Static, RichLog
from textual.timer import Timer

if TYPE_CHECKING:
    from kaos.core import Kaos


class AgentTable(Static):
    """Widget displaying agent status table."""

    def __init__(self, afs: Kaos, **kwargs):
        super().__init__(**kwargs)
        self.afs = afs

    def compose(self) -> ComposeResult:
        yield DataTable(id="agent-table")

    def on_mount(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.add_columns(
            "Agent ID", "Name", "Status", "Created", "Heartbeat"
        )
        self.refresh_data()
        self.set_interval(2.0, self.refresh_data)

    def refresh_data(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.clear()

        agents = self.afs.query(
            "SELECT agent_id, name, status, created_at, last_heartbeat "
            "FROM agents ORDER BY created_at DESC LIMIT 50"
        )

        for agent in agents:
            status = agent["status"]
            status_text = Text(status)
            if status == "running":
                status_text.stylize("bold green")
            elif status == "completed":
                status_text.stylize("green")
            elif status == "failed":
                status_text.stylize("bold red")
            elif status == "killed":
                status_text.stylize("red")
            elif status == "paused":
                status_text.stylize("yellow")

            table.add_row(
                agent["agent_id"][:12] + "...",
                agent["name"],
                status_text,
                agent["created_at"][:19] if agent["created_at"] else "",
                agent["last_heartbeat"][:19] if agent.get("last_heartbeat") else "-",
            )


class StatsPanel(Static):
    """Widget showing aggregate statistics."""

    def __init__(self, afs: Kaos, **kwargs):
        super().__init__(**kwargs)
        self.afs = afs

    def on_mount(self) -> None:
        self.refresh_stats()
        self.set_interval(5.0, self.refresh_stats)

    def refresh_stats(self) -> None:
        try:
            agents = self.afs.query(
                "SELECT status, COUNT(*) as cnt FROM agents GROUP BY status"
            )
            agent_stats = {r["status"]: r["cnt"] for r in agents}

            token_row = self.afs.query(
                "SELECT SUM(token_count) as total, COUNT(*) as calls "
                "FROM tool_calls WHERE status = 'success'"
            )
            total_tokens = token_row[0]["total"] or 0 if token_row else 0
            total_calls = token_row[0]["calls"] or 0 if token_row else 0

            blob_stats = self.afs.blobs.stats()

            self.update(
                f"[bold]Agents[/bold]\n"
                f"  Running: [green]{agent_stats.get('running', 0)}[/green]  "
                f"Completed: {agent_stats.get('completed', 0)}  "
                f"Failed: [red]{agent_stats.get('failed', 0)}[/red]  "
                f"Total: {sum(agent_stats.values())}\n\n"
                f"[bold]Tool Calls[/bold]\n"
                f"  Total: {total_calls}  Tokens: {total_tokens:,}\n\n"
                f"[bold]Storage[/bold]\n"
                f"  Blobs: {blob_stats['total_blobs']}  "
                f"Size: {blob_stats['total_stored_bytes'] / 1024:.1f} KB  "
                f"Refs: {blob_stats['total_references']}"
            )
        except Exception as e:
            self.update(f"[red]Error loading stats: {e}[/red]")


class EventLog(Static):
    """Widget showing recent events."""

    def __init__(self, afs: Kaos, **kwargs):
        super().__init__(**kwargs)
        self.afs = afs

    def compose(self) -> ComposeResult:
        yield RichLog(id="event-log", max_lines=100, wrap=True)

    def on_mount(self) -> None:
        self.refresh_events()
        self.set_interval(3.0, self.refresh_events)

    def refresh_events(self) -> None:
        log = self.query_one("#event-log", RichLog)
        try:
            events = self.afs.query(
                "SELECT timestamp, agent_id, event_type, payload "
                "FROM events ORDER BY event_id DESC LIMIT 20"
            )
            log.clear()
            for event in reversed(events):
                agent_short = event["agent_id"][:8]
                log.write(
                    f"[dim]{event['timestamp'][:19]}[/dim] "
                    f"[cyan]{agent_short}[/cyan] "
                    f"[bold]{event['event_type']}[/bold] "
                    f"{event.get('payload', '')[:60]}"
                )
        except Exception:
            pass


class KaosDashboard(App):
    """KAOS TUI Dashboard for real-time agent monitoring."""

    CSS = """
    #stats-panel {
        height: 8;
        border: solid green;
        padding: 1;
    }

    #agent-table-container {
        height: 1fr;
        border: solid cyan;
    }

    #event-log-container {
        height: 12;
        border: solid yellow;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
    ]

    def __init__(self, afs: Kaos, **kwargs):
        super().__init__(**kwargs)
        self.afs = afs

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            StatsPanel(self.afs, id="stats-panel"),
            Container(
                AgentTable(self.afs),
                id="agent-table-container",
            ),
            Container(
                EventLog(self.afs),
                id="event-log-container",
            ),
        )
        yield Footer()

    def action_refresh(self) -> None:
        """Force refresh all panels."""
        for widget in self.query(AgentTable):
            widget.refresh_data()
        for widget in self.query(StatsPanel):
            widget.refresh_stats()
        for widget in self.query(EventLog):
            widget.refresh_events()
