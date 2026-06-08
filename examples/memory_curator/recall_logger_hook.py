#!/usr/bin/env python3
"""
PostToolUse(Read) hook — memory-curator recall telemetry.

Claude Code exposes no native "memory recalled" event and no auto-recall stream
for native memory files. The genuine "this memory was actively pulled into
context" signal is an explicit Read of a memory/*.md file. This hook logs each
such Read to the curator's SQLite store so the re-use score is measured, not
just proxied.

Fail-open by design: any error exits 0 and never blocks or slows the Read.

Wire into ~/.claude/settings.json under hooks.PostToolUse with a matcher of
"Read", and set CURATOR_PKG to the dir holding curator.py/store.py (defaults to
this file's own dir). Optionally set CURATOR_MEM_DIR to override the memory dir.
"""
import json
import os
import sys

# Where store.py lives. Defaults to this hook's own directory so it works
# wherever you place the memory_curator example.
CURATOR_PKG = os.environ.get(
    "CURATOR_PKG", os.path.dirname(os.path.realpath(__file__))
)


def _resolve_mem_dir() -> str:
    env = os.environ.get("CURATOR_MEM_DIR")
    if env:
        return os.path.expanduser(env)
    # Mirror curator.py's auto-detection: ~/.claude/projects/<slug>/memory for cwd.
    cwd = os.path.realpath(os.getcwd())
    slug = "-" + cwd.strip("/").replace("/", "-")
    cand = os.path.join(os.path.expanduser("~/.claude/projects"), slug, "memory")
    return cand


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0
    tool = payload.get("tool_name") or payload.get("tool") or ""
    if tool != "Read":
        return 0
    ti = payload.get("tool_input") or payload.get("input") or {}
    path = ti.get("file_path") or ""
    real_mem = os.path.realpath(_resolve_mem_dir())
    real_path = os.path.realpath(path)
    # only log reads of an actual memory topic file (not MEMORY.md / ARCHIVE.md)
    if not real_path.startswith(real_mem + os.sep):
        return 0
    base = os.path.basename(real_path)
    if not base.endswith(".md") or base in ("MEMORY.md", "ARCHIVE.md"):
        return 0
    slug = base[:-3]
    session = payload.get("session_id") or payload.get("session") or None
    try:
        sys.path.insert(0, CURATOR_PKG)
        from store import Store  # type: ignore
        st = Store(real_mem)
        st.log_recall(slug, session=session, kind="read")
        st.close()
    except Exception:
        return 0  # fail-open: telemetry must never break a Read
    return 0


if __name__ == "__main__":
    sys.exit(main())
