"""``kaos connect <target>`` — wire KAOS into a tool you already run.

The Claude Code marketplace plugin (``plugins/claude-code``) is the preferred
path; this is the no-marketplace fallback that writes the same hooks and MCP
server into ``.claude/settings.json`` (project) or ``~/.claude/settings.json``
(user). Idempotent: existing KAOS entries are replaced, everything else in the
files is preserved.
"""
from __future__ import annotations

import json
from pathlib import Path

HOOK_MARK = "kaos-hook"

# Same events, timeouts and async flags as plugins/claude-code/hooks/hooks.json —
# tests assert the two stay in sync.
HOOK_SPEC: list[tuple[str, str, int, bool]] = [
    ("SessionStart", "session-start", 5, False),
    ("UserPromptSubmit", "prompt", 3, False),
    ("PostToolUse", "tool", 10, True),
    ("Stop", "stop", 120, True),
    ("SessionEnd", "session-end", 10, True),
]


def hooks_block(command_prefix: str = "kaos-hook") -> dict:
    out: dict = {}
    for event, sub, timeout, is_async in HOOK_SPEC:
        entry: dict = {"type": "command", "command": f"{command_prefix} {sub}", "timeout": timeout}
        if is_async:
            entry["async"] = True
        out[event] = [{"hooks": [entry]}]
    return out


def _merge_hooks(settings: dict, ours: dict) -> dict:
    hooks = settings.setdefault("hooks", {})
    for event, groups in ours.items():
        existing = [g for g in hooks.get(event, [])
                    if not any(HOOK_MARK in h.get("command", "") for h in g.get("hooks", []))]
        hooks[event] = existing + groups
    return settings


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")


def connect_claude_code(root: Path, scope: str = "project", prompt_inject: bool = False,
                        home: Path | None = None) -> dict:
    root = Path(root).resolve()
    home = Path(home) if home else Path.home()
    written: list[str] = []

    settings_path = (root / ".claude" / "settings.json") if scope == "project" else (home / ".claude" / "settings.json")
    settings = _merge_hooks(_read_json(settings_path), hooks_block())
    _write_json(settings_path, settings)
    written.append(str(settings_path))

    if scope == "project":
        mcp_path = root / ".mcp.json"
        mcp = _read_json(mcp_path)
        mcp.setdefault("mcpServers", {})["kaos"] = {"command": "kaos", "args": ["serve", "--transport", "stdio"]}
        _write_json(mcp_path, mcp)
        written.append(str(mcp_path))

    if prompt_inject:
        kaos_home = home / ".kaos"
        cfg_path = kaos_home / "hook.json"
        cfg = _read_json(cfg_path)
        cfg["prompt_inject"] = True
        _write_json(cfg_path, cfg)
        written.append(str(cfg_path))

    return {
        "target": "claude-code",
        "scope": scope,
        "written": written,
        "prompt_inject": prompt_inject,
        "next": ("Start a Claude Code session in this project: it is journaled into kaos.db "
                 "(or ~/.kaos/claude-code.db) and team memory is recalled at session start. "
                 "Inspect with `kaos ls`, `kaos query \"SELECT tool_name, COUNT(*) FROM tool_calls GROUP BY 1\"`."),
    }
