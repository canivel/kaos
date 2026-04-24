"""Cross-agent memory store backed by SQLite FTS5.

Inspired by claude-mem (Alex Newman / @thedotmack, github.com/thedotmack/claude-mem, AGPL-3.0).
Adapted for KAOS's multi-agent, multi-session architecture with SQLite FTS5 full-text search.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any

MEMORY_TYPES = ("observation", "result", "skill", "insight", "error")


@dataclass
class MemoryEntry:
    memory_id: int
    agent_id: str
    type: str
    key: str | None
    content: str
    metadata: dict[str, Any]
    created_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "MemoryEntry":
        return cls(
            memory_id=row["memory_id"],
            agent_id=row["agent_id"],
            type=row["type"],
            key=row["key"],
            content=row["content"],
            metadata=json.loads(row["metadata"] or "{}"),
            created_at=row["created_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "agent_id": self.agent_id,
            "type": self.type,
            "key": self.key,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at,
        }


class MemoryStore:
    """Persistent, searchable cross-agent memory for a KAOS project.

    All agents in the same .db file share a single memory store.  Agents write
    typed entries (observation, result, skill, insight, error) and any agent
    can search across all entries using SQLite FTS5 with porter stemming.

    Usage::

        from kaos import Kaos
        from kaos.memory import MemoryStore

        kaos = Kaos("project.db")
        mem  = MemoryStore(kaos.conn)

        # Write a result after completing a task
        mid = mem.write(
            agent_id="agent-01",
            content="Accuracy improved to 87% by switching to ensemble voting.",
            type="result",
            key="ensemble-voting-v3",
        )

        # Search from another agent
        hits = mem.search("ensemble accuracy")
        for h in hits:
            print(h.content)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    # ── Write ────────────────────────────────────────────────────────

    def write(
        self,
        agent_id: str,
        content: str,
        type: str = "observation",
        key: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        """Persist a memory entry and return its memory_id.

        Args:
            agent_id: ID of the agent writing the memory.
            content:  Free-text content (indexed by FTS5).
            type:     One of observation | result | skill | insight | error.
            key:      Optional human-readable key (also FTS-indexed).
            metadata: Arbitrary JSON-serialisable dict stored alongside the entry.

        Returns:
            The integer memory_id of the new entry.
        """
        if type not in MEMORY_TYPES:
            raise ValueError(f"type must be one of {MEMORY_TYPES!r}, got {type!r}")

        cur = self._conn.execute(
            """
            INSERT INTO memory (agent_id, type, key, content, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (agent_id, type, key, content, json.dumps(metadata or {})),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ── Search ───────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 10,
        type: str | None = None,
        agent_id: str | None = None,
        rank: str = "bm25",
        record_hits: bool = False,
        requesting_agent_id: str | None = None,
    ) -> list[MemoryEntry]:
        """Full-text search over memory content and keys.

        Uses SQLite FTS5 with porter stemming. BM25 relevance by default.

        Args:
            query:    FTS5 query string (supports phrases "like this", NOT, OR, *).
            limit:    Maximum number of results to return.
            type:     Optional filter by memory type.
            agent_id: Optional filter to a single agent's memories.
            rank:     ``"bm25"`` (default) or ``"weighted"``. Weighted rank
                      multiplies bm25 relevance by retrieval-frequency and
                      recency signals populated by ``kaos dream``.
            record_hits: If True, write each returned entry to ``memory_hits``
                      so plasticity can learn which memories are actually
                      consulted.
            requesting_agent_id: Written to memory_hits when record_hits=True.

        Returns:
            List of MemoryEntry sorted by the chosen ranking (best first).
        """
        filters: list[str] = []
        params: list[Any] = [query]

        if type:
            filters.append("m.type = ?")
            params.append(type)
        if agent_id:
            filters.append("m.agent_id = ?")
            params.append(agent_id)

        where = ("AND " + " AND ".join(filters)) if filters else ""
        fetch = limit * 4 if rank == "weighted" else limit
        params.append(fetch)

        rows = self._conn.execute(
            f"""
            SELECT m.memory_id, m.agent_id, m.type, m.key,
                   m.content, m.metadata, m.created_at,
                   bm25(memory_fts) AS bm25_raw
            FROM memory_fts f
            JOIN memory m ON m.memory_id = f.memory_id
            WHERE memory_fts MATCH ?
            {where}
            ORDER BY rank
            LIMIT ?
            """,
            params,
        ).fetchall()
        entries = [MemoryEntry.from_row(r) for r in rows]

        if rank == "weighted":
            from kaos.dream.signals import weighted_score
            hits_by_id, last_hit_by_id = _memory_hits_map(
                self._conn, [e.memory_id for e in entries]
            )
            bm25_by_id = {r["memory_id"]: -float(r["bm25_raw"] or 0.0) for r in rows}

            def score(e: MemoryEntry) -> float:
                hits = hits_by_id.get(e.memory_id, 0)
                return weighted_score(
                    bm25_score=bm25_by_id.get(e.memory_id, 1.0),
                    uses=hits,
                    successes=hits,  # every retrieval counts as a positive signal
                    last_used_at=last_hit_by_id.get(e.memory_id) or e.created_at,
                )

            entries = sorted(entries, key=score, reverse=True)

        entries = entries[:limit]

        if record_hits and entries:
            try:
                self._conn.executemany(
                    "INSERT INTO memory_hits (memory_id, agent_id, query, rank_pos) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (e.memory_id, requesting_agent_id, query, i + 1)
                        for i, e in enumerate(entries)
                    ],
                )
                self._conn.commit()
            except sqlite3.OperationalError:
                pass
            # Automatic plasticity: associate co-retrieved memories with each
            # other, and with any skills the requesting agent has already used.
            try:
                from kaos.dream import auto as _auto
                _auto.on_memory_hits(
                    self._conn,
                    [e.memory_id for e in entries],
                    requesting_agent_id=requesting_agent_id,
                )
            except Exception:
                pass

        return entries

    # ── List ─────────────────────────────────────────────────────────

    def list(
        self,
        agent_id: str | None = None,
        type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MemoryEntry]:
        """List memory entries (most recent first), with optional filters.

        Args:
            agent_id: Restrict to one agent.
            type:     Restrict to one memory type.
            limit:    Page size.
            offset:   Pagination offset.
        """
        clauses: list[str] = []
        params: list[Any] = []

        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if type:
            clauses.append("type = ?")
            params.append(type)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params += [limit, offset]

        rows = self._conn.execute(
            f"""
            SELECT memory_id, agent_id, type, key, content, metadata, created_at
            FROM memory
            {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        return [MemoryEntry.from_row(r) for r in rows]

    # ── Get ──────────────────────────────────────────────────────────

    def get(self, memory_id: int) -> MemoryEntry | None:
        """Fetch a single entry by its primary key."""
        row = self._conn.execute(
            """
            SELECT memory_id, agent_id, type, key, content, metadata, created_at
            FROM memory WHERE memory_id = ?
            """,
            (memory_id,),
        ).fetchone()
        return MemoryEntry.from_row(row) if row else None

    def get_by_key(self, key: str, agent_id: str | None = None) -> MemoryEntry | None:
        """Fetch the most-recent entry with a given key."""
        params: list[Any] = [key]
        extra = ""
        if agent_id:
            extra = "AND agent_id = ?"
            params.append(agent_id)
        row = self._conn.execute(
            f"""
            SELECT memory_id, agent_id, type, key, content, metadata, created_at
            FROM memory
            WHERE key = ? {extra}
            ORDER BY created_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
        return MemoryEntry.from_row(row) if row else None

    # ── Delete ───────────────────────────────────────────────────────

    def delete(self, memory_id: int) -> bool:
        """Delete an entry by memory_id. Returns True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM memory WHERE memory_id = ?", (memory_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ── Stats ────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return per-type counts and total entries."""
        rows = self._conn.execute(
            "SELECT type, COUNT(*) AS n FROM memory GROUP BY type"
        ).fetchall()
        total = self._conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0]
        return {
            "total": total,
            "by_type": {r["type"]: r["n"] for r in rows},
        }


def _memory_hits_map(
    conn: sqlite3.Connection, memory_ids: list[int]
) -> tuple[dict[int, int], dict[int, str]]:
    """Return ({id: hit_count}, {id: last_hit_at}) for the given memory IDs.

    Swallows OperationalError so this works on pre-v4 databases that don't
    have the memory_hits table.
    """
    if not memory_ids:
        return {}, {}
    placeholders = ",".join("?" * len(memory_ids))
    try:
        rows = conn.execute(
            f"SELECT memory_id, COUNT(*) AS n, MAX(hit_at) AS last_hit "
            f"FROM memory_hits WHERE memory_id IN ({placeholders}) "
            f"GROUP BY memory_id",
            memory_ids,
        ).fetchall()
    except sqlite3.OperationalError:
        return {}, {}
    counts = {r["memory_id"]: r["n"] for r in rows}
    lasts = {r["memory_id"]: r["last_hit"] for r in rows if r["last_hit"]}
    return counts, lasts
