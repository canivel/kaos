"""Organic episode sampling + BLIND trace rendering for the PFA probe.

Everything here is frozen by ISA.lock.json: seed 20260801, caps 80/100,
>=3 non-terminal events, and the blind-rendering clause. The leak guard
is constructive: outcome-revealing tokens are scrubbed from free text,
then asserted absent — any survivor VOIDs the run.
"""

from __future__ import annotations

import json
import random
import re
import sqlite3
from dataclasses import dataclass

SEED = 20260801
TERMINAL = ("agent_complete", "agent_fail", "agent_kill")
FORBIDDEN = re.compile(
    r"agent_complete|agent_fail|agent_kill|completed|failed|killed", re.I)


@dataclass
class Episode:
    agent_id: str
    failure_class: bool   # ground truth — NEVER passed to any arm
    n_events: int


def _scrub(text: str) -> str:
    return FORBIDDEN.sub("[…]", text or "")


def leak_guard(prompt: str) -> bool:
    return FORBIDDEN.search(prompt) is None


def sample(conn: sqlite3.Connection) -> tuple[list[Episode], list[Episode]]:
    """Frozen sampling: all failure-class capped 80, completed capped 100."""
    rows = conn.execute(
        "SELECT a.agent_id, a.status, COUNT(e.event_id) n FROM agents a "
        "JOIN events e ON e.agent_id = a.agent_id "
        "WHERE a.status IN ('completed','failed','killed') "
        f"AND e.event_type NOT IN {TERMINAL!r} "
        "GROUP BY a.agent_id HAVING n >= 3 ORDER BY a.agent_id",
    ).fetchall()
    fails = [Episode(a, True, n) for a, s, n in rows if s in ("failed", "killed")]
    oks = [Episode(a, False, n) for a, s, n in rows if s == "completed"]
    rng = random.Random(SEED)
    if len(fails) > 80:
        fails = rng.sample(fails, 80)
    if len(oks) > 100:
        oks = rng.sample(oks, 100)
    return sorted(fails, key=lambda e: e.agent_id), sorted(oks, key=lambda e: e.agent_id)


def _compact_payload(raw: str) -> str:
    try:
        d = json.loads(raw or "{}")
    except (json.JSONDecodeError, TypeError):
        return _scrub(str(raw))[:120]
    if not isinstance(d, dict):
        return _scrub(str(d))[:120]
    keep = {k: d[k] for k in ("path", "size", "tool_name", "name", "key",
                              "version", "call_id", "role") if k in d}
    if not keep:
        keep = d
    return _scrub(json.dumps(keep, default=str))[:120]


def render(conn: sqlite3.Connection, agent_id: str) -> tuple[str, list[int]]:
    """Blind prompt trace for one episode. Returns (trace, event_id list)."""
    task_row = conn.execute(
        "SELECT value FROM state WHERE agent_id=? AND key='task'", (agent_id,),
    ).fetchone()
    task = ""
    if task_row:
        try:
            v = json.loads(task_row[0])
            task = v if isinstance(v, str) else task_row[0]
        except (json.JSONDecodeError, TypeError):
            task = task_row[0]
    task = _scrub(task)[:300]

    evs = conn.execute(
        "SELECT event_id, event_type, payload, timestamp FROM events "
        f"WHERE agent_id=? AND event_type NOT IN {TERMINAL!r} "
        "ORDER BY timestamp, event_id", (agent_id,),
    ).fetchall()
    if len(evs) > 60:
        evs = evs[:40] + evs[-20:]
    ids = [e[0] for e in evs]
    lines = [f"[{eid}] {etype} {_compact_payload(p)}" for eid, etype, p, _ in evs]

    tcs = conn.execute(
        "SELECT tool_name, status, error_message FROM tool_calls "
        "WHERE agent_id=? ORDER BY started_at LIMIT 40", (agent_id,),
    ).fetchall()
    tlines = [
        f"tool {t} status={_scrub(s or '')}"
        + (f" err={_scrub(e)[:120]}" if e else "")
        for t, s, e in tcs
    ]
    dur = ""
    if len(evs) >= 2:
        dur = f"first-to-last event span: {evs[0][3]} .. {evs[-1][3]}"

    trace = (f"TASK (truncated): {task}\n\nEVENTS ({len(ids)} shown):\n"
             + "\n".join(lines)
             + ("\n\nTOOL CALLS:\n" + "\n".join(tlines) if tlines else "")
             + ("\n" + dur if dur else ""))
    return trace, ids
