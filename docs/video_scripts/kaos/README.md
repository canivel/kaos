# KAOS Video Tutorial Series

8 scripts × 5 minutes each. Beginner through advanced.

## Series Map

| # | File | Topic | Level | Key Concepts |
|---|------|-------|-------|--------------|
| 01 | [01_kaos_getting_started.md](01_kaos_getting_started.md) | Install, spawn, VFS isolation | Beginner | `Kaos()`, `spawn`, `write`, `read`, `set_state` |
| 02 | [02_kaos_checkpoints.md](02_kaos_checkpoints.md) | Checkpoint & surgical rollback | Beginner–Int | `checkpoint`, `restore`, `diff_checkpoints` |
| 03 | [03_kaos_parallel_agents.md](03_kaos_parallel_agents.md) | Parallel agents + GEPA router | Intermediate | `ccr.run_parallel`, GEPA classification, SQL cost queries |
| 04 | [04_kaos_mcp_server.md](04_kaos_mcp_server.md) | MCP server + Claude integration | Intermediate | `kaos serve`, 18 MCP tools, `agent_spawn`, `agent_query` |
| 05 | [05_kaos_audit_trail.md](05_kaos_audit_trail.md) | Event journal & SQL queries | Intermediate | event journal, token tracking, failure queries, `kaos search` |
| 06 | [06_kaos_meta_harness.md](06_kaos_meta_harness.md) | Meta-Harness autonomous search | Advanced | `mh search`, Pareto frontier, harness interface, knowledge base |
| 07 | [07_kaos_coral_coevolution.md](07_kaos_coral_coevolution.md) | CORAL co-evolution system | Advanced | skills, pivot prompts, hub sync, stagnation cooldown |
| 08 | [08_kaos_custom_benchmark.md](08_kaos_custom_benchmark.md) | Build a custom benchmark | Advanced | `Benchmark` interface, `score()`, multi-objective, registry |

---

## Script Format

Each script uses a consistent format designed for AI video generators (Synthesia, HeyGen, Runway, Pictory, etc.):

- **`[VISUAL: ...]`** — on-screen content (code, diagram, animation, terminal)
- **`> "..."`** — narration (spoken by presenter/avatar)
- **Code blocks** — shown on screen, animated character by character
- **Timestamps** — each scene has `[MM:SS–MM:SS]` marks for pacing
- **`## AI VIDEO GENERATION NOTES`** — generator-specific instructions at end of each script

---

## Recommended Paths

| Goal | Watch |
|------|-------|
| Just getting started | 01 → 02 |
| Building a multi-agent app | 01 → 02 → 03 → 05 |
| Using with Claude Code | 01 → 04 |
| Running autonomous optimization | 01 → 06 → 07 |
| Full series | 01 → 02 → 03 → 04 → 05 → 06 → 07 → 08 |

---

## Using These Scripts as KAOS Inputs

Each script can be fed directly to a KAOS agent running a video generation pipeline:

```python
from kaos import Kaos

db = Kaos("video_gen.db")

import os
script_dir = "video_scripts/kaos"

for fname in sorted(os.listdir(script_dir)):
    if not fname.endswith(".md") or fname == "README.md":
        continue

    with open(f"{script_dir}/{fname}") as f:
        script = f.read()

    agent_id = db.spawn(f"video-gen-{fname[:2]}", config={"script": fname})
    db.write(agent_id, "/script.md", script.encode())
    db.set_state(agent_id, "status", "ready_for_generation")

# Now run agents in parallel through your video generation pipeline
```
