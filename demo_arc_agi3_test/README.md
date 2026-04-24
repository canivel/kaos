# demo_arc_agi3_test — Full ARC-AGI-3 validation for Dream M1+M2+M3

End-to-end validation that **automatic neuroplasticity works on a realistic
ARC-AGI-3 meta-harness workload**. The scenario simulates evolving agent
strategies across a set of ARC games, capturing every plasticity signal
the live meta-harness search would produce:

- Harness candidates spawned as KAOS agents
- Skill templates applied per candidate (the strategy mutation points)
- Memory entries retrieved between generations
- Real failure patterns (compile errors, runtime exceptions, timeouts)
- Shared-log coordination (meta-harness proposer → candidate → decision)

Then it verifies the dream cycle captured it all **without any manual
`kaos dream run`** — plasticity must emerge inline from normal usage.

## Why a simulated search and not the real benchmark

The real ARC-AGI-3 meta-harness search requires:
- `arc-agi` SDK installed (optional external dependency)
- 15–30 minutes of wall-clock per pass (25s × 6 games × 10+ iterations)
- A configured LLM for the proposer (real API cost)

This validation must run in a CI-sized time budget (≤ 30s) with no
external deps. It uses KAOS's **real** primitives (`Kaos`, `SkillStore`,
`MemoryStore`, `SharedLog`, the dream module) against a handcrafted but
realistic ARC-AGI-3 workload — the kind of graph the live benchmark
would produce, but compressed into seconds.

If the `arc-agi` SDK happens to be installed, the scenario also runs a
single-game **smoke test** against the real benchmark to confirm wiring.
Missing SDK → smoke test skipped; main validation still runs.

## Reproduce

```bash
cd demo_arc_agi3_test
uv run python scenario.py
```

Exits 0 on success (every validation passed), non-zero otherwise.
Prints `[PASS]` / `[FAIL]` per check and a summary at the end.

## What the scenario plants

**6 ARC games** (matching the `n_search_games` default): `ls20`, `vc33`,
`ft09`, `gs50`, `ex01`, `hs45`. Each has realistic baseline_actions and
per-game `meta-harness` proposer → candidate cycles.

**7 strategy skills** — direct analogues of the real `arc_agi3.py` seeds:

| Skill | ARC-AGI-3 seed | Planted pattern |
|---|---|---|
| `random-fallback` | `SEED_RANDOM` | 5/15 success — a cold fallback |
| `systematic-click-sweep` | `SEED_SYSTEMATIC` | 12/15 success — hot |
| `productive-first-replay` | `SEED_PRODUCTIVE_FIRST` | 14/15 success — very hot |
| `click-nonzero-objects` | `SEED_CLICK_OBJECTS` | 10/15 success — solid |
| `bfs-state-exploration` | (novel mutation) | 2/8 success — prune candidate |
| `color-match-pattern` | (novel mutation) | 0/0 — never tried, cold |
| `corner-tap-heuristic` | (novel mutation, near-duplicate of systematic) | used to test merge detection |

**5 memory entries** — ARC-AGI-3 domain knowledge:
- `rhae-formula`: retrieved many times (hot)
- `action-6-requires-data`: retrieved several times
- `frame-hash-dedup-pattern`: retrieved when debugging loops
- `level-reset-on-game-over`: retrieved rarely
- `obsolete-action-5-note`: retrieved once (cold)

**Failure fingerprints** — realistic meta-harness mutation bugs:
- `KeyError: 'tried_actions'` (×3 identical — tests fingerprint merging)
- `TypeError: click requires data` (×2 identical)
- `Timeout exceeded 120s` (×1)

**Shared-log policy candidate**: 3 cycles of `intent("promote productive-first")`,
all approved — must become an auto-promoted policy.

## What it validates

Every dream capability:

| Category | Checks |
|---|---|
| Schema v5 | all 4 new tables + 3 new agent_skills columns present |
| Auto hooks — skills | Hebbian associations built per co-used skill pair |
| Auto hooks — memory | Co-retrieved memories + cross-modal skill↔memory edges |
| Auto hooks — failures | Fingerprints captured on `fail()`, duplicates merged |
| Auto hooks — threshold | Consolidation triggers at KAOS_DREAM_THRESHOLD crossing |
| Episode signals | One row per agent, success/fail flag, token counts |
| Consolidation | Promote (hot memory → skill), prune (low-success skill), merge (near-duplicate) |
| Policies | Repeated approved intent promoted to `policies` table |
| Weighted search | Productive-first ranks ahead of random under `rank="weighted"` |
| Digest narrative | Contains all sections + real content (no "no entries") |

Total: ~30 validations. All must pass for the scenario to exit 0.
