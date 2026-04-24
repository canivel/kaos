"""Associations phase — read the Hebbian graph populated by the auto hooks.

The heavy lifting is already done inline (kaos/dream/auto.py), so this phase
is mostly a query surface for the narrative phase, the CLI, and downstream
callers. It also applies a lazy exponential decay on weights so edges that
haven't fired recently naturally fade.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone

from kaos.dream.signals import DEFAULT_HALF_LIFE_DAYS, now_utc, recency_weight


@dataclass
class AssocEdge:
    kind_a: str
    id_a: int
    label_a: str
    kind_b: str
    id_b: int
    label_b: str
    weight: float
    decayed_weight: float
    uses: int
    last_seen: str


@dataclass
class AssociationsReport:
    total_edges: int = 0
    top_edges: list[AssocEdge] = field(default_factory=list)
    # Quick lookups for the narrative
    top_skill_skill: list[AssocEdge] = field(default_factory=list)
    top_skill_memory: list[AssocEdge] = field(default_factory=list)
    top_memory_memory: list[AssocEdge] = field(default_factory=list)


def run(
    conn: sqlite3.Connection,
    *,
    now: datetime | None = None,
    top_n: int = 15,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
) -> AssociationsReport:
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    now_dt = now or now_utc()
    try:
        try:
            rows = conn.execute(
                "SELECT kind_a, id_a, kind_b, id_b, weight, uses, last_seen "
                "FROM associations ORDER BY weight DESC"
            ).fetchall()
        except sqlite3.OperationalError:
            return AssociationsReport()

        if not rows:
            return AssociationsReport()

        labels = _label_map(conn)
    finally:
        conn.row_factory = prev

    edges: list[AssocEdge] = []
    for r in rows:
        w = r["weight"] or 0.0
        decay = recency_weight(r["last_seen"], now=now_dt,
                               half_life_days=half_life_days)
        edges.append(AssocEdge(
            kind_a=r["kind_a"], id_a=r["id_a"],
            label_a=labels.get((r["kind_a"], r["id_a"]), f"{r['kind_a']}:{r['id_a']}"),
            kind_b=r["kind_b"], id_b=r["id_b"],
            label_b=labels.get((r["kind_b"], r["id_b"]), f"{r['kind_b']}:{r['id_b']}"),
            weight=w,
            decayed_weight=w * decay,
            uses=r["uses"] or 0,
            last_seen=r["last_seen"],
        ))

    # Deduplicate directed pairs — we store both (a,b) and (b,a). For the
    # top-N view we want the canonical (lexicographically smaller) ordering.
    canonical: dict[tuple, AssocEdge] = {}
    for e in edges:
        a_key = (e.kind_a, e.id_a)
        b_key = (e.kind_b, e.id_b)
        key = (min(a_key, b_key), max(a_key, b_key))
        if key not in canonical or e.decayed_weight > canonical[key].decayed_weight:
            # Flip to canonical ordering so output is stable
            if a_key <= b_key:
                canonical[key] = e
            else:
                canonical[key] = AssocEdge(
                    kind_a=e.kind_b, id_a=e.id_b, label_a=e.label_b,
                    kind_b=e.kind_a, id_b=e.id_a, label_b=e.label_a,
                    weight=e.weight, decayed_weight=e.decayed_weight,
                    uses=e.uses, last_seen=e.last_seen,
                )

    deduped = sorted(canonical.values(), key=lambda e: -e.decayed_weight)

    report = AssociationsReport(
        total_edges=len(deduped),
        top_edges=deduped[:top_n],
    )
    report.top_skill_skill = [e for e in deduped
                              if e.kind_a == "skill" and e.kind_b == "skill"][:top_n]
    report.top_skill_memory = [e for e in deduped
                               if {e.kind_a, e.kind_b} == {"skill", "memory"}][:top_n]
    report.top_memory_memory = [e for e in deduped
                                if e.kind_a == "memory" and e.kind_b == "memory"][:top_n]
    return report


def related(
    conn: sqlite3.Connection,
    kind: str,
    entity_id: int,
    *,
    limit: int = 10,
    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
    now: datetime | None = None,
) -> list[AssocEdge]:
    """Return the top-N entities most strongly associated with the given one.

    Handles both directions because the table stores both orderings.
    """
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    now_dt = now or now_utc()
    try:
        try:
            rows = conn.execute(
                "SELECT kind_a, id_a, kind_b, id_b, weight, uses, last_seen "
                "FROM associations "
                "WHERE kind_a = ? AND id_a = ? "
                "ORDER BY weight DESC LIMIT ?",
                (kind, entity_id, limit * 3),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        labels = _label_map(conn)
    finally:
        conn.row_factory = prev

    edges: list[AssocEdge] = []
    for r in rows:
        w = r["weight"] or 0.0
        decay = recency_weight(r["last_seen"], now=now_dt,
                               half_life_days=half_life_days)
        edges.append(AssocEdge(
            kind_a=r["kind_a"], id_a=r["id_a"],
            label_a=labels.get((r["kind_a"], r["id_a"]), f"{r['kind_a']}:{r['id_a']}"),
            kind_b=r["kind_b"], id_b=r["id_b"],
            label_b=labels.get((r["kind_b"], r["id_b"]), f"{r['kind_b']}:{r['id_b']}"),
            weight=w,
            decayed_weight=w * decay,
            uses=r["uses"] or 0,
            last_seen=r["last_seen"],
        ))
    edges.sort(key=lambda e: -e.decayed_weight)
    return edges[:limit]


def _label_map(conn: sqlite3.Connection) -> dict[tuple[str, int], str]:
    """Build {(kind, id): human_label} for skills and memory."""
    labels: dict[tuple[str, int], str] = {}
    try:
        for r in conn.execute("SELECT skill_id, name FROM agent_skills"):
            labels[("skill", r["skill_id"])] = r["name"]
    except sqlite3.OperationalError:
        pass
    try:
        for r in conn.execute("SELECT memory_id, key FROM memory"):
            labels[("memory", r["memory_id"])] = r["key"] or f"memory-{r['memory_id']}"
    except sqlite3.OperationalError:
        pass
    return labels
