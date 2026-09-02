"""ExperimentStore — journal of probe / mh_search / benchmark runs.

The v0.9 "queryability" gap was: when a verdict lands (ACCEPT / REJECT /
VOID), nothing in KAOS records it durably alongside the git sha, the
lock hash, and the per-arm stats. The next person — or the same person
a month later — has to grep commits to figure out which run produced
which result. ExperimentStore closes that.

Append-only. One row per run. No mutation API beyond ``log_run``; query
APIs return rows untouched. Storage piggy-backs on the existing
``kaos.db`` (no new file) via the v9 migration.
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from kaos.schema import init_schema


def _current_git_sha() -> str | None:
    """Best-effort: returns HEAD sha or None outside a git checkout."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=2.0,
        )
        if out.returncode == 0:
            return out.stdout.strip() or None
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


@dataclass
class Experiment:
    exp_id: int
    name: str
    family: str | None
    git_sha: str | None
    lock_sha256: str | None
    started_at: str
    finished_at: str | None
    duration_ms: int | None
    verdict: str | None
    judge_kappa: float | None
    arms: dict
    gates: list
    metadata: dict
    results_path: str | None


class ExperimentStore:
    """SQLite-backed journal. Opens its own connection on a shared
    ``kaos.db`` path so callers don't need a Kaos instance."""

    def __init__(self, db_path: str | Path = "kaos.db") -> None:
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        init_schema(self._conn)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "ExperimentStore":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── write ────────────────────────────────────────────────────────

    def log_run(
        self,
        *,
        name: str,
        family: str | None = None,
        verdict: str | None = None,
        judge_kappa: float | None = None,
        arms: dict | None = None,
        gates: Iterable[dict] | None = None,
        lock_sha256: str | None = None,
        git_sha: str | None = None,
        metadata: dict | None = None,
        results_path: str | Path | None = None,
        started_at: str | None = None,
        finished_at: str | None = None,
        duration_ms: int | None = None,
    ) -> int:
        """Insert one experiment row and return its exp_id.

        git_sha defaults to ``git rev-parse HEAD`` if omitted; pass
        ``""`` to suppress that auto-fill (useful in tests).
        """
        sha = git_sha if git_sha is not None else _current_git_sha()
        cur = self._conn.execute(
            """
            INSERT INTO experiments (
                name, family, git_sha, lock_sha256,
                started_at, finished_at, duration_ms,
                verdict, judge_kappa,
                arms_json, gates_json, metadata, results_path
            ) VALUES (
                ?, ?, ?, ?,
                COALESCE(?, strftime('%Y-%m-%dT%H:%M:%f','now')),
                ?, ?,
                ?, ?,
                ?, ?, ?, ?
            )
            """,
            (
                name, family, sha or None, lock_sha256,
                started_at,
                finished_at, duration_ms,
                verdict, judge_kappa,
                json.dumps(arms or {}),
                json.dumps(list(gates or [])),
                json.dumps(metadata or {}),
                str(results_path) if results_path else None,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    # ── read ─────────────────────────────────────────────────────────

    def get(self, exp_id: int) -> Experiment | None:
        row = self._conn.execute(
            "SELECT * FROM experiments WHERE exp_id = ?", (exp_id,)
        ).fetchone()
        return self._row_to_experiment(row) if row else None

    def list(
        self,
        *,
        name: str | None = None,
        family: str | None = None,
        verdict_prefix: str | None = None,
        limit: int = 50,
    ) -> list[Experiment]:
        sql = "SELECT * FROM experiments"
        clauses: list[str] = []
        params: list[Any] = []
        if name:
            clauses.append("name = ?")
            params.append(name)
        if family:
            clauses.append("family = ?")
            params.append(family)
        if verdict_prefix:
            clauses.append("verdict LIKE ?")
            params.append(verdict_prefix + "%")
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        # exp_id breaks ties: runs logged within the same millisecond (fast CI
        # runners, batch loggers) must still list newest-first deterministically
        sql += " ORDER BY started_at DESC, exp_id DESC LIMIT ?"
        params.append(int(limit))
        rows = self._conn.execute(sql, params).fetchall()
        return [self._row_to_experiment(r) for r in rows]

    def compare(self, a_id: int, b_id: int) -> dict:
        """Diff two experiment rows. Returns a dict with the shared
        fields and a ``changes`` map of field -> (a_val, b_val) for
        any field that differs. Useful for "what's new since run X?".
        """
        a, b = self.get(a_id), self.get(b_id)
        if a is None or b is None:
            raise ValueError(f"missing experiment(s): {a_id}, {b_id}")
        changes: dict[str, tuple] = {}
        for field in (
            "name", "family", "git_sha", "lock_sha256", "verdict",
            "judge_kappa", "results_path",
        ):
            va, vb = getattr(a, field), getattr(b, field)
            if va != vb:
                changes[field] = (va, vb)
        # arms / gates differ structurally — record bool only
        if a.arms != b.arms:
            changes["arms"] = ("differs", "differs")
        if a.gates != b.gates:
            changes["gates"] = ("differs", "differs")
        return {
            "a": {"exp_id": a.exp_id, "started_at": a.started_at},
            "b": {"exp_id": b.exp_id, "started_at": b.started_at},
            "changes": changes,
        }

    # ── helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _row_to_experiment(row: sqlite3.Row) -> Experiment:
        return Experiment(
            exp_id=int(row["exp_id"]),
            name=row["name"],
            family=row["family"],
            git_sha=row["git_sha"],
            lock_sha256=row["lock_sha256"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            duration_ms=row["duration_ms"],
            verdict=row["verdict"],
            judge_kappa=row["judge_kappa"],
            arms=json.loads(row["arms_json"] or "{}"),
            gates=json.loads(row["gates_json"] or "[]"),
            metadata=json.loads(row["metadata"] or "{}"),
            results_path=row["results_path"],
        )
