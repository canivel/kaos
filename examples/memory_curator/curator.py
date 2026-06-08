#!/usr/bin/env python3
"""
memory-curator — probabilistic staleness triage for Claude Code's native memory dir.

Claude Code keeps a per-project markdown memory dir (an always-loaded `MEMORY.md`
index plus one `*.md` file per fact). It grows monotonically: nothing ever ages
out, so the index drifts toward a size cap and stale files keep loading into every
session's context. This tool scores every memory file across five dimensions
(staleness, completion, correctness, durability, re-use) into a composite
P(archive), and archives approved candidates reversibly (move to archived/ +
ARCHIVE.md digest + MEMORY.md index strike). Read-only by default; nothing deletes
a file.

This is the KAOS dream/consolidation prune-decay idea (recency half-life +
soft, reversible removal) ported to a store KAOS does NOT manage: Claude Code's
native markdown memory, as opposed to the kaos.db FTS store. It does not import
or modify the kaos package — it is a standalone sidecar CLI.

Re-use blends MEASURED recall telemetry (Read events captured by the optional
PostToolUse hook, backfilled from transcripts) with a proxy (inbound [[links]]
+ recency). A persistent SQLite store (<mem_dir>/.curator/) holds telemetry,
score history, and decisions; rejected candidates get a cooldown so they don't
re-nag.

Usage:
  python3 curator.py report [--all]                 # score + list candidates (default)
  python3 curator.py backfill                        # seed telemetry from past transcripts
  python3 curator.py archive <slug>... [--apply]     # dry-run / perform reversible archive
  python3 curator.py reject  <slug>...               # cooldown (suppress from ARCHIVE)
  python3 curator.py history <slug>                  # recall/decision/score trend
  python3 curator.py selftest                        # scoring + archive-path checks

Point it at a memory dir with CURATOR_MEM_DIR; otherwise it auto-detects the
Claude Code memory dir for the current working directory.
"""
from __future__ import annotations
import argparse
import datetime as dt
import math
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --- config -----------------------------------------------------------------


def _default_mem_dir() -> Path:
    """Locate Claude Code's native memory dir for the current project.

    Claude Code stores per-project state under ~/.claude/projects/<slug>/, where
    <slug> is the project path with separators replaced by '-'. Memory lives in
    that dir's memory/ subfolder. Override with CURATOR_MEM_DIR for any other
    layout. Falls back to ./memory so the tool still runs (and selftest passes)
    outside a Claude Code project.
    """
    env = os.environ.get("CURATOR_MEM_DIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd().resolve()
    slug = "-" + str(cwd).strip("/").replace("/", "-")
    candidate = Path.home() / ".claude" / "projects" / slug / "memory"
    if candidate.is_dir():
        return candidate.resolve()
    # walk up: a parent dir may be the registered Claude Code project root
    for parent in cwd.parents:
        slug = "-" + str(parent).strip("/").replace("/", "-")
        candidate = Path.home() / ".claude" / "projects" / slug / "memory"
        if candidate.is_dir():
            return candidate.resolve()
    return (cwd / "memory").resolve()


MEM_DIR = _default_mem_dir()
INDEX_FILE = "MEMORY.md"
ARCHIVE_FILE = "ARCHIVE.md"
ARCHIVE_SUBDIR = "archived"


def _open_store():
    """Open the persistent SQLite store; return None if unavailable (fail-open)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from store import Store
        return Store(MEM_DIR)
    except Exception as e:  # never let telemetry break scoring
        print(f"  (store unavailable, proxy-only: {e})", file=sys.stderr)
        return None

# type -> (durability prior 0..1, staleness half-life in days)
TYPE_PRIORS = {
    "reference": (0.90, 240),
    "user": (0.90, 365),
    "feedback": (0.80, 210),
    "project": (0.30, 30),
}
DEFAULT_PRIOR = (0.50, 120)

COMPLETION_MARKERS = re.compile(
    r"\b(DEPLOYED|SHIPPED|RESOLVED|DONE|COMPLETE[D]?|LIVE IN PROD|WORKING E2E|"
    r"phase\s+\d+\s+(?:done|complete))\b",
    re.IGNORECASE,
)
INCORRECT_MARKERS = re.compile(
    r"\b(SUPERSEDED|LEGACY|DEPRECATED|DECOMMISSION(?:ED|ING)?|"
    r"NO LONGER|WAS WRONG|DEAD END|OBSOLETE|STALE)\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
LINK_RE = re.compile(r"\[\[([a-z0-9][a-z0-9\-]*)\]\]")
# Absolute filesystem paths referenced in the body. A memory naming a path that
# no longer exists is a signal the memory may now be incorrect. Matches unix
# (/a/b/c.ext) and Windows (C:\a\b\c.ext) absolute paths ending in a short ext.
PATH_RE = re.compile(
    r"(?<![\w])((?:/|[A-Za-z]:\\)[\w./\\\-]+\.\w{1,6})"
)

# composite weights (tuned defaults; adjust for your corpus)
W_STALE, W_DONE, W_INCORRECT, W_REUSE = 0.55, 0.45, 0.50, 0.30
ORPHAN_BONUS = 0.10  # not in MEMORY.md index => mild archive pressure
TAU_CANDIDATE = 0.70
FLOOR_KEEP = 0.40

TODAY = dt.date.today()


# --- model ------------------------------------------------------------------


@dataclass
class Memory:
    path: Path
    slug: str
    mtype: str
    description: str
    body: str
    mtime: dt.date
    in_index: bool
    inbound_links: int = 0
    # scores filled in by score()
    stale: float = 0.0
    complete: float = 0.0
    incorrect: float = 0.0
    durability: float = 0.0
    reuse: float = 0.0
    p_archive: float = 0.0
    reasons: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.p_archive >= TAU_CANDIDATE:
            return "ARCHIVE"
        if self.p_archive < FLOOR_KEEP:
            return "keep"
        return "watch"


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Tiny dependency-free frontmatter parser. Returns (fields, body)."""
    fields: dict[str, str] = {}
    if not text.startswith("---"):
        return fields, text
    end = text.find("\n---", 3)
    if end == -1:
        return fields, text
    fm = text[3:end]
    body = text[end + 4 :]
    for line in fm.splitlines():
        m = re.match(r"\s*([A-Za-z_]+)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip().strip('"').strip("'")
        # don't clobber a top-level key with a nested one of the same name
        if key not in fields and val:
            fields[key] = val
    return fields, body


def load_memories(mem_dir: Path) -> list[Memory]:
    index_text = ""
    idx_path = mem_dir / INDEX_FILE
    if idx_path.exists():
        index_text = idx_path.read_text(encoding="utf-8", errors="replace")

    mems: list[Memory] = []
    for p in sorted(mem_dir.glob("*.md")):
        if p.name in (INDEX_FILE, ARCHIVE_FILE):
            continue
        raw = p.read_text(encoding="utf-8", errors="replace")
        # strip a leading system-reminder line if present (recall artifact)
        raw = re.sub(r"^<system-reminder>.*?</system-reminder>\s*", "", raw, flags=re.S)
        fm, body = parse_frontmatter(raw)
        slug = fm.get("name", p.stem)
        mtype = (fm.get("type") or "").lower()
        mtime = dt.date.fromtimestamp(p.stat().st_mtime)
        mems.append(
            Memory(
                path=p,
                slug=slug,
                mtype=mtype,
                description=fm.get("description", ""),
                body=body,
                mtime=mtime,
                in_index=(p.name in index_text) or (slug in index_text),
            )
        )

    # inbound link counts: how many OTHER memories point at each slug
    by_slug = {m.slug: m for m in mems}
    for m in mems:
        for target in set(LINK_RE.findall(m.body)):
            if target in by_slug and target != m.slug:
                by_slug[target].inbound_links += 1
    return mems


def _content_date(body: str) -> dt.date | None:
    best = None
    for y, mo, d in DATE_RE.findall(body):
        try:
            cand = dt.date(int(y), int(mo), int(d))
        except ValueError:
            continue
        if cand <= TODAY and (best is None or cand > best):
            best = cand
    return best


def score(m: Memory, max_inbound: int, recall_counts: dict | None = None) -> None:
    durability, halflife = TYPE_PRIORS.get(m.mtype, DEFAULT_PRIOR)
    m.durability = durability

    # staleness: age from the more recent of mtime / latest in-body date
    cdate = _content_date(m.body)
    anchor = max([d for d in (m.mtime, cdate) if d is not None])
    age = (TODAY - anchor).days
    m.stale = _clamp(1.0 - 0.5 ** (age / halflife))
    if age > halflife:
        m.reasons.append(f"{age}d old (>{halflife}d half-life for {m.mtype or 'untyped'})")

    # completion
    done_hits = len(set(x.lower() for x in [g[0] if isinstance(g, tuple) else g
                                            for g in COMPLETION_MARKERS.findall(m.body)]))
    m.complete = _clamp(done_hits / 2.0)
    if done_hits:
        m.reasons.append(f"{done_hits} completion marker(s)")

    # correctness (likelihood now-incorrect)
    incorrect = 0.0
    inc_hits = len(INCORRECT_MARKERS.findall(m.body))
    if inc_hits:
        incorrect += min(0.6, 0.3 * inc_hits)
        m.reasons.append(f"{inc_hits} superseded/legacy marker(s)")
    # referenced filesystem paths that no longer exist
    paths = set(PATH_RE.findall(m.body))
    missing = [p for p in paths if not Path(p).exists()]
    if paths:
        frac = len(missing) / len(paths)
        incorrect += 0.4 * frac
        if missing:
            m.reasons.append(f"{len(missing)}/{len(paths)} referenced path(s) missing")
    m.incorrect = _clamp(incorrect)

    # re-use (higher => keep). MEASURED recall reads (from telemetry/backfill)
    # when present, blended with the proxy (inbound links + recency). Claude Code
    # exposes no auto-recall stream for native memory, so the real signal is an
    # explicit Read of a memory file — sparse but genuine. Being IN the index
    # carries no signal (every live memory is indexed); its ABSENCE does (orphan).
    link_sig = min(1.0, m.inbound_links / 3.0)
    recency_sig = 0.5 ** (age / 60.0)  # decays ~2 months
    # canonical recall key is the FILENAME STEM (what the hook/backfill see on
    # disk) — NOT the frontmatter name, which can differ and won't join.
    reads = (recall_counts or {}).get(m.path.stem, 0)
    measured_sig = min(1.0, reads / 3.0)
    m.reuse = _clamp(0.35 * link_sig + 0.25 * recency_sig + 0.55 * measured_sig)
    if reads:
        m.reasons.append(f"{reads} measured recall read(s)")
    if m.inbound_links:
        m.reasons.append(f"{m.inbound_links} inbound link(s)")

    orphan = 0.0
    if not m.in_index:
        orphan = ORPHAN_BONUS
        m.reasons.append("NOT in MEMORY.md index")

    # composite
    pressure = (
        W_STALE * m.stale * (1.0 - m.durability)
        + W_DONE * m.complete
        + W_INCORRECT * m.incorrect
        + orphan
    )
    m.p_archive = _clamp(pressure - W_REUSE * m.reuse)


# --- report -----------------------------------------------------------------


def _score_all(mems, store=None):
    """Score every memory using measured recall counts from the store if present."""
    max_inbound = max((m.inbound_links for m in mems), default=0)
    recall_counts = store.recall_counts() if store else {}
    for m in mems:
        score(m, max_inbound, recall_counts)
    return mems


def cmd_report(args) -> int:
    mems = load_memories(MEM_DIR)
    if not mems:
        print(f"No memories found in {MEM_DIR}", file=sys.stderr)
        return 1
    store = _open_store()
    _score_all(mems, store)

    # cooldown: a recently-rejected candidate is held at 'watch' so it doesn't
    # re-nag every run until its content materially changes.
    cooled = store.cooled_down() if store else set()
    for m in mems:
        if m.path.stem in cooled and m.verdict == "ARCHIVE":
            m.cooled = True
            m.reasons.append("cooldown (rejected recently)")
    mems.sort(key=lambda m: m.p_archive, reverse=True)

    def eff_verdict(m):
        return "watch" if getattr(m, "cooled", False) else m.verdict

    shown = mems if args.all else [m for m in mems if eff_verdict(m) != "keep"]
    n_arch = sum(1 for m in mems if eff_verdict(m) == "ARCHIVE")
    n_watch = sum(1 for m in mems if eff_verdict(m) == "watch")

    measured = "telemetry+proxy" if (store and store.recall_counts()) else "proxy only"
    print(f"\nmemory-curator — {len(mems)} memories scored in {MEM_DIR}")
    print(f"  re-use signal: {measured}")
    print(f"  {n_arch} ARCHIVE candidate(s), {n_watch} watch, "
          f"{len(mems) - n_arch - n_watch} keep\n")
    print(f"{'P':>4}  {'verdict':<8} {'stl':>4} {'cmp':>4} {'inc':>4} "
          f"{'dur':>4} {'reu':>4}  slug")
    print("-" * 96)
    for m in shown:
        print(f"{m.p_archive:4.2f}  {eff_verdict(m):<8} {m.stale:4.2f} {m.complete:4.2f} "
              f"{m.incorrect:4.2f} {m.durability:4.2f} {m.reuse:4.2f}  {m.slug}")
        if eff_verdict(m) in ("ARCHIVE", "watch") and m.reasons:
            print(f"        -> {'; '.join(m.reasons)}")
    print()
    if store:
        store.record_run(mems, n_arch)
        store.close()
    if n_arch:
        cands = " ".join(m.slug for m in mems if eff_verdict(m) == "ARCHIVE")
        print("Approve (archive) candidates:   "
              f"python3 {Path(sys.argv[0]).name} archive {cands} --apply")
        print("Reject (cooldown) candidates:   "
              f"python3 {Path(sys.argv[0]).name} reject {cands}\n")
    return 0


# --- archive (reversible) ---------------------------------------------------


def _resolve_slug(slug: str, mems: list[Memory]) -> Memory | None:
    for m in mems:
        if m.slug == slug or m.path.stem == slug:
            return m
    return None


def cmd_archive(args) -> int:
    mems = load_memories(MEM_DIR)
    store = _open_store()
    # score so the ARCHIVE.md digest captures the real probability + reasons
    _score_all(mems, store)
    targets = []
    for slug in args.slugs:
        m = _resolve_slug(slug, mems)
        if not m:
            print(f"  ! no memory matches slug '{slug}' — skipping", file=sys.stderr)
            continue
        targets.append(m)
    if not targets:
        print("Nothing to archive.", file=sys.stderr)
        return 1

    # E1: never mutate a directory that isn't a memory dir
    if args.apply and not (MEM_DIR / INDEX_FILE).exists():
        print(f"  ! {MEM_DIR} has no {INDEX_FILE} — refusing to --apply here "
              f"(set CURATOR_MEM_DIR correctly).", file=sys.stderr)
        return 1

    archive_dir = MEM_DIR / ARCHIVE_SUBDIR
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"\n[{mode}] archiving {len(targets)} memory file(s):\n")
    for m in targets:
        # safety: never escape the memory dir
        dest = (archive_dir / m.path.name).resolve()
        if not str(dest).startswith(str(archive_dir.resolve()) + os.sep):
            print(f"  ! refusing unsafe destination for {m.slug}", file=sys.stderr)
            continue
        print(f"  {m.path.name}")
        print(f"     move  -> {ARCHIVE_SUBDIR}/{m.path.name}")
        print(f"     digest-> {ARCHIVE_FILE}  (date={TODAY}, p={m.p_archive:.2f})")
        print(f"     index -> strike line from {INDEX_FILE}")
        if args.apply:
            # T2: move FIRST (the only irreversible step). If it fails or the
            # destination already exists, skip without touching ARCHIVE.md/index,
            # so a failed move can never leave the records inconsistent.
            if dest.exists():
                print(f"     ! {ARCHIVE_SUBDIR}/{m.path.name} already exists — skipping",
                      file=sys.stderr)
                continue
            archive_dir.mkdir(exist_ok=True)
            try:
                os.rename(m.path, dest)
            except OSError as e:
                print(f"     ! move failed ({e}) — skipping, records untouched",
                      file=sys.stderr)
                continue
            # T3: sanitize content-derived slug before writing the durable log
            safe_slug = re.sub(r"[\r\n`]", " ", m.slug)[:120]
            safe_reasons = re.sub(r"[\r\n]", " ", "; ".join(m.reasons)) or "stale"
            digest = (f"- {TODAY} `{safe_slug}` (p={m.p_archive:.2f}) — "
                      f"{safe_reasons} [restore: {ARCHIVE_SUBDIR}/{m.path.name}]\n")
            ap = MEM_DIR / ARCHIVE_FILE
            if not ap.exists():
                ap.write_text("# Archived memories\n\n"
                              "Reversible archive log. Files live in `archived/`.\n\n",
                              encoding="utf-8")
            with ap.open("a", encoding="utf-8") as fh:
                fh.write(digest)
            _strike_index_line(m)
            if store:
                store.record_decision(m.path.stem, "archived", m.p_archive, safe_reasons)
    if not args.apply:
        print(f"\n(dry-run — re-run with --apply to perform the moves)\n")
    else:
        print(f"\nArchived. Restore by moving files back from {ARCHIVE_SUBDIR}/ "
              f"and re-adding their index lines.\n")
    if store:
        store.close()
    return 0


def cmd_reject(args) -> int:
    """Record a rejection so the slug is held at 'watch' (cooldown) on future runs."""
    store = _open_store()
    if not store:
        print("Store unavailable — cannot record rejections.", file=sys.stderr)
        return 1
    mems = load_memories(MEM_DIR)
    n = 0
    for slug in args.slugs:
        m = _resolve_slug(slug, mems)
        canonical = m.path.stem if m else slug
        store.record_decision(canonical, "rejected", None, "user reject")
        print(f"  cooldown set: {canonical}")
        n += 1
    store.close()
    print(f"\n{n} memory(ies) will be suppressed from ARCHIVE status for the "
          f"cooldown window.\n")
    return 0


def cmd_history(args) -> int:
    store = _open_store()
    if not store:
        return 1
    mems = load_memories(MEM_DIR)
    m = _resolve_slug(args.slug, mems)
    key = m.path.stem if m else args.slug
    h = store.history(key)
    print(f"\nhistory for {key}")
    print("  recall reads:", h["recalls"] or "(none)")
    print("  decisions:   ", h["decisions"] or "(none)")
    print("  score trend: ", h["trend"] or "(none)")
    print()
    store.close()
    return 0


def _strike_index_line(m: Memory) -> None:
    ip = MEM_DIR / INDEX_FILE
    if not ip.exists():
        return
    lines = ip.read_text(encoding="utf-8").splitlines(keepends=True)
    # T1: match the markdown link target EXACTLY — `](file.md)` — never a bare
    # substring, so `axiom.md` can't also strike `project_axiom.md`'s line.
    token = f"]({m.path.name})"
    kept = [ln for ln in lines if token not in ln]
    if len(kept) != len(lines):
        ip.write_text("".join(kept), encoding="utf-8")


# --- selftest ---------------------------------------------------------------


def cmd_selftest(args) -> int:
    """Synthetic fixtures verify the scoring logic without touching real files."""
    import tempfile

    fixtures = {
        "fresh-reference.md": (
            "---\nname: fresh-reference\ndescription: x\nmetadata:\n  type: reference\n---\n"
            f"Current as of {TODAY}. [[other-thing]] points here.\n"
        ),
        "done-project.md": (
            "---\nname: done-project\ndescription: x\nmetadata:\n  type: project\n---\n"
            "Shipped 2025-01-01. DEPLOYED to prod. RESOLVED. Phase 3 complete.\n"
        ),
        "other-thing.md": (
            "---\nname: other-thing\ndescription: x\nmetadata:\n  type: feedback\n---\n"
            "See [[fresh-reference]] and [[done-project]].\n"
        ),
    }
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        for name, content in fixtures.items():
            (d / name).write_text(content, encoding="utf-8")
        # backdate done-project so it reads old
        old = dt.datetime(2025, 1, 1).timestamp()
        os.utime(d / "done-project.md", (old, old))
        (d / INDEX_FILE).write_text(
            "- [a](fresh-reference.md)\n- [b](done-project.md)\n- [c](other-thing.md)\n"
        )
        global MEM_DIR
        MEM_DIR = d
        mems = load_memories(d)
        mx = max(m.inbound_links for m in mems)
        for m in mems:
            score(m, mx)
        by = {m.slug: m for m in mems}

        checks = [
            ("fresh reference is not a candidate",
             by["fresh-reference"].verdict != "ARCHIVE"),
            ("fresh reference scores low", by["fresh-reference"].p_archive < FLOOR_KEEP),
            ("done old project is a candidate",
             by["done-project"].verdict == "ARCHIVE"),
            ("done project detected completion", by["done-project"].complete > 0),
            ("inbound links counted", by["fresh-reference"].inbound_links == 1),
            ("durability prior applied (reference>project)",
             by["fresh-reference"].durability > by["done-project"].durability),
        ]
        for label, cond in checks:
            print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    # --- archive-path checks (T1/T2) in a fresh temp dir ---
    with tempfile.TemporaryDirectory() as td2:
        d = Path(td2)
        # substring-collision pair: 'axiom' must not strike 'project-axiom'
        (d / "axiom.md").write_text(
            "---\nname: axiom\ndescription: x\nmetadata:\n  type: project\n---\nbody\n")
        (d / "project-axiom.md").write_text(
            "---\nname: project-axiom\ndescription: x\nmetadata:\n  type: project\n---\nbody\n")
        (d / INDEX_FILE).write_text(
            "- [a](axiom.md) — short\n- [b](project-axiom.md) — long\n")
        MEM_DIR = d
        args = type("A", (), {"slugs": ["axiom"], "apply": True})()
        cmd_archive(args)
        index_after = (d / INDEX_FILE).read_text()
        archived_ok = (d / ARCHIVE_SUBDIR / "axiom.md").exists()
        digest_ok = (d / ARCHIVE_FILE).exists() and "axiom" in (d / ARCHIVE_FILE).read_text()
        # idempotent re-run: file already gone, nothing to do, index unchanged
        cmd_archive(type("A", (), {"slugs": ["axiom"], "apply": True})())

        arch_checks = [
            ("T1: collision-victim index line survived",
             "](project-axiom.md)" in index_after),
            ("T1: target index line struck", "](axiom.md)" not in index_after),
            ("T2: file moved to archived/", archived_ok),
            ("digest written to ARCHIVE.md", digest_ok),
            ("idempotent re-run leaves index intact",
             (d / INDEX_FILE).read_text() == index_after),
        ]
        checks += arch_checks
        for label, cond in arch_checks:
            print(f"  [{'PASS' if cond else 'FAIL'}] {label}")

    print()
    return 0 if all(c for _, c in checks) else 1


# --- backfill (seed telemetry from existing transcripts) --------------------


def _scan_transcripts_for_reads(proj_dir: Path, known_slugs: set[str]) -> list[tuple]:
    """Return [(slug, ts, session)] for each historical Read of a memory file.
    Claude Code exposes no auto-recall stream for native memory, so the genuine
    re-use signal is an explicit Read tool_result on a memory/*.md path."""
    import glob, json
    READPATH = re.compile(r'/memory/([\w\-]+)\.md')
    events = []
    for fp in glob.glob(str(proj_dir / "*.jsonl")):
        sid = Path(fp).stem[:8]
        try:
            with open(fp, encoding="utf-8", errors="replace") as f:
                for ln in f:
                    if '"tool_result"' not in ln or "/memory/" not in ln:
                        continue
                    if "point-in-time observations" not in ln:
                        continue  # the marker the harness attaches to a memory Read
                    try:
                        o = json.loads(ln)
                    except Exception:
                        continue
                    ts = (o.get("timestamp") or "")[:10] or None
                    for fn in set(READPATH.findall(json.dumps(o))):
                        if not known_slugs or fn in known_slugs:
                            events.append((fn, ts, sid))
        except OSError:
            continue
    return events


def cmd_backfill(args) -> int:
    store = _open_store()
    if not store:
        return 1
    proj = MEM_DIR.parent
    known = {p.stem for p in MEM_DIR.glob("*.md")}
    events = _scan_transcripts_for_reads(proj, known)
    seeded = sum(1 for (slug, ts, sid) in events
                 if store.log_recall(slug, ts, sid, kind="backfill"))
    counts = store.recall_counts()
    print(f"\nbackfill: scanned transcripts in {proj}")
    print(f"  {len(events)} historical memory-read event(s) found, "
          f"{seeded} new row(s) seeded (deduped)")
    print(f"  memories with >=1 measured read now: {len(counts)}")
    top = sorted(counts.items(), key=lambda x: -x[1])[:8]
    for slug, n in top:
        print(f"    {n:3d}  {slug}")
    print()
    store.close()
    return 0


# --- cli --------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description="memory-curator: probabilistic staleness triage")
    sub = ap.add_subparsers(dest="cmd")
    rp = sub.add_parser("report", help="score and list candidates (default)")
    rp.add_argument("--all", action="store_true", help="show every memory")
    av = sub.add_parser("archive", help="archive given slugs (reversible)")
    av.add_argument("slugs", nargs="+")
    av.add_argument("--apply", action="store_true", help="actually move (default dry-run)")
    rj = sub.add_parser("reject", help="cooldown given slugs (suppress from ARCHIVE)")
    rj.add_argument("slugs", nargs="+")
    hp = sub.add_parser("history", help="show recall/decision/score history for a slug")
    hp.add_argument("slug")
    sub.add_parser("backfill", help="seed recall telemetry from existing transcripts")
    sub.add_parser("selftest", help="run scoring + archive-path sanity checks")
    args = ap.parse_args()

    if args.cmd in (None, "report"):
        if args.cmd is None:
            args.all = False
        return cmd_report(args)
    if args.cmd == "archive":
        return cmd_archive(args)
    if args.cmd == "reject":
        return cmd_reject(args)
    if args.cmd == "history":
        return cmd_history(args)
    if args.cmd == "backfill":
        return cmd_backfill(args)
    if args.cmd == "selftest":
        return cmd_selftest(args)
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
