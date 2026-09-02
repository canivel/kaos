# Plugin: realistic seed datasets for `kaos demo` (`kaos-plugin-demodata`)

Labels: good first issue, enhancement · Priority: P2

`kaos demo` seeds one built-in scenario (code-review swarm, parallel refactors, failed
migrations). Newcomers evaluating KAOS for *their* domain — data pipelines, incident
response, research agents — would understand it faster with a scenario that looks like
their work. Make scenarios pluggable and contribute two.

**What to build**

- A plugin (`contrib/plugin-template/` as the base) that registers an MCP tool pack
  `demo_seed_<scenario>(db_path)` — the plugin surface has no "demo scenario" hook, so
  the tool-pack route needs zero core changes; if you'd rather add
  `add_demo_scenario(name, fn)` to `kaos/plugins.py`, open that as a small separate PR.
- Two scenarios, each seeding agents, VFS files, tool calls, memories and a few skill
  outcomes so `kaos ui`, `kaos memory search --rank weighted` and
  `kaos dream consolidate` all have something to show:
  `incident-response` (on-call swarm, one flaky runbook skill) and
  `etl-pipeline` (schema drift caught by a review agent).
- Deterministic (seeded RNG) so screenshots and docs are reproducible.

**Done when** `uv run kaos plugins` lists the pack, and a test seeds a temp db and asserts
agent/memory/skill counts.

Reported by AI agent
