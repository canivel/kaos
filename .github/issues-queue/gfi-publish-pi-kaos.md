# Publish `pi-kaos` (Pi extension) to npm from its own repo

Labels: good first issue, enhancement · Priority: P2

`integrations/pi-kaos/` holds a ~100-line TypeScript Pi extension (journals sessions
into `kaos.db`, injects weighted memory before each turn, `/kaos-recall`). Pi's ecosystem
is npm/git packages, so it needs to live in `canivel/pi-kaos` and be installable with
`pi install npm:pi-kaos`. Needs someone with Node + a Pi install to finish it.

**What to do**

1. `npm install && npm run typecheck` in `integrations/pi-kaos/` against the current
   `@earendil-works/pi-coding-agent` types; fix any drift from the documented
   `ExtensionAPI` (event names `session_start`, `before_agent_start`, `tool_result`,
   `turn_end`, `session_shutdown`; `ctx.sessionManager.getSessionId()`).
2. Smoke-test in a real Pi session with KAOS ≥ 2.1 (`kaos journal append` and
   `kaos memory search --format inject` are the two CLI verbs it calls) — confirm rows
   land in `kaos.db` and the injected `kaos-memory` message appears.
3. Split into `canivel/pi-kaos` (maintainer will create the repo), `npm publish`,
   and update the README install line.

**Done when** `pi install npm:pi-kaos` works on a clean machine and one session leaves
`session_start` / `tool_use` / `turn_end` rows in `kaos.db`.

Reported by AI agent
