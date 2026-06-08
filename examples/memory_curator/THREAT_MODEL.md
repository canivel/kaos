# Threat Model: memory-curator

## Overview
- **Target:** `curator.py` + `store.py` + `recall_logger_hook.py` — probabilistic staleness triage for Claude Code's native memory dir
- **Stack:** local Python 3 CLI + SQLite + a PostToolUse(Read) hook (no network, no server, no auth surface)
- **Scope:** the `--apply` mutation path (the only thing that writes user data)

## Change Summary
A CLI that reads every `~/.claude/.../memory/*.md`, scores each across five dimensions, and — behind an explicit `--apply` flag — moves stale files into `archived/`, appends a digest to `ARCHIVE.md`, and strikes the corresponding line from `MEMORY.md`. Read-only by default; nothing is ever deleted.

## Trust model (why the usual STRIDE surfaces mostly don't apply)
No network, no listener, no auth, no secrets handled, single local user. So Spoofing / Repudiation-of-identity / network-DoS / privilege-escalation are largely N/A. The **real** trust boundaries are:
1. **Memory file *content* → script logic** — memory files can be written automatically by Claude from external/untrusted material (ticket bodies, web content). Content is therefore semi-untrusted input.
2. **Script → user's filesystem** — the `--apply` path mutates and moves the user's canonical memory index. The principal risk is *the tool corrupting or losing the very data it's meant to curate.*

## Data Flow
```
memory/*.md ─(read)→ parse frontmatter+body ─→ score ─→ report (stdout, read-only)
                                                   │
                         user passes approved slugs ▼  (--apply only)
              os.rename → archived/ → ARCHIVE.md (append digest) → MEMORY.md (strike line)
```

## STRIDE Analysis

### Tampering / Integrity  (the load-bearing category here)
| # | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| T1 | **Over-broad index-line strike.** A naive `_strike_index_line` that drops every MEMORY.md line *containing the filename as a substring* would, if one filename is a substring of another (`axiom.md` ⊂ `project_axiom.md`), silently delete the longer one's index line too. | Medium | High | **FIXED** — match the markdown link target exactly: `](<name>)`, not `name in line`. Regression-tested in `selftest`. |
| T2 | **Non-atomic archive.** If the order were digest-write → index-strike → `os.rename` and `rename` failed (dest exists, perms, EXDEV), ARCHIVE.md + MEMORY.md would already be mutated but the file never moved → inconsistent state, no rollback. | Low | High | **FIXED** — `os.rename` runs **first**; only on success are the digest + index written. Skip-if-dest-exists guard. |
| T3 | **ARCHIVE.md digest injection.** `slug`/`reasons` derive from file content; a frontmatter `name:` containing a newline/markdown could inject forged lines or a misleading `[restore: …]` path into the durable audit log. | Low | Medium | **FIXED** — strip newlines + backticks from `slug` before writing the digest; clamp length. |

### Information Disclosure
| # | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| I1 | Tool echoes sensitive memory content to stdout/logs. | Low | Medium | **Good:** report prints only slug + scores + computed reasons; never the body or `description`. `PATH_RE` only calls `.exists()`, never reads referenced files. Keep the no-body-echo invariant if reasons ever expand. |

### Denial of Service
| # | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| D1 | Pathological/huge memory file or ReDoS slows the run. | Low | Low | Regexes are linear (no nested quantifiers); corpus is typically a few hundred small files. Optional: cap per-file read size. |

### Elevation of Privilege / Spoofing
| # | Threat | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| E1 | `CURATOR_MEM_DIR` points the tool (and `--apply`) at an unintended directory, moving unrelated `*.md`. | Low | Medium | **FIXED** — `--apply` refuses a target dir with no `MEMORY.md`. Report is read-only; `--apply` needs explicit slugs. |
| E2 | Path traversal via user-supplied slug → write outside dir. | Low | High | **Good (already mitigated):** slugs only resolve to already-globbed real files; dest is `archive_dir/<basename>` with a `startswith(archive_dir)` guard. |

## Telemetry components

| # | Component | Threat | Likelihood | Impact | Mitigation (in place) |
|---|---|---|---|---|---|
| H1 | `recall_logger_hook.py` (PostToolUse Read hook) | A hook on every Read could block/slow Reads or crash the tool loop. | Low | Medium | **Fail-open:** every error path `return 0`; store import wrapped in try/except. Only acts when the read path is under the memory dir. |
| H2 | Same hook | Path confusion logs a non-memory read, or a traversal writes outside the store. | Low | Low | `os.realpath` + `startswith(mem_dir + sep)` gate; only a derived slug string is written to SQLite — no path is ever written or moved by the hook. |
| H3 | Same hook | Imports `store` from a configurable dir — if that dir were attacker-writable, code exec in the Read-hook context. | Low | High (if precondition met) | Single-user local workstation; the dir is user-owned. Accept; revisit if the repo dir becomes group-writable. |
| ST1 | `store.py` (SQLite) | SQL injection via slug/reason content. | Low | Medium | **All queries parameterized** (`?` placeholders); no string interpolation into SQL. |
| ST2 | `store.py` | Telemetry corruption / unbounded growth. | Low | Low | `INSERT OR IGNORE` unique dedup on recall rows; DB is local, append-only, small. |
| BF1 | `backfill` (transcript scan) | Reads session transcripts (may contain sensitive content). | Low | Low | Read-only; extracts only the memory **filename** from `/memory/<file>.md` paths, never transcript body content, into the store. |

## OWASP mapping
A08 Software & Data Integrity (T1/T2/T3), A09 Logging Integrity (T3 audit-log injection). No A01/A02/A03/A07 surface (no auth, no network, no injection-to-interpreter).

## Anti-patterns to avoid
- **Substring matching for structural edits** — when striking/locating index lines, match the structured token (`](file.md)`), never `file.md in line`. (T1)
- **Mutate-then-move** — never edit derived records before the primary irreversible op succeeds. Do the move first; derived edits are recoverable, a half-applied move is not. (T2)
- **Trusting frontmatter as safe** — `name:`/`description:` can originate from external content; treat as untrusted when writing to a durable log. (T3)
- **Echoing memory bodies** — keep the read-only report to metadata + computed signals; never dump file contents (preserves I1).
