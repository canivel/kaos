"""VaultExporter — walks a KAOS database and writes an Obsidian-compatible vault.

Design:
  - One-way, read-only against the .db (uses its own sqlite3 connection, never
    mutates).
  - Idempotent: re-running against the same vault refreshes generated notes
    but preserves `.obsidian/workspace*` so the user's Obsidian state stays
    put. Pass clean=True (or --clean) to wipe generated directories first.
  - Pure Python stdlib (json, sqlite3, shutil, pathlib). No extra dependencies.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaos.obsidian import assets
from kaos.obsidian.renderer import safe_filename, wikilink
from kaos.obsidian.templates import (
    render_agent,
    render_checkpoint,
    render_index,
    render_log_entry,
    render_log_file,
    render_memory,
    render_skill,
)


# Top-level directories the exporter owns. `_clean` only wipes these —
# the user's `.obsidian/workspace*` and notes in other folders are preserved.
OWNED_DIRS = (
    "Agents",
    "Skills",
    "Memory",
    "Checkpoints",
    "Sessions",
    "VFS",
    "meta",
    ".obsidian/snippets",
)

# Files the exporter owns at the vault root.
OWNED_ROOT_FILES = ("KAOS.md", "Log.md", "README.md")


# Default wave inference — the demo uses name prefixes but there's no formal
# wave column. We map by name heuristic so the graph still looks sensible.
# Callers can override via `wave_map` on the exporter.
DEFAULT_WAVE_MAP = {
    "research-agent": 1, "architect-agent": 1,
    "payment-engine-agent": 2, "fraud-agent": 2, "api-gateway-agent": 2,
    "compliance-agent": 2, "infra-agent": 2, "test-agent": 2,
    "portal-agent": 2, "migration-agent": 2,
    "security-agent": 3, "perf-agent": 3, "compliance-validator": 3,
    "compliance-validator-agent": 3, "integration-agent": 3,
    "deploy-agent": 4, "observability-agent": 4,
}


@dataclass
class ExportStats:
    agents: int = 0
    skills: int = 0
    memories: int = 0
    checkpoints: int = 0
    log_entries: int = 0
    sessions: int = 0
    files_written: int = 0
    waves: dict[int, list[str]] = field(default_factory=dict)


class VaultExporter:
    """Export a KAOS database to an Obsidian vault directory."""

    def __init__(
        self,
        db_path: str | Path,
        vault_path: str | Path,
        wave_map: dict[str, int] | None = None,
        kaos_version: str = "0.7.0",
    ) -> None:
        self.db_path = str(db_path)
        self.vault_path = Path(vault_path).expanduser().resolve()
        self.wave_map = dict(DEFAULT_WAVE_MAP)
        if wave_map:
            self.wave_map.update(wave_map)
        self.kaos_version = kaos_version
        self._agents_by_id: dict[str, dict[str, Any]] = {}
        self._skill_files: dict[int, str] = {}
        self._memory_files: dict[int, str] = {}

    # ── Top-level driver ────────────────────────────────────────────

    def export_all(self, clean: bool = False) -> ExportStats:
        """Run a full export. Returns an ExportStats summary."""
        if clean:
            self._clean()

        self._init_vault()
        stats = ExportStats()

        with self._connect() as conn:
            self._load_agents(conn)
            self._export_skills(conn, stats)
            self._export_memory(conn, stats)
            self._export_checkpoints(conn, stats)
            self._export_agents(conn, stats)   # agents last — they link to the rest
            self._export_shared_log(conn, stats)

        # Group agents by wave for the index
        stats.waves = self._group_by_wave()
        stats.agents = len(self._agents_by_id)
        self._export_index(stats)
        self._export_dashboard()

        return stats

    # ── Vault initialization ────────────────────────────────────────

    def _clean(self) -> None:
        """Remove owned directories and files — but NOT `.obsidian/workspace*`."""
        if not self.vault_path.exists():
            return
        for d in OWNED_DIRS:
            full = self.vault_path / d
            if full.exists():
                shutil.rmtree(full)
        for f in OWNED_ROOT_FILES:
            full = self.vault_path / f
            if full.exists():
                full.unlink()

    def _init_vault(self) -> None:
        """Create directories and write static assets."""
        self.vault_path.mkdir(parents=True, exist_ok=True)
        for d in OWNED_DIRS:
            (self.vault_path / d).mkdir(parents=True, exist_ok=True)
        # Memory is grouped by type
        for t in ("observation", "result", "insight", "error", "skill"):
            (self.vault_path / "Memory" / t).mkdir(parents=True, exist_ok=True)

        self._write_text(".obsidian/app.json", assets.APP_JSON)
        self._write_text(".obsidian/appearance.json", assets.APPEARANCE_JSON)
        self._write_text(".obsidian/graph.json", assets.GRAPH_JSON)
        self._write_text(".obsidian/snippets/kaos.css", assets.KAOS_CSS)
        self._write_text("README.md", assets.VAULT_README)

    # ── Database access ─────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Open a read-only connection to the .db."""
        # Use URI mode so we can request read-only
        uri = f"file:{self.db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    def _load_agents(self, conn: sqlite3.Connection) -> None:
        """Load all agents into memory (we need them for cross-linking)."""
        rows = conn.execute(
            "SELECT agent_id, name, parent_id, created_at, status, config, metadata "
            "FROM agents ORDER BY created_at"
        ).fetchall()
        for r in rows:
            agent = dict(r)
            agent["wave"] = self.wave_map.get(agent["name"])
            agent["config_pretty"] = _pretty_json(agent["config"])
            self._agents_by_id[agent["agent_id"]] = agent

    # ── Skills ──────────────────────────────────────────────────────

    def _export_skills(self, conn: sqlite3.Connection, stats: ExportStats) -> None:
        rows = conn.execute(
            "SELECT skill_id, name, description, template, tags, source_agent_id, "
            "use_count, success_count, created_at, updated_at "
            "FROM agent_skills ORDER BY skill_id"
        ).fetchall()

        for r in rows:
            skill = dict(r)
            skill["tags_list"] = _safe_json_list(skill["tags"])
            source = self._agents_by_id.get(skill["source_agent_id"])
            links = {
                "source_agent": wikilink(source["name"]) if source else "",
                "applied_by": [],  # populated in a second pass below if we track applications
            }
            filename = f"Skills/{safe_filename(skill['name'])}.md"
            self._skill_files[skill["skill_id"]] = skill["name"]
            self._write_text(filename, render_skill(skill, links))
            stats.skills += 1
            stats.files_written += 1

    # ── Memory ──────────────────────────────────────────────────────

    def _export_memory(self, conn: sqlite3.Connection, stats: ExportStats) -> None:
        rows = conn.execute(
            "SELECT memory_id, agent_id, type, key, content, metadata, created_at "
            "FROM memory ORDER BY memory_id"
        ).fetchall()

        for r in rows:
            entry = dict(r)
            entry["metadata_pretty"] = _pretty_json(entry["metadata"])
            source = self._agents_by_id.get(entry["agent_id"])
            links = {
                "source_agent": wikilink(source["name"]) if source else "",
            }
            key = entry["key"] or f"memory-{entry['memory_id']}"
            filename = f"Memory/{entry['type']}/{safe_filename(key)}.md"
            self._memory_files[entry["memory_id"]] = key
            self._write_text(filename, render_memory(entry, links))
            stats.memories += 1
            stats.files_written += 1

    # ── Checkpoints ─────────────────────────────────────────────────

    def _export_checkpoints(self, conn: sqlite3.Connection, stats: ExportStats) -> None:
        rows = conn.execute(
            "SELECT checkpoint_id, agent_id, label, created_at, "
            "file_manifest, state_snapshot, metadata "
            "FROM checkpoints ORDER BY created_at"
        ).fetchall()

        for r in rows:
            cp = dict(r)
            cp["file_manifest_pretty"] = _pretty_json(cp["file_manifest"])
            cp["state_snapshot_pretty"] = _pretty_json(cp["state_snapshot"])
            source = self._agents_by_id.get(cp["agent_id"])
            links = {
                "source_agent": wikilink(source["name"]) if source else "",
            }
            source_name = source["name"] if source else "unknown-agent"
            label = cp["label"] or cp["checkpoint_id"]
            (self.vault_path / "Checkpoints" / safe_filename(source_name)).mkdir(
                parents=True, exist_ok=True
            )
            filename = f"Checkpoints/{safe_filename(source_name)}/{safe_filename(label)}.md"
            self._write_text(filename, render_checkpoint(cp, links))
            stats.checkpoints += 1
            stats.files_written += 1

    # ── Agents (render last so we can link to skills/memories/checkpoints) ──

    def _export_agents(self, conn: sqlite3.Connection, stats: ExportStats) -> None:
        # Pre-compute backlinks per agent
        skills_by_agent: dict[str, list[str]] = {}
        for r in conn.execute(
            "SELECT name, source_agent_id FROM agent_skills"
        ).fetchall():
            aid = r["source_agent_id"]
            if aid:
                skills_by_agent.setdefault(aid, []).append(r["name"])

        mem_by_agent: dict[str, list[tuple[int, str | None]]] = {}
        for r in conn.execute(
            "SELECT memory_id, agent_id, key FROM memory ORDER BY memory_id"
        ).fetchall():
            mem_by_agent.setdefault(r["agent_id"], []).append((r["memory_id"], r["key"]))

        cp_by_agent: dict[str, list[str]] = {}
        for r in conn.execute(
            "SELECT checkpoint_id, agent_id, label FROM checkpoints ORDER BY created_at"
        ).fetchall():
            cp_by_agent.setdefault(r["agent_id"], []).append(
                r["label"] or r["checkpoint_id"]
            )

        for agent in self._agents_by_id.values():
            aid = agent["agent_id"]
            links = {
                "skills": [wikilink(n) for n in skills_by_agent.get(aid, [])],
                "memories": [
                    wikilink(key or f"memory-{mid}")
                    for (mid, key) in mem_by_agent.get(aid, [])
                ],
                "checkpoints": [
                    wikilink(lbl) for lbl in cp_by_agent.get(aid, [])
                ],
            }
            filename = f"Agents/{safe_filename(agent['name'])}.md"
            self._write_text(filename, render_agent(agent, links))
            stats.files_written += 1

    # ── Shared log ──────────────────────────────────────────────────

    def _export_shared_log(self, conn: sqlite3.Connection, stats: ExportStats) -> None:
        lines: list[str] = []
        # The shared_log table may not exist on older schemas — guard.
        try:
            rows = conn.execute(
                "SELECT log_id, position, type, agent_id, ref_id, payload, created_at "
                "FROM shared_log ORDER BY position"
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []

        for r in rows:
            entry = dict(r)
            entry["payload_pretty"] = _pretty_json(entry["payload"])
            source = self._agents_by_id.get(entry["agent_id"])
            links = {
                "source_agent": wikilink(source["name"]) if source else "",
                "ref": "",  # log entries reference other log entries by log_id —
                            # we could add named anchors in a future pass
            }
            lines.append(render_log_entry(entry, links))
            stats.log_entries += 1

        self._write_text("Log.md", render_log_file(lines, stats.log_entries))

    # ── Index + dashboard ───────────────────────────────────────────

    def _export_index(self, stats: ExportStats) -> None:
        waves_md = []
        for wave, names in sorted(stats.waves.items()):
            wave_lines = ", ".join(wikilink(n) for n in sorted(names))
            waves_md.append(f"**Wave {wave}**: {wave_lines}")
        index_data = {
            "generated_at": _now_iso(),
            "kaos_version": self.kaos_version,
            "db_path": self.db_path,
            "agents": stats.agents,
            "skills": stats.skills,
            "memories": stats.memories,
            "checkpoints": stats.checkpoints,
            "log_entries": stats.log_entries,
            "waves_markdown": waves_md,
        }
        self._write_text("KAOS.md", render_index(index_data))

    def _export_dashboard(self) -> None:
        self._write_text("meta/dashboard.base", assets.DASHBOARD_BASE)

    # ── Helpers ─────────────────────────────────────────────────────

    def _group_by_wave(self) -> dict[int, list[str]]:
        groups: dict[int, list[str]] = {}
        for agent in self._agents_by_id.values():
            if agent["wave"] is None:
                continue
            groups.setdefault(agent["wave"], []).append(agent["name"])
        return groups

    def _write_text(self, relpath: str, content: str) -> None:
        """Write text to vault_path / relpath, creating parent dirs as needed."""
        full = self.vault_path / relpath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content, encoding="utf-8")


# ── Module-level helpers ────────────────────────────────────────────


def _pretty_json(raw: str | None) -> str:
    """Pretty-print a JSON string. Tolerates missing/invalid data."""
    if not raw:
        return "{}"
    try:
        return json.dumps(json.loads(raw), indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, TypeError):
        return str(raw)


def _safe_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(val, list):
        return [str(v) for v in val]
    return []


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
