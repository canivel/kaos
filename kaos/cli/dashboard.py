"""TUI Dashboard for KAOS — real-time agent monitoring."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Container
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Header, Static, RichLog

if TYPE_CHECKING:
    from kaos.core import Kaos


STATUS_STYLES = {
    "running": "bold green",
    "initialized": "bold cyan",
    "completed": "green",
    "failed": "bold red",
    "killed": "red",
    "paused": "yellow",
}

EVENT_COLORS = {
    "agent_spawn": "green",
    "agent_complete": "green",
    "agent_fail": "red",
    "agent_kill": "red",
    "agent_pause": "yellow",
    "agent_resume": "cyan",
    "file_write": "bright_blue",
    "file_read": "dim",
    "file_delete": "magenta",
    "tool_call_start": "bright_cyan",
    "tool_call_end": "bright_cyan",
    "state_change": "bright_yellow",
    "checkpoint_create": "bright_green",
    "checkpoint_restore": "bright_magenta",
    "error": "bold red",
    "warning": "yellow",
}


class AgentTable(Widget):
    """Widget displaying agent status table."""

    def __init__(self, afs: Kaos, **kwargs):
        super().__init__(**kwargs)
        self.afs = afs

    def compose(self) -> ComposeResult:
        table = DataTable(id="agent-table", zebra_stripes=True)
        yield table

    def on_mount(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.add_columns(
            "Agent ID", "Name", "Status", "Files", "Tool Calls", "Tokens", "Created",
        )
        self.refresh_data()
        self.set_interval(2.0, self.refresh_data)

    def refresh_data(self) -> None:
        table = self.query_one("#agent-table", DataTable)
        table.clear()

        agents = self.afs.query("""
            SELECT
                a.agent_id, a.name, a.status, a.created_at,
                (SELECT COUNT(*) FROM files f WHERE f.agent_id = a.agent_id AND f.deleted = 0) as file_count,
                (SELECT COUNT(*) FROM tool_calls tc WHERE tc.agent_id = a.agent_id) as call_count,
                (SELECT COALESCE(SUM(tc.token_count), 0) FROM tool_calls tc WHERE tc.agent_id = a.agent_id) as token_count
            FROM agents a
            ORDER BY a.created_at DESC LIMIT 50
        """)

        for agent in agents:
            status = agent["status"]
            style = STATUS_STYLES.get(status, "")
            status_text = Text(status.upper(), style=style)

            tokens = agent["token_count"] or 0
            token_str = f"{tokens:,}" if tokens else "-"

            table.add_row(
                agent["agent_id"][:14] + "...",
                agent["name"],
                status_text,
                str(agent["file_count"]),
                str(agent["call_count"]),
                token_str,
                agent["created_at"][:19] if agent["created_at"] else "",
            )


class StatsPanel(Static):
    """Widget showing aggregate statistics."""

    def __init__(self, afs: Kaos, **kwargs):
        super().__init__(**kwargs)
        self.afs = afs

    def on_mount(self) -> None:
        self.refresh_stats()
        self.set_interval(3.0, self.refresh_stats)

    def refresh_stats(self) -> None:
        try:
            agents = self.afs.query(
                "SELECT status, COUNT(*) as cnt FROM agents GROUP BY status"
            )
            agent_stats = {r["status"]: r["cnt"] for r in agents}
            total_agents = sum(agent_stats.values())

            token_row = self.afs.query(
                "SELECT COALESCE(SUM(token_count), 0) as total, COUNT(*) as calls, "
                "SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors "
                "FROM tool_calls"
            )
            total_tokens = token_row[0]["total"] if token_row else 0
            total_calls = token_row[0]["calls"] if token_row else 0
            total_errors = token_row[0]["errors"] if token_row else 0

            blob_stats = self.afs.blobs.stats()

            event_count = self.afs.query("SELECT COUNT(*) as n FROM events")
            n_events = event_count[0]["n"] if event_count else 0

            running = agent_stats.get("running", 0) + agent_stats.get("initialized", 0)
            completed = agent_stats.get("completed", 0)
            failed = agent_stats.get("failed", 0)
            paused = agent_stats.get("paused", 0)
            killed = agent_stats.get("killed", 0)

            stored_kb = blob_stats["total_stored_bytes"] / 1024

            self.update(
                f"[bold bright_white]AGENTS[/]  "
                f"[green]{running}[/] running  "
                f"[bright_green]{completed}[/] completed  "
                f"[red]{failed}[/] failed  "
                f"[yellow]{paused}[/] paused  "
                f"[dim]{killed}[/] killed  "
                f"[bright_white]{total_agents}[/] total"
                f"      "
                f"[bold bright_white]CALLS[/]  "
                f"{total_calls:,} total  "
                f"[red]{total_errors}[/] errors  "
                f"[bright_cyan]{total_tokens:,}[/] tokens"
                f"      "
                f"[bold bright_white]STORAGE[/]  "
                f"{blob_stats['total_blobs']} blobs  "
                f"{stored_kb:.1f} KB  "
                f"{n_events:,} events"
            )
        except Exception as e:
            self.update(f"[red]Error: {e}[/red]")


class MetaHarnessPanel(Static):
    """Widget showing active Meta-Harness search status."""

    def __init__(self, afs: Kaos, **kwargs):
        super().__init__(**kwargs)
        self.afs = afs

    def on_mount(self) -> None:
        self.refresh_mh()
        self.set_interval(5.0, self.refresh_mh)

    def refresh_mh(self) -> None:
        try:
            searches = self.afs.query("""
                SELECT a.agent_id, a.name, a.status, a.created_at
                FROM agents a
                WHERE a.name = 'meta-harness-search'
                ORDER BY a.created_at DESC LIMIT 3
            """)

            if not searches:
                self.update("[dim]No Meta-Harness searches[/dim]")
                return

            lines = []
            for s in searches:
                aid = s["agent_id"]
                status = s["status"]
                style = STATUS_STYLES.get(status, "")

                iteration = self.afs.get_state(aid, "current_iteration") or 0

                # Count harnesses
                try:
                    harnesses = self.afs.ls(aid, "/harnesses")
                    n_harnesses = len(harnesses)
                except Exception:
                    n_harnesses = 0

                # Frontier size
                try:
                    frontier_data = json.loads(
                        self.afs.read(aid, "/pareto/frontier.json").decode()
                    )
                    n_frontier = len(frontier_data.get("points", []))
                except Exception:
                    n_frontier = 0

                lines.append(
                    f"  [{style}]{status.upper()}[/{style}] "
                    f"iter {iteration}  "
                    f"{n_harnesses} harnesses  "
                    f"frontier={n_frontier}  "
                    f"({aid[:12]}...)"
                )

            self.update(
                "[bold bright_white]META-HARNESS[/]\n" + "\n".join(lines)
            )
        except Exception as e:
            self.update(f"[dim]Meta-Harness: {e}[/dim]")


class EventLog(Widget):
    """Widget showing recent events as a scrolling log."""

    def __init__(self, afs: Kaos, **kwargs):
        super().__init__(**kwargs)
        self.afs = afs
        self._last_event_id = 0

    def compose(self) -> ComposeResult:
        yield RichLog(id="event-log", max_lines=200, wrap=True, markup=True)

    def on_mount(self) -> None:
        self._load_initial()
        self.set_interval(2.0, self._poll_new)

    def _load_initial(self) -> None:
        log = self.query_one("#event-log", RichLog)
        events = self.afs.query(
            "SELECT event_id, timestamp, agent_id, event_type, payload "
            "FROM events ORDER BY event_id DESC LIMIT 30"
        )
        for event in reversed(events):
            self._write_event(log, event)
            self._last_event_id = max(self._last_event_id, event["event_id"])

    def _poll_new(self) -> None:
        events = self.afs.query(
            "SELECT event_id, timestamp, agent_id, event_type, payload "
            "FROM events WHERE event_id > ? ORDER BY event_id LIMIT 20",
            [self._last_event_id],
        )
        if events:
            log = self.query_one("#event-log", RichLog)
            for event in events:
                self._write_event(log, event)
                self._last_event_id = max(self._last_event_id, event["event_id"])

    def _write_event(self, log: RichLog, event: dict) -> None:
        ts = event["timestamp"][:19] if event.get("timestamp") else "?"
        agent_short = (event.get("agent_id") or "?")[:10]
        etype = event.get("event_type", "?")
        payload = str(event.get("payload") or "")
        if len(payload) > 80:
            payload = payload[:77] + "..."

        color = EVENT_COLORS.get(etype, "dim")
        text = Text()
        text.append(f" {ts} ", style="dim")
        text.append(f" {agent_short} ", style="cyan")
        text.append(f" {etype:22s}", style=color)
        text.append(f" {payload}", style="dim")
        log.write(text)


class KaosDashboard(App):
    """KAOS TUI Dashboard for real-time agent monitoring."""

    TITLE = "KAOS Dashboard"
    SUB_TITLE = "Kernel for Agent Orchestration & Sandboxing"

    CSS = """
    Screen {
        background: #0a0a12;
    }

    #stats-panel {
        height: 3;
        padding: 0 1;
        background: #111119;
        border: tall $accent;
        color: $text;
    }

    #mh-panel {
        height: auto;
        max-height: 6;
        padding: 0 1;
        background: #110d1a;
        border: tall #a855f7;
        color: $text;
    }

    #agent-table-container {
        height: 1fr;
        border: tall $success;
        background: #0d0d16;
    }

    AgentTable {
        height: 100%;
    }

    AgentTable DataTable {
        height: 100%;
    }

    #event-log-container {
        height: 14;
        border: tall $warning;
        background: #0d0d16;
    }

    EventLog {
        height: 100%;
    }

    EventLog RichLog {
        height: 100%;
    }

    Header {
        background: #1a1a2e;
    }

    Footer {
        background: #1a1a2e;
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
            MetaHarnessPanel(self.afs, id="mh-panel"),
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
