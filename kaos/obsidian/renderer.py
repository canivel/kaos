"""Markdown rendering helpers — frontmatter, wikilinks, safe filenames."""

from __future__ import annotations

import json
import re
from typing import Any


# Obsidian treats these characters as illegal or problematic in filenames
# (on disk AND in wikilinks). We strip them.
_UNSAFE_CHARS = re.compile(r"[\\/:*?\"<>|\[\]#^]")


def safe_filename(name: str) -> str:
    """Make a string safe to use as an Obsidian note filename.

    Keeps case; replaces unsafe characters with "-"; collapses runs of "-".
    """
    cleaned = _UNSAFE_CHARS.sub("-", name.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    return cleaned or "unnamed"


def wikilink(target: str, alias: str | None = None) -> str:
    """Render a wikilink. target is the note name (without .md)."""
    target = safe_filename(target)
    if alias and alias != target:
        return f"[[{target}|{alias}]]"
    return f"[[{target}]]"


def frontmatter(data: dict[str, Any]) -> str:
    """Render a dict as YAML frontmatter block (+trailing blank line).

    Uses YAML-compatible serialization:
      - strings with special chars are quoted
      - lists are rendered inline: [a, b, c]
      - nested dicts are flattened with dotted keys (keeps it Dataview-friendly)
    """
    lines = ["---"]
    for key, value in data.items():
        lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _yaml_scalar(value: Any) -> str:
    """Render a single YAML value."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        rendered = ", ".join(_yaml_scalar(v) for v in value)
        return f"[{rendered}]"
    if isinstance(value, dict):
        # Flatten into a one-line JSON-ish form for simplicity
        return json.dumps(value, ensure_ascii=False)
    s = str(value)
    # Quote if it contains YAML-sensitive characters or starts with reserved tokens
    if not s:
        return '""'
    if any(ch in s for ch in ':#{}[],&*!|>%@`') or s[0] in "-?" or s.lower() in ("yes", "no", "true", "false", "null"):
        escaped = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    # Preserve newlines via block scalar
    if "\n" in s:
        indented = "\n    ".join(s.splitlines())
        return f"|-\n    {indented}"
    return s


def tag_list(tags: list[str]) -> list[str]:
    """Normalise a list of tags for Obsidian (no leading #, lowercase, hyphens)."""
    result: list[str] = []
    for t in tags:
        if not t:
            continue
        t = str(t).strip().lstrip("#")
        t = re.sub(r"\s+", "-", t)
        t = t.lower()
        if t:
            result.append(t)
    return result


def bullet_list(items: list[str], empty: str = "_(none)_") -> str:
    """Render a markdown bullet list, or a placeholder if empty."""
    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)


def code_block(content: str, lang: str = "") -> str:
    """Render a fenced code block, escaping any existing fences safely."""
    if "```" in content:
        # Bump fence length so inner fences remain literal
        return f"````{lang}\n{content}\n````"
    return f"```{lang}\n{content}\n```"


def short_id(agent_id: str, n: int = 6) -> str:
    """Return the last N chars of an agent_id for readable short references."""
    return agent_id[-n:] if len(agent_id) > n else agent_id
