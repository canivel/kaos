"""
Persistent SQLite store for memory-curator: recall telemetry, score-run history,
and archive/reject/restore decisions. Lives under the memory dir's .curator/ so
the telemetry travels with the data it describes. Dependency-free (stdlib sqlite3).
"""
from __future__ import annotations

import datetime as dt
import os
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS recall_events (
    id      INTEGER PRIMARY KEY,
    slug    TEXT NOT NULL,
    ts      TEXT NOT NULL,           -- ISO date
    session TEXT,
    kind    TEXT NOT NULL DEFAULT 'read'   -- read | backfill
);
CREATE INDEX IF NOT EXISTS ix_recall_slug ON recall_events(slug);
CREATE UNIQUE INDEX IF NOT EXISTS ux_recall_dedup
    ON recall_events(slug, ts, session, kind);

CREATE TABLE IF NOT EXISTS runs (
    id           INTEGER PRIMARY KEY,
    ts           TEXT NOT NULL,
    n_scored     INTEGER,
    n_candidates INTEGER
);

CREATE TABLE IF NOT EXISTS scores (
    run_id     INTEGER,
    slug       TEXT,
    p          REAL,
    stale      REAL, complete REAL, incorrect REAL, durability REAL, reuse REAL,
    verdict    TEXT
);
CREATE INDEX IF NOT EXISTS ix_scores_slug ON scores(slug);

CREATE TABLE IF NOT EXISTS decisions (
    id     INTEGER PRIMARY KEY,
    slug   TEXT NOT NULL,
    ts     TEXT NOT NULL,
    action TEXT NOT NULL,            -- archived | rejected | restored
    p      REAL,
    reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_dec_slug ON decisions(slug);
"""


def _today() -> str:
    return dt.date.today().isoformat()


class Store:
    def __init__(self, mem_dir: Path):
        self.dir = Path(mem_dir) / ".curator"
        self.dir.mkdir(exist_ok=True)
        self.path = self.dir / "memory_curator.db"
        self.db = sqlite3.connect(self.path)
        self.db.executescript(SCHEMA)
        self.db.commit()

    # --- telemetry ---------------------------------------------------------
    def log_recall(self, slug: str, ts: str | None = None,
                   session: str | None = None, kind: str = "read") -> bool:
        try:
            self.db.execute(
                "INSERT OR IGNORE INTO recall_events(slug,ts,session,kind) "
                "VALUES (?,?,?,?)",
                (slug, ts or _today(), session, kind),
            )
            self.db.commit()
            return True
        except sqlite3.Error:
            return False

    def recall_counts(self, window_days: int = 90) -> dict[str, int]:
        cutoff = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
        rows = self.db.execute(
            "SELECT slug, COUNT(*) FROM recall_events WHERE ts >= ? GROUP BY slug",
            (cutoff,),
        ).fetchall()
        return {slug: n for slug, n in rows}

    # --- decisions / cooldown ---------------------------------------------
    def record_decision(self, slug: str, action: str,
                        p: float | None = None, reason: str = "") -> None:
        self.db.execute(
            "INSERT INTO decisions(slug,ts,action,p,reason) VALUES (?,?,?,?,?)",
            (slug, _today(), action, p, reason),
        )
        self.db.commit()

    def cooled_down(self, window_days: int = 30) -> set[str]:
        """Slugs rejected within the window — suppress from candidate status."""
        cutoff = (dt.date.today() - dt.timedelta(days=window_days)).isoformat()
        rows = self.db.execute(
            "SELECT DISTINCT slug FROM decisions "
            "WHERE action='rejected' AND ts >= ?",
            (cutoff,),
        ).fetchall()
        return {r[0] for r in rows}

    # --- run history -------------------------------------------------------
    def record_run(self, scored, n_candidates: int) -> int:
        cur = self.db.execute(
            "INSERT INTO runs(ts,n_scored,n_candidates) VALUES (?,?,?)",
            (_today(), len(scored), n_candidates),
        )
        run_id = cur.lastrowid
        self.db.executemany(
            "INSERT INTO scores(run_id,slug,p,stale,complete,incorrect,"
            "durability,reuse,verdict) VALUES (?,?,?,?,?,?,?,?,?)",
            [(run_id, m.slug, m.p_archive, m.stale, m.complete, m.incorrect,
              m.durability, m.reuse, m.verdict) for m in scored],
        )
        self.db.commit()
        return run_id

    def history(self, slug: str, limit: int = 20) -> dict:
        recalls = self.db.execute(
            "SELECT ts,kind,session FROM recall_events WHERE slug=? "
            "ORDER BY ts DESC LIMIT ?", (slug, limit)).fetchall()
        decisions = self.db.execute(
            "SELECT ts,action,p,reason FROM decisions WHERE slug=? "
            "ORDER BY ts DESC LIMIT ?", (slug, limit)).fetchall()
        trend = self.db.execute(
            "SELECT r.ts,s.p,s.verdict FROM scores s JOIN runs r ON r.id=s.run_id "
            "WHERE s.slug=? ORDER BY r.ts DESC LIMIT ?", (slug, limit)).fetchall()
        return {"recalls": recalls, "decisions": decisions, "trend": trend}

    def close(self) -> None:
        self.db.close()
