"""Cross-agent skill library backed by SQLite FTS5.

Inspired by the Externalization framework in:
  "Externalization in LLM Agents: A Unified Review of Memory, Skills,
   Protocols and Harness Engineering"
  Zhou et al. 2026, arXiv:2604.08224

Skills are *procedural* artifacts — parameterized templates that encode
reusable solution patterns.  They are distinct from memory entries
(episodic / factual) and complement them:

  memory → "Accuracy was 87% on dataset X using ensemble voting"
  skill  → "To improve classification: try ensemble with {n_models} models,
             use {voting} voting, tune threshold to {threshold}"

Any agent in the project can save a skill.  Any agent can search and
apply skills using SQLite FTS5 with porter stemming.  Usage outcomes
(success / failure) are tracked so agents can rank skills by reliability.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from string import Formatter
from typing import Any


@dataclass
class Skill:
    skill_id: int
    name: str
    description: str
    template: str
    tags: list[str]
    source_agent_id: str | None
    use_count: int
    success_count: int
    created_at: str
    updated_at: str

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Skill":
        tags = row["tags"]
        return cls(
            skill_id=row["skill_id"],
            name=row["name"],
            description=row["description"],
            template=row["template"],
            tags=json.loads(tags) if tags else [],
            source_agent_id=row["source_agent_id"],
            use_count=row["use_count"],
            success_count=row["success_count"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "template": self.template,
            "tags": self.tags,
            "source_agent_id": self.source_agent_id,
            "use_count": self.use_count,
            "success_count": self.success_count,
            "success_rate": round(self.success_count / self.use_count, 3) if self.use_count else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    def params(self) -> list[str]:
        """Return the list of template parameter names (e.g. {model} → ['model'])."""
        return [
            field_name
            for _, field_name, _, _ in Formatter().parse(self.template)
            if field_name is not None
        ]

    def apply(self, **kwargs: str) -> str:
        """Render the skill template with the provided parameters.

        Unrecognised keys are silently ignored.  Missing keys raise KeyError.
        """
        return self.template.format_map(kwargs)


class SkillStore:
    """Persistent, searchable cross-agent skill library for a KAOS project.

    All agents in the same .db file share a single skill store.  Agents save
    skills (parameterised prompt templates) and any agent can search across
    them using SQLite FTS5 with porter stemming.

    Usage::

        from kaos import Kaos
        from kaos.skills import SkillStore

        kaos = Kaos("project.db")
        sk   = SkillStore(kaos.conn)

        # Save a skill after discovering a reliable pattern
        sid = sk.save(
            source_agent_id="agent-01",
            name="ensemble_classifier",
            description="Improve classification accuracy with ensemble voting",
            template="Implement a {n_models}-model ensemble using {voting} voting. "
                     "Tune decision threshold to {threshold}.",
            tags=["classification", "ensemble", "accuracy"],
        )

        # Search from another agent before starting a similar task
        hits = sk.search("classification accuracy")
        for s in hits:
            print(s.name, s.apply(n_models="3", voting="majority", threshold="0.5"))

        # Record outcomes to track reliability
        sk.record_outcome(sid, success=True)
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.row_factory = sqlite3.Row

    # ── Save ─────────────────────────────────────────────────────────

    def save(
        self,
        name: str,
        description: str,
        template: str,
        source_agent_id: str | None = None,
        tags: list[str] | None = None,
    ) -> int:
        """Save a new skill and return its skill_id.

        Args:
            name:             Short identifier (snake_case recommended).
            description:      What the skill does and when to use it.
            template:         Prompt template — use {param} for variable parts.
            source_agent_id:  Agent that discovered this skill.
            tags:             List of topic tags for faceted search.

        Returns:
            Integer skill_id of the new entry.
        """
        tags_json = json.dumps(tags or [])
        cur = self._conn.execute(
            """
            INSERT INTO agent_skills (name, description, template, tags, source_agent_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, description, template, tags_json, source_agent_id),
        )
        self._conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ── Search ───────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        limit: int = 10,
        tag: str | None = None,
    ) -> list[Skill]:
        """Full-text search over skill name, description, tags, and template.

        Uses SQLite FTS5 with porter stemming.  Results are ranked by BM25
        relevance (most relevant first).

        Args:
            query: FTS5 query string (supports phrases "like this", NOT, OR, *).
            limit: Maximum number of results.
            tag:   Optional exact-match tag filter applied after FTS ranking.

        Returns:
            List of Skill sorted by relevance (best first).
        """
        params: list[Any] = [query, limit]
        rows = self._conn.execute(
            """
            SELECT s.skill_id, s.name, s.description, s.template, s.tags,
                   s.source_agent_id, s.use_count, s.success_count,
                   s.created_at, s.updated_at
            FROM agent_skills_fts f
            JOIN agent_skills s ON s.skill_id = f.rowid
            WHERE agent_skills_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            params,
        ).fetchall()
        skills = [Skill.from_row(r) for r in rows]
        if tag:
            skills = [s for s in skills if tag in s.tags]
        return skills

    # ── Get / List ───────────────────────────────────────────────────

    def get(self, skill_id: int) -> Skill | None:
        """Fetch a single skill by its primary key."""
        row = self._conn.execute(
            """
            SELECT skill_id, name, description, template, tags,
                   source_agent_id, use_count, success_count, created_at, updated_at
            FROM agent_skills WHERE skill_id = ?
            """,
            (skill_id,),
        ).fetchone()
        return Skill.from_row(row) if row else None

    def list(
        self,
        tag: str | None = None,
        source_agent_id: str | None = None,
        order_by: str = "created_at",
        limit: int = 50,
        offset: int = 0,
    ) -> list[Skill]:
        """List skills (most recent first by default), with optional filters.

        Args:
            tag:              Filter to skills containing this tag.
            source_agent_id:  Filter to skills saved by one agent.
            order_by:         Column to sort by: created_at | success_count | use_count.
            limit:            Page size.
            offset:           Pagination offset.
        """
        allowed = {"created_at", "success_count", "use_count", "name"}
        if order_by not in allowed:
            order_by = "created_at"

        clauses: list[str] = []
        params: list[Any] = []

        if source_agent_id:
            clauses.append("source_agent_id = ?")
            params.append(source_agent_id)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params += [limit, offset]

        rows = self._conn.execute(
            f"""
            SELECT skill_id, name, description, template, tags,
                   source_agent_id, use_count, success_count, created_at, updated_at
            FROM agent_skills
            {where}
            ORDER BY {order_by} DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        skills = [Skill.from_row(r) for r in rows]
        if tag:
            skills = [s for s in skills if tag in s.tags]
        return skills

    # ── Outcome tracking ─────────────────────────────────────────────

    def record_outcome(self, skill_id: int, success: bool) -> None:
        """Record whether applying a skill succeeded or failed.

        Increments use_count always; increments success_count only on success.
        This lets agents rank skills by reliability (success_count / use_count).
        """
        if success:
            self._conn.execute(
                """
                UPDATE agent_skills
                SET use_count = use_count + 1,
                    success_count = success_count + 1,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%f','now')
                WHERE skill_id = ?
                """,
                (skill_id,),
            )
        else:
            self._conn.execute(
                """
                UPDATE agent_skills
                SET use_count = use_count + 1,
                    updated_at = strftime('%Y-%m-%dT%H:%M:%f','now')
                WHERE skill_id = ?
                """,
                (skill_id,),
            )
        self._conn.commit()

    # ── Delete ───────────────────────────────────────────────────────

    def delete(self, skill_id: int) -> bool:
        """Delete a skill by skill_id. Returns True if a row was removed."""
        cur = self._conn.execute(
            "DELETE FROM agent_skills WHERE skill_id = ?", (skill_id,)
        )
        self._conn.commit()
        return cur.rowcount > 0

    # ── Stats ────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        """Return skill counts and top skills by success rate."""
        total = self._conn.execute("SELECT COUNT(*) FROM agent_skills").fetchone()[0]
        top = self._conn.execute(
            """
            SELECT name, use_count, success_count,
                   CASE WHEN use_count > 0
                        THEN ROUND(CAST(success_count AS REAL) / use_count, 3)
                        ELSE NULL END AS success_rate
            FROM agent_skills
            WHERE use_count > 0
            ORDER BY success_rate DESC
            LIMIT 5
            """
        ).fetchall()
        return {
            "total": total,
            "top_by_success_rate": [dict(r) for r in top],
        }
