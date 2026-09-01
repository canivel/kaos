# Tutorial 04 — KAOS MCP Server: Claude Manages Your Agents
**Duration:** 5 minutes  
**Level:** Intermediate  
**Goal:** Install the MCP server, connect it to Claude Code, and use Claude to spawn agents, read VFS files, and query the database — all from a conversation.

---

## SCENE 1 — Hook [0:00–0:20]

**[VISUAL: Claude Code conversation — user asks Claude to "run a parallel code review." Claude calls kaos tools, spawns agents, reads results, reports back — all inline.]**

> "What if Claude could directly manage your agent swarm? Spawn agents, read their files, query what they did — without you writing a single line of Python. That's what the KAOS MCP server enables. Let's wire it up."

---

## SCENE 2 — What MCP Is [0:20–0:50]

**[VISUAL: MCP architecture diagram — Claude ↔ MCP protocol ↔ KAOS server ↔ SQLite]**

> "MCP — Model Context Protocol — is a standard for giving LLMs access to external tools and data sources. KAOS exposes 18 tools over MCP. Claude calls them like any other tool — spawn, read, write, checkpoint, query. The MCP server runs locally and talks to your KAOS database."

---

## SCENE 3 — Install [0:50–1:40]

**[VISUAL: Two options — setup wizard (fast) and manual (for reference)]**

> "The easiest way is the setup wizard — it auto-installs everything."

```bash
kaos setup
# → picks your preset
# → generates kaos.yaml
# → writes the MCP config to ~/.claude/settings.json automatically
```

> "If you prefer to wire it manually, add this to your Claude Code settings:"

**[VISUAL: File `~/.claude/settings.json`]**
```json
{
  "mcpServers": {
    "kaos": {
      "command": "kaos",
      "args": ["serve", "--transport", "stdio"]
    }
  }
}
```

> "Then start the server — though with stdio transport, Claude Code starts it automatically when needed."

```bash
kaos serve --transport stdio
```

> "Restart Claude Code and you'll see the KAOS tools in the tools list."

---

## SCENE 4 — Using KAOS Tools in Claude [1:40–3:00]

**[VISUAL: Claude Code conversation, tool calls visible]**

> "Now let's see it in action. Open Claude Code and ask it to run a parallel code review."

**[VISUAL: User types to Claude]**

> User: "Use KAOS to run a parallel review of the auth module. Have one agent look for security issues and another check for performance problems."

**[VISUAL: Claude's response with tool calls shown inline]**

> Claude calls `mcp__kaos__agent_spawn` twice:

```
Tool: mcp__kaos__agent_spawn
{
  "name": "security-review",
  "prompt": "Review /src/auth.py for security vulnerabilities. Focus on injection, auth bypass, and session handling.",
  "config": {}
}
```

```
Tool: mcp__kaos__agent_spawn
{
  "name": "perf-review",  
  "prompt": "Review /src/auth.py for performance issues. Check for N+1 queries, blocking I/O, and redundant computation.",
  "config": {}
}
```

> "Both agents run. When they finish, Claude reads their outputs:"

```
Tool: mcp__kaos__agent_read
{ "agent_id": "01JQSEC...", "path": "/review.md" }
```

> "And summarizes the findings directly in the conversation — no switching to a terminal, no Python script."

---

## SCENE 5 — Key MCP Tools [3:00–3:50]

**[VISUAL: Tool reference table]**

> "KAOS exposes 18 tools over MCP. The most important ones:"

```
mcp__kaos__agent_spawn      — spawn a new agent with a prompt
mcp__kaos__agent_status     — check if an agent finished
mcp__kaos__agent_read       — read a file from an agent's VFS
mcp__kaos__agent_write      — write a file to an agent's VFS
mcp__kaos__agent_ls         — list files in an agent's VFS
mcp__kaos__agent_checkpoint — snapshot agent state
mcp__kaos__agent_restore    — roll back to a checkpoint
mcp__kaos__agent_query      — raw SQL against the KAOS database
mcp__kaos__agent_kill       — stop a running agent
mcp__kaos__agent_parallel   — spawn multiple agents at once
```

> "There are also meta-harness tools — `mh_start_search`, `mh_next_iteration`, `mh_submit_candidate` — which we'll cover in a dedicated tutorial."

---

## SCENE 6 — Querying From Claude [3:50–4:30]

**[VISUAL: Claude using agent_query to answer questions about the run]**

> "One of the most powerful tools is `agent_query` — it lets Claude run SQL against your KAOS database and answer questions like 'how much did that parallel run cost?'"

**[VISUAL: User message to Claude]**

> User: "How many tokens did the two review agents use?"

**[VISUAL: Claude calls `mcp__kaos__agent_query`]**

```
Tool: mcp__kaos__agent_query
{
  "sql": "SELECT a.name, SUM(tc.token_count) as tokens FROM agents a JOIN tool_calls tc ON a.agent_id = tc.agent_id WHERE a.name IN ('security-review', 'perf-review') GROUP BY a.agent_id"
}
```

**[VISUAL: Result and Claude's summary]**
```
security-review: 4,820 tokens
perf-review:     3,104 tokens
Total: 7,924 tokens (~$0.04 at Claude Haiku pricing)
```

---

## SCENE 7 — Summary [4:30–5:00]

**[VISUAL: Claude ↔ KAOS loop diagram]**

> "The MCP server turns KAOS into Claude's agent runtime. Claude spawns agents, reads results, queries the database, rolls back mistakes — all as tool calls, all from a conversation. The setup wizard wires it up automatically. Once connected, you never need to leave Claude Code to manage your agents.

Next tutorial: the audit trail — querying the event journal to understand exactly what your agents did, when, and in what order."

---

## AI VIDEO GENERATION NOTES
- **Voice tone:** Exciting demo energy. This is the most "wow" tutorial — lead with the demo.
- **Scene 4:** Show Claude's tool calls in a collapsible panel (like Claude Code's real UI). Expand them to show the JSON.
- **Speed:** The MCP call-response cycle should feel fast — don't add artificial pauses between tool call and result.
- **Callout in Scene 5:** Highlight `agent_parallel` and `agent_query` as the two most powerful tools besides spawn.
