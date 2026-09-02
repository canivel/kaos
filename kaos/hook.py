"""``kaos-hook`` — the fast entrypoint that Claude Code (and Pi) hooks call.

Each invocation is a cold process, so this module imports only ``sqlite3``
and the light KAOS modules — no click, no rich, no yaml — to stay inside a
hook's latency budget. It never raises: any failure exits 0 silently (set
``KAOS_HOOK_DEBUG=1`` for tracebacks) because a broken hook must never block
the user's session.

Subcommands mirror Claude Code hook events; JSON arrives on stdin::

    kaos-hook session-start   journal the session, print recalled memory (stdout → context)
    kaos-hook prompt          journal the prompt; inject memory only when enabled
    kaos-hook tool            record one tool call in ``tool_calls`` + the journal
    kaos-hook stop            journal the turn end; occasionally consolidate memory
    kaos-hook session-end     mark the session's agent completed

One KAOS agent is created per external session (name ``claude-code:<session_id>``),
so ``kaos ls``, ``kaos query`` and the dashboard show every Claude Code session
as a first-class, auditable agent.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

AGENT_FAMILY = "claude-code"
SESSION_TOKEN_CAP = 800
PROMPT_TOKEN_CAP = 400
CONSOLIDATE_INTERVAL_S = 30 * 60

_STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "have", "are", "was", "were",
    "you", "your", "can", "not", "but", "all", "any", "into", "then", "than", "when",
    "what", "how", "why", "which", "where", "who", "will", "would", "should", "could",
    "please", "make", "just", "like", "also", "about", "there", "here", "some", "them",
    "they", "our", "its", "use", "using", "add", "new", "one", "two", "get", "set",
}


# ── db resolution ────────────────────────────────────────────────────────


def resolve_db(explicit: str | None, cwd: str | None) -> str:
    """Pick the journal database: explicit flag > $KAOS_DB > ./kaos.db in the
    project (a KAOS user) > ~/.kaos/claude-code.db (everyone else)."""
    if explicit:
        return explicit
    env = os.environ.get("KAOS_DB")
    if env:
        return env
    if cwd:
        local = Path(cwd) / "kaos.db"
        if local.exists():
            return str(local)
    home = Path(os.environ.get("KAOS_HOME", str(Path.home() / ".kaos")))
    home.mkdir(parents=True, exist_ok=True)
    return str(home / "claude-code.db")


def open_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    have = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memory_fts'"
    ).fetchone()
    if not have:
        from kaos.schema import init_schema
        init_schema(conn)
    return conn


# ── journal primitives ───────────────────────────────────────────────────


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int(time.time() * 1000) % 1000:03d}"


def log_event(conn: sqlite3.Connection, agent_id: str, event_type: str, payload: dict | None = None) -> int:
    cur = conn.execute(
        "INSERT INTO events (agent_id, event_type, payload) VALUES (?, ?, ?)",
        (agent_id, event_type, json.dumps(payload or {})),
    )
    return int(cur.lastrowid)


def ensure_agent(conn: sqlite3.Connection, family: str, session_id: str,
                 cwd: str | None = None, extra: dict | None = None) -> str:
    """Return the agent_id for an external session, creating it on first sight."""
    name = f"{family}:{session_id}"
    row = conn.execute("SELECT agent_id FROM agents WHERE name = ?", (name,)).fetchone()
    if row:
        conn.execute(
            "UPDATE agents SET status='running', last_heartbeat=? WHERE agent_id=? AND status IN ('initialized','completed','paused')",
            (_now(), row[0]),
        )
        return row[0]
    from kaos._ids import new_ulid
    agent_id = new_ulid()
    meta = {"session_id": session_id, "cwd": cwd or "", "family": family}
    meta.update(extra or {})
    conn.execute(
        "INSERT INTO agents (agent_id, name, status, config, metadata, last_heartbeat) "
        "VALUES (?, ?, 'running', ?, ?, ?)",
        (agent_id, name, json.dumps({"role": f"{family}-session"}), json.dumps(meta), _now()),
    )
    conn.execute("INSERT INTO files (agent_id, path, is_dir) VALUES (?, '/', 1)", (agent_id,))
    log_event(conn, agent_id, "agent_spawn", {"name": name, "session_id": session_id, "cwd": cwd or ""})
    return agent_id


def append_external_event(db_path: str, family: str, session_id: str,
                          event_type: str, payload: dict | None = None) -> dict:
    """Public helper used by ``kaos journal append`` — same code path as the hooks."""
    conn = open_db(db_path)
    try:
        agent_id = ensure_agent(conn, family, session_id, (payload or {}).get("cwd"))
        event_id = log_event(conn, agent_id, event_type, payload)
        conn.commit()
        return {"agent_id": agent_id, "event_id": event_id, "event_type": event_type, "db": db_path}
    finally:
        conn.close()


# ── recall ───────────────────────────────────────────────────────────────


def fts_query(text: str, max_terms: int = 12) -> str:
    """Turn free text into a safe FTS5 query: quoted terms joined with OR.

    Hyphens and dots split words ("payments-service" → payments, service) so a
    project directory name recalls memories about its parts.
    """
    terms: list[str] = []
    for tok in re.findall(r"[a-z0-9_]{3,}", (text or "").lower()):
        if tok in _STOPWORDS or tok in terms:
            continue
        terms.append(tok)
        if len(terms) >= max_terms:
            break
    return " OR ".join(f'"{t}"' for t in terms)


def recall(conn: sqlite3.Connection, text: str, limit: int, requesting_agent_id: str | None) -> list:
    q = fts_query(text)
    if not q:
        return []
    from kaos.memory import MemoryStore
    try:
        return MemoryStore(conn).search(
            q, limit=limit, rank="weighted",
            record_hits=True, requesting_agent_id=requesting_agent_id,
        )
    except sqlite3.OperationalError:
        return []


def format_inject(entries: list, token_cap: int) -> str:
    """Compact context block; ``token_cap`` is enforced as ~4 chars per token."""
    if not entries:
        return ""
    budget = token_cap * 4
    head = (f'<kaos-memory hits="{len(entries)}" note="team lessons recalled by KAOS; '
            f'prior context — verify before relying on it">')
    lines = [head]
    used = len(head)
    for e in entries:
        label = f"- [{e.type}{'/' + e.key if e.key else ''}] "
        room = budget - used - len(label) - 16
        if room < 40:
            break
        body = " ".join(str(e.content).split())
        if len(body) > room:
            body = body[: room - 1] + "…"
        line = label + body
        lines.append(line)
        used += len(line) + 1
    lines.append("</kaos-memory>")
    return "\n".join(lines)


# ── hook config (~/.kaos/hook.json) ──────────────────────────────────────


def _hook_home() -> Path:
    return Path(os.environ.get("KAOS_HOME", str(Path.home() / ".kaos")))


def hook_config() -> dict:
    try:
        return json.loads((_hook_home() / "hook.json").read_text())
    except Exception:
        return {}


def prompt_inject_enabled() -> bool:
    env = os.environ.get("KAOS_HOOK_PROMPT_INJECT")
    if env is not None:
        return env not in ("", "0", "false", "no")
    return bool(hook_config().get("prompt_inject", False))


# ── commands ─────────────────────────────────────────────────────────────


def cmd_session_start(conn: sqlite3.Connection, data: dict) -> str:
    sid = str(data.get("session_id") or "unknown")
    cwd = data.get("cwd")
    aid = ensure_agent(conn, AGENT_FAMILY, sid, cwd,
                       {"transcript_path": data.get("transcript_path", "")})
    log_event(conn, aid, "session_start", {
        "reason": data.get("session_start_reason") or data.get("source") or "",
        "cwd": cwd or "",
    })
    conn.commit()
    hint = Path(cwd).name if cwd else ""
    entries = recall(conn, hint, 5, aid) if hint else []
    conn.commit()
    return format_inject(entries, SESSION_TOKEN_CAP)


def cmd_prompt(conn: sqlite3.Connection, data: dict) -> str:
    sid = str(data.get("session_id") or "unknown")
    aid = ensure_agent(conn, AGENT_FAMILY, sid, data.get("cwd"))
    prompt = str(data.get("user_message") or data.get("prompt") or "")
    log_event(conn, aid, "user_prompt", {"prompt": prompt[:500], "prompt_id": data.get("prompt_id", "")})
    conn.commit()
    if not prompt_inject_enabled() or not prompt:
        return ""
    entries = recall(conn, prompt[:300], 3, aid)
    conn.commit()
    return format_inject(entries, PROMPT_TOKEN_CAP)


def _looks_like_error(result: Any) -> bool:
    if isinstance(result, dict):
        return bool(result.get("is_error") or result.get("error"))
    if isinstance(result, str):
        return result.startswith("Error") or "Traceback" in result[:200]
    return False


def cmd_tool(conn: sqlite3.Connection, data: dict) -> str:
    sid = str(data.get("session_id") or "unknown")
    aid = ensure_agent(conn, AGENT_FAMILY, sid, data.get("cwd"))
    tool = str(data.get("tool_name") or "unknown")
    tool_input = data.get("tool_input")
    result = data.get("tool_result", data.get("tool_response"))
    status = "error" if _looks_like_error(result) else "success"
    from kaos._ids import new_ulid
    call_id = new_ulid()
    now = _now()
    conn.execute(
        "INSERT INTO tool_calls (call_id, agent_id, tool_name, input, output, status, "
        "started_at, completed_at, duration_ms, error_message) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (
            call_id, aid, tool,
            json.dumps(tool_input if tool_input is not None else {})[:4000],
            json.dumps(result)[:4000] if result is not None else None,
            status, now, now, 0,
            (json.dumps(result)[:500] if status == "error" else None),
        ),
    )
    log_event(conn, aid, "tool_call_end", {"call_id": call_id, "tool_name": tool, "status": status,
                                          "tool_use_id": data.get("tool_use_id", "")})
    path = tool_input.get("file_path") if isinstance(tool_input, dict) else None
    if path and tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        log_event(conn, aid, "file_write", {"path": path, "host_fs": True, "call_id": call_id})
    elif path and tool == "Read":
        log_event(conn, aid, "file_read", {"path": path, "host_fs": True, "call_id": call_id})
    conn.commit()
    return ""


def _maybe_consolidate(db_path: str) -> None:
    """Run ``kaos dream consolidate --apply`` at most every CONSOLIDATE_INTERVAL_S.

    The Stop hook fires after every assistant turn, so this is rate-limited via a
    small state file; the hook runs async so the cost is invisible to the user.
    """
    if os.environ.get("KAOS_HOOK_NO_CONSOLIDATE"):
        return
    state_path = _hook_home() / "hook-state.json"
    try:
        state = json.loads(state_path.read_text())
    except Exception:
        state = {}
    last = float(state.get("last_consolidate", {}).get(db_path, 0))
    if time.time() - last < CONSOLIDATE_INTERVAL_S:
        return
    state.setdefault("last_consolidate", {})[db_path] = time.time()
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state))
    except Exception:
        pass
    import subprocess
    try:
        subprocess.run(["kaos", "dream", "consolidate", "--apply", "--db", db_path],
                       capture_output=True, timeout=90)
    except Exception:
        pass


def cmd_stop(conn: sqlite3.Connection, data: dict, db_path: str) -> str:
    sid = str(data.get("session_id") or "unknown")
    aid = ensure_agent(conn, AGENT_FAMILY, sid, data.get("cwd"))
    log_event(conn, aid, "turn_end", {
        "last_assistant_message": str(data.get("last_assistant_message") or "")[:1000],
        "prompt_id": data.get("prompt_id", ""),
    })
    conn.execute("UPDATE agents SET last_heartbeat=? WHERE agent_id=?", (_now(), aid))
    conn.commit()
    conn.close()
    _maybe_consolidate(db_path)
    return ""


def cmd_session_end(conn: sqlite3.Connection, data: dict) -> str:
    sid = str(data.get("session_id") or "unknown")
    aid = ensure_agent(conn, AGENT_FAMILY, sid, data.get("cwd"))
    log_event(conn, aid, "session_end", {"reason": data.get("reason", "")})
    conn.execute("UPDATE agents SET status='completed' WHERE agent_id=?", (aid,))
    conn.commit()
    return ""


COMMANDS = {
    "session-start": cmd_session_start,
    "prompt": cmd_prompt,
    "tool": cmd_tool,
    "stop": cmd_stop,
    "session-end": cmd_session_end,
}


# ── entrypoint ───────────────────────────────────────────────────────────


def run(argv: list[str], stdin_text: str | None = None) -> str:
    """Execute one hook command; returns the text to print (context injection)."""
    if not argv or argv[0] not in COMMANDS:
        raise SystemExit(f"usage: kaos-hook {{{'|'.join(COMMANDS)}}} [--db PATH]")
    cmd = argv[0]
    db_flag = None
    if "--db" in argv:
        db_flag = argv[argv.index("--db") + 1]
    raw = stdin_text if stdin_text is not None else (sys.stdin.read() if not sys.stdin.isatty() else "")
    try:
        data = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    db_path = resolve_db(db_flag, data.get("cwd"))
    conn = open_db(db_path)
    try:
        if cmd == "stop":
            return cmd_stop(conn, data, db_path)
        return COMMANDS[cmd](conn, data)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def main(argv: list[str] | None = None, stdin_text: str | None = None) -> int:
    t0 = time.perf_counter()
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        out = run(argv, stdin_text)
        if out:
            sys.stdout.write(out + "\n")
            sys.stdout.flush()
    except SystemExit as exc:
        if exc.code and isinstance(exc.code, str):
            sys.stderr.write(exc.code + "\n")
        return 0
    except Exception:
        if os.environ.get("KAOS_HOOK_DEBUG"):
            import traceback
            traceback.print_exc()
        return 0
    if os.environ.get("KAOS_HOOK_DEBUG"):
        sys.stderr.write(f"kaos-hook {argv[0]} {(time.perf_counter() - t0) * 1000:.0f} ms\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
