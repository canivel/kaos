# Plugin: MCP tool pack that exports memory + skills to an Obsidian vault

Labels: good first issue, enhancement · Priority: P2

`kaos obsidian` exists as a CLI command, but nothing exposes the export to MCP clients
(Claude Code, Cursor) — a user in an editor can't say "export what the team learned this
sprint to my vault". This is a plugin-shaped task: one MCP tool pack, no core changes.

**What to build**

- Start from `contrib/plugin-template/`; publish as `kaos-plugin-obsidian`.
- `register(reg)` → `reg.add_mcp_tools([...], dispatch)` with two tools:
  `obsidian_export_memory(vault_path, since?)` and `obsidian_export_skills(vault_path)`.
- Reuse whatever `kaos/cli/main.py`'s `obsidian` command already does (import the
  function rather than copying it); write one Markdown note per memory/skill with
  front-matter (`key`, `type`, `agent_id`, `created_at`, plasticity stats when present).

**Done when**

- `kaos serve` lists both tools (`kaos plugins` shows the pack).
- A test runs `dispatch` against a temp `kaos.db` with two memories and asserts two
  `.md` files with front-matter.

Reported by AI agent
