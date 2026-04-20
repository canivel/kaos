"""String templates for each KAOS entity rendered as an Obsidian note.

All templates take plain dicts (row data + pre-resolved wikilinks) and return
a markdown string. They are pure functions — no I/O, no DB access — so they
can be tested in isolation.
"""

from __future__ import annotations

from typing import Any

from kaos.obsidian.renderer import (
    bullet_list,
    code_block,
    frontmatter,
    short_id,
    tag_list,
    wikilink,
)


def render_agent(agent: dict[str, Any], links: dict[str, list[str]]) -> str:
    """Render one agent note.

    `agent` is a row from the agents table (dict-style).
    `links` has keys: skills (list of skill wikilinks), memories (list of memory
    wikilinks), checkpoints (list of checkpoint wikilinks).
    """
    wave = agent.get("wave")
    tags = ["agent", f"status-{agent['status']}"]
    if wave is not None:
        tags.append(f"wave-{wave}")

    fm = frontmatter({
        "type": "agent",
        "agent_id": agent["agent_id"],
        "name": agent["name"],
        "status": agent["status"],
        "wave": wave if wave is not None else "",
        "created_at": agent["created_at"],
        "parent_id": agent.get("parent_id") or "",
        "tags": tag_list(tags),
    })

    body = [
        fm,
        f"# {agent['name']}",
        "",
        f"> [!kaos-wave] Wave {wave if wave is not None else '?'} · `{agent['status']}`",
        f"> Agent ID: `{agent['agent_id']}`",
        f"> Short: `{short_id(agent['agent_id'])}`",
        "",
        "## Skills loaded",
        bullet_list(links.get("skills", [])),
        "",
        "## Memory entries written",
        bullet_list(links.get("memories", [])),
        "",
        "## Checkpoints",
        bullet_list(links.get("checkpoints", [])),
        "",
        "## Config",
        code_block(agent.get("config_pretty", "{}"), "json"),
    ]
    return "\n".join(body)


def render_skill(skill: dict[str, Any], links: dict[str, list[str]]) -> str:
    """Render one skill template note."""
    tags = tag_list(["skill"] + (skill.get("tags_list") or []))
    source_link = links.get("source_agent") or ""
    success_rate = _success_rate(skill["use_count"], skill["success_count"])

    fm = frontmatter({
        "type": "skill",
        "skill_id": skill["skill_id"],
        "name": skill["name"],
        "source_agent": source_link,
        "use_count": skill["use_count"],
        "success_count": skill["success_count"],
        "success_rate": success_rate if success_rate is not None else "",
        "created_at": skill["created_at"],
        "updated_at": skill["updated_at"],
        "tags": tags,
    })

    body = [
        fm,
        f"# {skill['name']}",
        "",
        f"> [!kaos-skill] {skill['description']}",
        f"> Source: {source_link or '_unknown_'}  ·  use_count: {skill['use_count']}"
        + (f"  ·  success rate: {int(success_rate * 100)}%" if success_rate is not None else ""),
        "",
        "## Template",
        code_block(skill["template"]),
        "",
        "## Applied by",
        bullet_list(links.get("applied_by", []),
                    empty="_(no recorded applications yet)_"),
    ]
    return "\n".join(body)


def render_memory(entry: dict[str, Any], links: dict[str, list[str]]) -> str:
    """Render one memory note."""
    tags = tag_list(["memory", f"memory-{entry['type']}"])
    source_link = links.get("source_agent") or ""
    key = entry.get("key") or f"memory-{entry['memory_id']}"

    fm = frontmatter({
        "type": "memory",
        "memory_id": entry["memory_id"],
        "memory_type": entry["type"],
        "key": key,
        "source_agent": source_link,
        "created_at": entry["created_at"],
        "tags": tags,
    })

    body = [
        fm,
        f"# {key}",
        "",
        f"> [!kaos-memory] {entry['type']} · by {source_link or '_unknown_'}",
        "",
        entry["content"],
    ]
    if entry.get("metadata_pretty") and entry["metadata_pretty"] != "{}":
        body += ["", "## Metadata", code_block(entry["metadata_pretty"], "json")]
    return "\n".join(body)


def render_checkpoint(cp: dict[str, Any], links: dict[str, list[str]]) -> str:
    """Render one checkpoint note."""
    source_link = links.get("source_agent") or ""
    label = cp.get("label") or cp["checkpoint_id"]

    fm = frontmatter({
        "type": "checkpoint",
        "checkpoint_id": cp["checkpoint_id"],
        "label": label,
        "source_agent": source_link,
        "created_at": cp["created_at"],
        "tags": tag_list(["checkpoint"]),
    })

    body = [
        fm,
        f"# {label}",
        "",
        f"Agent: {source_link or '_unknown_'}  ·  Checkpoint `{cp['checkpoint_id']}`",
        "",
        "## File manifest",
        code_block(cp.get("file_manifest_pretty", "[]"), "json"),
        "",
        "## State snapshot",
        code_block(cp.get("state_snapshot_pretty", "{}"), "json"),
    ]
    return "\n".join(body)


def render_log_entry(entry: dict[str, Any], links: dict[str, list[str]]) -> str:
    """Render a single shared-log entry as a one-line markdown bullet.

    The full log is rendered as one `Log.md` file; each entry becomes a line
    in a chronological list. Also returns the target wikilink it references
    (e.g. an intent referenced by a vote) so we can add backlinks later.
    """
    source_link = links.get("source_agent") or f"`{short_id(entry['agent_id'])}`"
    ref_link = links.get("ref") or ""
    marker = {
        "intent": "🎯",
        "vote": "🗳️",
        "decision": "✅",
        "commit": "📝",
        "result": "📊",
        "abort": "⛔",
        "policy": "📜",
        "mail": "✉️",
    }.get(entry["type"], "•")

    payload_preview = ""
    payload_s = entry.get("payload_pretty", "")
    if payload_s and payload_s not in ("{}", "null"):
        first_line = payload_s.splitlines()[0][:120]
        payload_preview = f" — `{first_line}`"

    ref_part = f" → {ref_link}" if ref_link else ""
    return (
        f"- {marker} **{entry['type']}** "
        f"`#{entry['position']}` {source_link}{ref_part}"
        f"  <span style='color:var(--text-muted)'>{entry['created_at']}</span>"
        f"{payload_preview}"
    )


def render_index(stats: dict[str, Any]) -> str:
    """Render the root index note (KAOS.md)."""
    fm = frontmatter({
        "type": "index",
        "generated_at": stats["generated_at"],
        "kaos_version": stats["kaos_version"],
        "db": stats["db_path"],
        "tags": tag_list(["index"]),
    })

    body = [
        fm,
        "# KAOS engagement",
        "",
        f"Generated from `{stats['db_path']}` at `{stats['generated_at']}`.",
        "",
        "## Contents",
        f"- **{stats['agents']}** agents → `Agents/`",
        f"- **{stats['skills']}** skills → `Skills/`",
        f"- **{stats['memories']}** memory entries → `Memory/`",
        f"- **{stats['checkpoints']}** checkpoints → `Checkpoints/`",
        f"- **{stats['log_entries']}** shared-log entries → `Log.md`",
        "",
        "## Waves",
        bullet_list(stats.get("waves_markdown", []),
                    empty="_(agents were not grouped into waves in metadata)_"),
        "",
        "## Dashboard",
        "",
        "Open [[meta/dashboard|dashboard]] (Bases) for filterable tables per entity type.",
        "",
        "## Graph view",
        "",
        "Press **Ctrl/Cmd+G** to open the graph. Color groups are preconfigured:",
        "- 🟢 Agents  🟦 Skills  🟪 Memory  🟡 Checkpoints  🟣 Sessions",
    ]
    return "\n".join(body)


def render_log_file(lines: list[str], total: int) -> str:
    """Wrap the list of per-entry bullet lines into a Log.md file."""
    fm = frontmatter({
        "type": "log",
        "entries": total,
        "tags": tag_list(["log"]),
    })
    if not lines:
        return fm + "# Shared coordination log\n\n_(no entries)_\n"
    return fm + f"# Shared coordination log\n\n{total} entries · newest first\n\n" + "\n".join(reversed(lines)) + "\n"


def _success_rate(use_count: int, success_count: int) -> float | None:
    """Return success rate in [0, 1] or None if no uses recorded."""
    if not use_count:
        return None
    return max(0.0, min(1.0, success_count / use_count))
