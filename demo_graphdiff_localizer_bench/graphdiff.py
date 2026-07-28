"""GDL — bench-local implementation of the frozen normalization and
earliest-divergence diff. Per the lock, this code does NOT ship in kaos/;
it exists only so the probe can measure it.

Every rule here is byte-frozen in ISA.lock.json `normalization_frozen`
and `gdl_algorithm_frozen`. No LLM, no embeddings, anywhere.
"""

from __future__ import annotations

import json
import re
import sqlite3
from difflib import SequenceMatcher

_VOLATILE = re.compile(r"(?i)(^|_)(id|ts|time|date|uuid|token|nonce|seed|hash)($|_)")


def _value_class(key: str, v) -> str | None:
    if _VOLATILE.search(key):
        return None  # dropped
    if isinstance(v, bool):
        return "b"
    if isinstance(v, (int, float)):
        return "n"
    if isinstance(v, str):
        if "/" in v or "\\" in v:
            seg = re.split(r"[/\\]", v.strip("/\\"))[0]
            ext = v.rsplit(".", 1)[1].lower() if "." in v.rsplit("/", 1)[-1] else ""
            return f"p:{seg}:{ext}"
        if len(v) <= 24:
            return f"s:{v.lower()}"
        return "S"
    if isinstance(v, list):
        return f"L{len(v)}"
    if isinstance(v, dict):
        return f"D{len(v)}"
    return "S"


def node_label(tool_name: str, input_json: str) -> tuple:
    """Frozen node normalization: (tool_name, sorted (key, value_class))."""
    try:
        args = json.loads(input_json or "{}")
        if not isinstance(args, dict):
            args = {"_": args}
    except (json.JSONDecodeError, TypeError):
        args = {"_raw": (input_json or "")[:100] + "…pad25chars…"}  # long-str bucket
    sig = []
    for k in sorted(args):
        vc = _value_class(k, args[k])
        if vc is not None:
            sig.append((k, vc))
    return (tool_name, tuple(sig))


class Interner:
    def __init__(self) -> None:
        self._d: dict[tuple, int] = {}

    def __call__(self, label: tuple) -> int:
        if label not in self._d:
            self._d[label] = len(self._d) + 1
        return self._d[label]


def label_sequence(
    conn: sqlite3.Connection, agent_id: str, intern: Interner,
) -> tuple[list[int], list[str]]:
    """Ordered (integer-label sequence, call_id list) for one agent."""
    rows = conn.execute(
        "SELECT call_id, tool_name, input FROM tool_calls "
        "WHERE agent_id = ? ORDER BY started_at, call_id",
        (agent_id,),
    ).fetchall()
    labels = [intern(node_label(r[1], r[2])) for r in rows]
    return labels, [r[0] for r in rows]


def reuse_rate(conn: sqlite3.Connection, agent_id: str) -> float:
    """n_calls / n_distinct_normalized_labels for one agent (G3 metric)."""
    intern = Interner()
    labels, _ = label_sequence(conn, agent_id, intern)
    return len(labels) / len(set(labels)) if labels else 0.0


_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def bm25_pair(
    failed_task: str, successes: list[tuple[str, str]],
) -> str | None:
    """Top-1 BM25 (FTS5 default rank) pairing of a failed episode's
    VERBATIM task text against success task texts.

    successes: list of (agent_id, task_text). Returns paired agent_id.
    """
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE t USING fts5(agent_id UNINDEXED, task)")
    db.executemany("INSERT INTO t (agent_id, task) VALUES (?, ?)", successes)
    toks = _TOKEN.findall(failed_task)
    if not toks:
        return None
    q = " OR ".join(f'"{t}"' for t in toks)
    row = db.execute(
        "SELECT agent_id FROM t WHERE t MATCH ? ORDER BY rank LIMIT 1", (q,)
    ).fetchone()
    db.close()
    return row[0] if row else None


def gdl_predict(
    conn: sqlite3.Connection, failed_agent: str, success_agent: str,
) -> str:
    """Frozen GDL: earliest divergence of failed vs paired success.

    Returns the predicted decisive call_id on the FAILED side.
    """
    intern = Interner()
    f_labels, f_calls = label_sequence(conn, failed_agent, intern)
    s_labels, _ = label_sequence(conn, success_agent, intern)
    sm = SequenceMatcher(None, f_labels, s_labels, autojunk=False)
    for tag, i1, _i2, _j1, _j2 in sm.get_opcodes():
        if tag != "equal":
            idx = min(i1, len(f_calls) - 1)
            return f_calls[idx]
    return f_calls[-1]  # identical sequences: predict last step (frozen rule)
