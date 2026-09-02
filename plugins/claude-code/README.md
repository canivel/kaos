# KAOS for Claude Code

A flight recorder and team memory for Claude Code. Every session becomes an
auditable KAOS agent in one SQLite file; the lessons your team saved come back
at session start.

## Install

```
claude plugin marketplace add canivel/kaos
/plugin install kaos@kaos
```

The plugin needs the `kaos-harness` package for the hook entrypoint:

```
pip install kaos-harness          # or: uv tool install kaos-harness
```

No marketplace? `kaos connect claude-code` writes the same hooks and MCP server
into `.claude/settings.json` + `.mcp.json` in the current project.

## What it does

| Claude Code event | KAOS | Latency (p95, measured) |
|---|---|---|
| `SessionStart` | creates agent `claude-code:<session>`, journals the start, injects up to 5 weighted-ranked memories about this project | 241 ms |
| `UserPromptSubmit` | journals the prompt; memory injection **off by default** (275 ms failed its 200 ms gate — see `benchmarks/cc_hook_latency`) | — |
| `PostToolUse` (async) | records the tool call in `tool_calls` + journal; `file_write` / `file_read` events for Edit/Write/Read | background |
| `Stop` (async) | journals the turn; runs `kaos dream consolidate --apply` at most every 30 min | background |
| `SessionEnd` (async) | marks the agent completed | background |
| MCP | the 58-tool KAOS server (`kaos serve`) is registered automatically | — |
| `/kaos:recall <query>` | skill: search team memory (weighted rank) and record which hits were useful | — |

Where it writes: `./kaos.db` if the project already has one, otherwise
`~/.kaos/claude-code.db`. Override with `KAOS_DB`.

## Look at what happened

```
kaos ls                                           # every session is an agent
kaos query "SELECT tool_name, COUNT(*) FROM tool_calls GROUP BY 1"
kaos logs <agent-id>                              # the journal
kaos memory search "double charge" --rank weighted
kaos ui                                           # dashboard
```

## Turn on prompt-time recall

```
kaos connect claude-code --prompt-inject     # writes ~/.kaos/hook.json {"prompt_inject": true}
# or per shell: export KAOS_HOOK_PROMPT_INJECT=1
```

Debugging: `KAOS_HOOK_DEBUG=1` prints timings and tracebacks to stderr. Hooks
never block a session — any failure exits 0 silently.
