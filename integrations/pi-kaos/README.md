# pi-kaos

A [Pi](https://pi.dev) extension that turns [KAOS](https://github.com/canivel/kaos)
into Pi's flight recorder and team memory. About 100 lines of TypeScript; every
hook shells out to the `kaos` CLI and is a silent no-op if KAOS is missing.

## Install

```bash
pip install 'kaos-harness'          # or: uv tool install kaos-harness
cd your-project && kaos init        # creates ./kaos.db

pi install npm:pi-kaos              # once published (see "Publishing" below)
# or, from a checkout:
pi install git:github.com/canivel/pi-kaos
```

Pi also auto-discovers `index.ts` if you copy it to `.pi/extensions/` (project) or
`~/.pi/agent/extensions/` (global). No build step: Pi runs TypeScript via jiti.

## What each hook does

| Pi event | KAOS call | Blocking? | Budget |
|---|---|---|---|
| `session_start` | `kaos journal append --agent pi --session <id> --event session_start --stdin` | yes | ≤ 450 ms |
| `before_agent_start` | `kaos memory search "<prompt[:120]>" -n 5 --rank weighted --format inject` → injected as a hidden `kaos-memory` message | yes | ≤ 450 ms |
| `tool_result` | `kaos journal append … --event tool_use --stdin` (tool name, input, is_error) | no | ≤ 450 ms |
| `turn_end` | `kaos journal append … --event turn_end --stdin` | no | ≤ 450 ms |
| `session_shutdown` | `kaos journal append … --event session_stop --stdin` | no | ≤ 450 ms |

Command: `/kaos-recall <query>` searches team memory and shows the result in Pi's UI.

The 450 ms cap is enforced by `spawnSync`'s `timeout`; a slow or missing `kaos` never
blocks Pi longer than that. Set `KAOS_BIN` to point at a specific binary (for example a
`uv tool` install that is not on `PATH`).

What you get afterwards, from the same `kaos.db`:

```bash
kaos query "SELECT event_type, COUNT(*) FROM events GROUP BY 1"   # audit = SQL
kaos memory search "stripe webhook" --rank weighted              # what actually worked
kaos dream consolidate --apply                                    # promote / prune
```

## Requirements

- KAOS ≥ 2.1 — `kaos journal append` and `memory search --format inject` ship in 2.1
  (roadmap M1). With 2.0.x installed the hooks run but journal nothing.
- Pi extension API as documented at <https://pi.dev/docs/latest/extensions>
  (`ExtensionAPI`, `pi.on`, `pi.registerCommand`, `ctx.sessionManager.getSessionId()`).

## Publishing (moving to its own repo)

Pi's ecosystem is npm/git packages, so this extension will live at
`github.com/canivel/pi-kaos` — the one deliberate exception to KAOS's
"one package" rule, because it is not a Python package.

```bash
gh repo create canivel/pi-kaos --public --source integrations/pi-kaos --push
cd integrations/pi-kaos && npm install && npm run typecheck
npm publish --access public          # then: pi install npm:pi-kaos
```

Until then, `pi install git:github.com/canivel/kaos` is **not** enough (the extension
is in a subdirectory); copy `index.ts` into `.pi/extensions/` instead.

MIT.
