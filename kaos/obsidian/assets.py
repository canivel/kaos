"""Static asset content for the exported vault — `.obsidian/` config + CSS snippet.

Everything here is a plain string constant so we don't need file-based templates
or any packaging resources. The exporter writes these to the vault on init.
"""

from __future__ import annotations


APP_JSON = """{
  "attachmentFolderPath": "Attachments",
  "newFileLocation": "folder",
  "newFileFolderPath": "Inbox",
  "promptDelete": true,
  "alwaysUpdateLinks": true,
  "useMarkdownLinks": false,
  "newLinkFormat": "shortest",
  "showInlineTitle": true,
  "showUnsupportedFiles": false
}
"""

APPEARANCE_JSON = """{
  "enabledCssSnippets": ["kaos"],
  "showViewHeader": true,
  "accentColor": "#00cec9"
}
"""

# Graph view: color nodes by folder, giving KAOS entities distinct colors.
GRAPH_JSON = """{
  "collapse-filter": false,
  "search": "",
  "showTags": true,
  "showAttachments": false,
  "hideUnresolved": false,
  "showOrphans": true,
  "collapse-color-groups": false,
  "colorGroups": [
    {"query": "path:Agents", "color": {"a": 1, "rgb": 36817}},
    {"query": "path:Skills", "color": {"a": 1, "rgb": 1638655}},
    {"query": "path:Memory", "color": {"a": 1, "rgb": 16606120}},
    {"query": "path:Checkpoints", "color": {"a": 1, "rgb": 16761411}},
    {"query": "path:Sessions", "color": {"a": 1, "rgb": 11382256}},
    {"query": "path:VFS", "color": {"a": 1, "rgb": 7900153}}
  ],
  "collapse-display": false,
  "showArrow": false,
  "textFadeMultiplier": 0,
  "nodeSizeMultiplier": 1,
  "lineSizeMultiplier": 1,
  "collapse-forces": false,
  "centerStrength": 0.5,
  "repelStrength": 10,
  "linkStrength": 1,
  "linkDistance": 250,
  "scale": 1,
  "close": true
}
"""

# CSS snippet — goes in .obsidian/snippets/kaos.css
KAOS_CSS = """/* KAOS vault color scheme — matches the KAOS brand palette.
 * Enable under Settings → Appearance → CSS snippets → kaos
 */

/* File tree color by folder */
.nav-folder-title[data-path^="Agents"]        { color: #00e676; }
.nav-folder-title[data-path^="Skills"]        { color: #00cec9; }
.nav-folder-title[data-path^="Memory"]        { color: #fd79a8; }
.nav-folder-title[data-path^="Checkpoints"]   { color: #ffd166; }
.nav-folder-title[data-path^="Sessions"]      { color: #a29bfe; }
.nav-folder-title[data-path^="VFS"]           { color: #6c5ce7; }
.nav-folder-title[data-path^="Log"]           { color: #e3b341; }

/* Frontmatter keys in reading view */
.metadata-property[data-property-key="agent_id"] .metadata-property-key,
.metadata-property[data-property-key="skill_id"] .metadata-property-key,
.metadata-property[data-property-key="memory_id"] .metadata-property-key,
.metadata-property[data-property-key="checkpoint_id"] .metadata-property-key {
  color: #6c5ce7;
  font-family: var(--font-monospace);
}

/* Callouts used by KAOS templates */
.callout[data-callout="kaos-wave"] {
  --callout-color: 0, 230, 118;
  --callout-icon: flame;
}
.callout[data-callout="kaos-skill"] {
  --callout-color: 0, 206, 201;
  --callout-icon: sparkles;
}
.callout[data-callout="kaos-memory"] {
  --callout-color: 253, 121, 168;
  --callout-icon: brain;
}
"""

# A Bases dashboard — Obsidian's native query system (requires Obsidian 1.9+).
# Shows one table per major entity with sort/filter.
DASHBOARD_BASE = """filters:
  and: []
properties:
  note.type:
    displayName: Type
  note.status:
    displayName: Status
  note.wave:
    displayName: Wave
  note.created_at:
    displayName: Created
views:
  - type: table
    name: Agents
    filters:
      and:
        - note.type == "agent"
    order:
      - file.name
      - note.wave
      - note.status
      - note.created_at
  - type: table
    name: Skills
    filters:
      and:
        - note.type == "skill"
    order:
      - file.name
      - note.use_count
      - note.success_count
      - note.created_at
  - type: table
    name: Memory
    filters:
      and:
        - note.type == "memory"
    order:
      - file.name
      - note.memory_type
      - note.source_agent
      - note.created_at
  - type: table
    name: Checkpoints
    filters:
      and:
        - note.type == "checkpoint"
    order:
      - file.name
      - note.source_agent
      - note.created_at
"""

# README shown in the root of the vault to orient Obsidian users.
VAULT_README = """# Welcome to your KAOS vault

This vault is a **one-way export** from a KAOS SQLite database. Every agent,
skill, memory entry, checkpoint, and shared-log entry is a note. Every cross-
reference is a real wikilink, so you can open the [graph
view](obsidian://graph) and see your engagement laid out as a network.

## Where things live

- **`Agents/`** — one note per agent, with wave number, status, loaded skills,
  and backlinks from the memories/checkpoints that reference them.
- **`Skills/`** — one note per skill template. Backlinks show which agents
  wrote the skill and which projects applied it.
- **`Memory/`** — one note per memory entry, grouped by type
  (`observation`, `result`, `insight`, `error`, `skill`). Backlinks show the
  agent that wrote each one.
- **`Checkpoints/`** — one note per checkpoint, grouped by agent.
- **`Sessions/`** — one note per session (grouped by date).
- **`Log.md`** — shared LogAct coordination log (intent → vote → decide).
- **`meta/dashboard.base`** — a Bases dashboard with queries per entity
  type (requires Obsidian 1.9+).

## Regenerating

This vault was generated by `kaos obsidian export`. Re-run the same command to
refresh it — the exporter overwrites generated notes but preserves your
`.obsidian/workspace*` state. Pass `--clean` to wipe and re-export.

## Tips

- Turn on the **`kaos`** CSS snippet under Settings → Appearance → CSS
  snippets to get the color scheme.
- Open **`meta/dashboard.base`** for one-click filtering across all entities.
- Hit **Ctrl/Cmd+G** to open the graph view — color groups are preconfigured
  per folder.
"""
