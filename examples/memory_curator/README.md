# memory-curator

Probabilistic staleness triage for **Claude Code's native markdown memory dir**
(`~/.claude/projects/<project-slug>/memory/`): score every memory file, flag
archive candidates, and archive approved ones reversibly. Approval is always
required; nothing auto-deletes.

It's the KAOS **dream / consolidation** prune-decay idea (recency half-life +
soft, reversible removal — see `kaos/dream/phases/consolidation.py` and
`kaos/dream/signals.py`) ported to a store KAOS does **not** manage: Claude
Code's native `memory/*.md` + `MEMORY.md` index, as opposed to the `kaos.db`
FTS store. It's a standalone sidecar CLI — it does **not** import or modify the
`kaos` package.

## Why

Claude Code's per-project memory dir grows monotonically. Nothing ages out, so
the always-loaded `MEMORY.md` index drifts toward its size cap and stale facts
keep loading into every session's context. This tool gives that dir the same
"prune low-value, keep high-value, decay by recency" treatment KAOS gives skills.

## What's in here

- `curator.py` — the engine: scorer + reversible archiver + reject/cooldown + backfill + history. Read-only by default.
- `store.py` — persistent SQLite store (recall telemetry, score-run history, decisions). Lives at `<mem_dir>/.curator/memory_curator.db`.
- `recall_logger_hook.py` — optional `PostToolUse(Read)` hook that records real recall reads (see below).
- `THREAT_MODEL.md` — STRIDE review of the `--apply` mutation path.

## The probability model

Each memory gets a 0..1 sub-score on five dimensions; the composite `P(archive)`
decides verdict (`ARCHIVE` >= 0.70, `keep` < 0.40, else `watch`).

| Dimension | Direction | Signal |
|---|---|---|
| Staleness | up | age since mtime / latest in-body date, decayed on a type-dependent half-life |
| Completion | up | `DEPLOYED/RESOLVED/DONE/Phase N complete` markers (esp. `project` type) |
| Correctness | up | `SUPERSEDED/LEGACY/DECOMMISSIONED` markers + referenced filesystem paths that no longer exist |
| Durability | modifier | type prior: reference/user/feedback durable (damp), project ephemeral (amplify) |
| Re-use | down | MEASURED recall reads (telemetry) blended with a proxy (inbound `[[links]]` + recency) |

`P = clamp( w_stale*stale*(1-durability) + w_done*complete + w_incorrect*incorrect + orphan - w_reuse*reuse )`. Weights are hand-set defaults; tune for your corpus.

## Memory type priors

The model expects each memory's frontmatter to carry a `type` (`reference`,
`user`, `feedback`, `project`); untyped files get a neutral default. Priors set
how fast each type decays and how strongly staleness counts toward archival —
durable reference notes resist archival, ephemeral project notes don't.

## Re-use telemetry

Claude Code has **no native "memory recalled" hook event and no auto-recall
stream** for native memory files. Native memory = the always-loaded `MEMORY.md`
index + an explicit `Read` of a topic file. So the genuine "this memory was
actively pulled into context" signal is a **`Read` of a `memory/*.md` file**,
captured two ways:

- **Forward:** the `PostToolUse(Read)` hook (`recall_logger_hook.py`) logs each memory-file read to the store. Fail-open — never blocks or slows a Read.
- **Backfill:** `curator.py backfill` reconstructs historical reads from existing session transcripts, so there's real data on day one.

The canonical join key everywhere (telemetry, scoring, decisions) is the
**filename stem** — what the hook can see on disk — not the frontmatter `name:`,
which can differ.

### Wiring the hook (optional)

Add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          { "type": "command", "command": "python3 /abs/path/to/memory_curator/recall_logger_hook.py" }
        ]
      }
    ]
  }
}
```

The hook resolves `store.py` from its own directory by default (override with
`CURATOR_PKG`). Without the hook you still get the proxy re-use signal; `backfill`
seeds measured reads from transcripts either way.

## Usage

```
python3 curator.py report [--all]              # score + list candidates (read-only, default)
python3 curator.py backfill                     # seed telemetry from past transcripts
python3 curator.py archive <slug>...            # DRY-RUN the archive
python3 curator.py archive <slug>... --apply    # move (reversible: archived/ + ARCHIVE.md + index strike)
python3 curator.py reject  <slug>...            # cooldown — suppress from ARCHIVE on future runs
python3 curator.py history <slug>               # recall reads + decisions + score trend
python3 curator.py selftest                     # scoring + archive-path checks
```

It auto-detects the Claude Code memory dir for the current working directory.
Override with `CURATOR_MEM_DIR=/path/to/memory`.

## Relationship to KAOS

This deliberately does **not** depend on the `kaos` package — it's a sidecar, so
it runs even where KAOS isn't installed. Scoring is **deterministic arithmetic**,
so it does NOT spawn LLM sub-agents — that would be wrong for this workload. What
it borrows from KAOS is the *philosophy* of the dream/consolidation phase
(reversible prune, never hard-delete; recency half-life decay; persist decisions
so they accrue over weeks). Run it on a weekly cadence, or after a heavy session.

## Cooldown

`reject` records a decision; rejected candidates are held at `watch` (not
`ARCHIVE`) for the cooldown window so they don't re-nag every run until their
content materially changes.

## Not for

Not the `kaos.db` FTS memory store or any observation store — KAOS's own dream
cycle already curates those. This curates only the native Claude Code
`memory/*.md` + `MEMORY.md` index.
