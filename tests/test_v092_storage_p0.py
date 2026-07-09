"""v0.9.2 Tier-0 — core storage P0 regressions (RED-FIRST).

Each test in this file reproduces a P0 the v0.10 scoping panel found and
verified in source. They are written to FAIL on the pre-fix code and pass
after the fix, per the gate-first discipline (G1..G5 in
docs/roadmap/v0.10-candidates.md, candidate core-storage-hardening).
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

import pytest

from kaos import Kaos


@pytest.fixture
def kaos(tmp_path: Path) -> Kaos:
    k = Kaos(db_path=str(tmp_path / "kaos.db"))
    yield k
    k.close()


# ── G1: write() version collision ────────────────────────────────────


class TestVersionCollision:
    def test_write_after_delete_does_not_crash(self, kaos: Kaos):
        """delete-then-rewrite must not hit UNIQUE(agent_id,path,version).
        Pre-fix: MAX(version) over deleted=0 rows resets to 1 and collides
        with the soft-deleted version-1 tombstone."""
        a = kaos.spawn("agent")
        kaos.write(a, "/f.txt", b"v1")
        kaos.delete(a, "/f.txt")
        # This is the crash on pre-fix code:
        kaos.write(a, "/f.txt", b"v2")
        assert kaos.read(a, "/f.txt") == b"v2"

    def test_repeated_delete_rewrite_cycles(self, kaos: Kaos):
        a = kaos.spawn("agent")
        for i in range(5):
            kaos.write(a, "/f.txt", f"v{i}".encode())
            kaos.delete(a, "/f.txt")
        kaos.write(a, "/f.txt", b"final")
        assert kaos.read(a, "/f.txt") == b"final"

    def test_write_after_restore_does_not_crash(self, kaos: Kaos):
        """checkpoint -> write -> restore -> write must not collide."""
        a = kaos.spawn("agent")
        kaos.write(a, "/f.txt", b"v1")
        cp = kaos.checkpoint(a, label="cp1")
        kaos.write(a, "/f.txt", b"v2")
        kaos.restore(a, cp)
        # writing after a restore previously collided on version numbers
        kaos.write(a, "/f.txt", b"v3")
        assert kaos.read(a, "/f.txt") == b"v3"

    def test_versions_are_strictly_monotonic_across_tombstones(self, kaos: Kaos):
        a = kaos.spawn("agent")
        kaos.write(a, "/f.txt", b"a")
        kaos.delete(a, "/f.txt")
        kaos.write(a, "/f.txt", b"b")
        versions = [
            r[0]
            for r in kaos.conn.execute(
                "SELECT version FROM files WHERE agent_id=? AND path=? ORDER BY version",
                (a, "/f.txt"),
            ).fetchall()
        ]
        # no duplicate version numbers even across soft-deleted rows
        assert len(versions) == len(set(versions))


# ── G3: query() read-only enforcement ────────────────────────────────


class TestQueryReadOnly:
    ADVERSARIAL = [
        "REPLACE INTO agents (agent_id, name) VALUES ('x', 'y')",
        "INSERT INTO agents (agent_id, name) VALUES ('x', 'y')",
        "UPDATE agents SET name = 'z'",
        "DELETE FROM agents",
        "DROP TABLE agents",
        "ALTER TABLE agents ADD COLUMN hacked TEXT",
        "CREATE TABLE evil (x INTEGER)",
        "PRAGMA writable_schema = 1",
        "ATTACH DATABASE ':memory:' AS evil",
        "WITH x AS (SELECT 1) DELETE FROM agents",
        "VACUUM",
    ]

    @pytest.mark.parametrize("sql", ADVERSARIAL)
    def test_write_sql_is_rejected(self, kaos: Kaos, sql: str):
        with pytest.raises(PermissionError):
            kaos.query(sql)

    def test_write_via_query_leaves_db_unchanged(self, kaos: Kaos):
        a = kaos.spawn("agent")
        before = kaos.conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        for sql in ("DELETE FROM agents", "UPDATE agents SET name='z'",
                    "REPLACE INTO agents (agent_id,name) VALUES ('e','e')"):
            with pytest.raises(PermissionError):
                kaos.query(sql)
        after = kaos.conn.execute("SELECT COUNT(*) FROM agents").fetchone()[0]
        assert before == after
        assert kaos.conn.execute(
            "SELECT name FROM agents WHERE agent_id=?", (a,)
        ).fetchone()[0] == "agent"

    def test_legitimate_selects_still_work(self, kaos: Kaos):
        a = kaos.spawn("agent")
        rows = kaos.query("SELECT agent_id, name FROM agents WHERE agent_id = ?", (a,))
        assert rows and rows[0]["name"] == "agent"
        # aggregates + CTEs are legitimate read-only
        agg = kaos.query("SELECT COUNT(*) AS n FROM agents")
        assert agg[0]["n"] >= 1
        cte = kaos.query("WITH x AS (SELECT 1 AS v) SELECT v FROM x")
        assert cte[0]["v"] == 1


# ── G2: read() must not hold a write transaction / block writers ─────


class TestReaderDoesNotBlockWriters:
    def test_read_leaves_no_open_transaction(self, kaos: Kaos):
        a = kaos.spawn("agent")
        kaos.write(a, "/f.txt", b"data")
        kaos.read(a, "/f.txt")
        # Pre-fix: FILE_READ event INSERT leaves an uncommitted write txn open.
        assert kaos.conn.in_transaction is False

    def test_concurrent_reader_does_not_block_writer(self, tmp_path: Path):
        db = str(tmp_path / "kaos.db")
        k = Kaos(db_path=db)
        a = k.spawn("agent")
        k.write(a, "/f.txt", b"seed")

        errors: list[Exception] = []
        writer_done = threading.Event()

        def reader_loop():
            kr = Kaos(db_path=db)
            try:
                for _ in range(50):
                    kr.read(a, "/f.txt")
                    time.sleep(0.001)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                kr.close()

        def writer_loop():
            kw = Kaos(db_path=db)
            try:
                for i in range(50):
                    kw.write(a, "/f.txt", f"w{i}".encode())
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                writer_done.set()
                kw.close()

        rt = threading.Thread(target=reader_loop)
        wt = threading.Thread(target=writer_loop)
        rt.start(); wt.start()
        rt.join(timeout=30); wt.join(timeout=30)
        k.close()
        assert writer_done.is_set(), "writer never completed — reader blocked it"
        assert not errors, f"concurrent read/write raised: {errors}"


# ── Cross-thread helper connection correctness ───────────────────────


class TestThreadLocalHelpers:
    def test_write_from_second_thread_succeeds(self, tmp_path: Path):
        """Helpers (blobs/events/checkpoints) must resolve the CURRENT
        thread's connection, not the init thread's."""
        db = str(tmp_path / "kaos.db")
        k = Kaos(db_path=db)
        a = k.spawn("agent")
        errors: list[Exception] = []

        def worker():
            try:
                k.write(a, "/from_thread.txt", b"threaded")
                assert k.read(a, "/from_thread.txt") == b"threaded"
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        t = threading.Thread(target=worker)
        t.start(); t.join(timeout=15)
        k.close()
        assert not errors, f"cross-thread write failed: {errors}"


# ── G5: SharedLog position race ──────────────────────────────────────


class TestSharedLogPosition:
    def test_concurrent_appends_no_position_collision(self, tmp_path: Path):
        from kaos.shared_log import SharedLog

        db = str(tmp_path / "kaos.db")
        k = Kaos(db_path=db)
        errors: list[Exception] = []
        n_threads, per = 8, 40

        def appender(idx: int):
            kk = Kaos(db_path=db)
            log = SharedLog(kk.conn)
            try:
                for j in range(per):
                    log.append(f"agent-{idx}", "result", {"j": j})
            except Exception as e:  # noqa: BLE001
                errors.append(e)
            finally:
                kk.close()

        threads = [threading.Thread(target=appender, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        k.close()
        assert not errors, f"concurrent appends raised (position collision?): {errors[:3]}"

        k2 = Kaos(db_path=db)
        positions = [r[0] for r in k2.conn.execute(
            "SELECT position FROM shared_log ORDER BY position"
        ).fetchall()]
        k2.close()
        assert len(positions) == n_threads * per
        assert len(positions) == len(set(positions)), "duplicate positions"


# ── v0.10 storage-scale: Kaos durability/throughput pragmas configurable ──


class TestConfigurablePragmas:
    def test_synchronous_and_autocheckpoint_apply(self, tmp_path):
        k = Kaos(db_path=str(tmp_path / "k.db"),
                 synchronous="NORMAL", wal_autocheckpoint=1000)
        sync = k.conn.execute("PRAGMA synchronous").fetchone()[0]
        wal = k.conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
        assert sync == 1  # NORMAL==1, FULL==2
        assert wal == 1000
        k.close()

    def test_defaults_preserve_full_100(self, tmp_path):
        k = Kaos(db_path=str(tmp_path / "k.db"))
        assert k.conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
        assert k.conn.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 100
        k.close()

    def test_writes_work_under_normal(self, tmp_path):
        k = Kaos(db_path=str(tmp_path / "k.db"), synchronous="NORMAL")
        a = k.spawn("agent")
        k.write(a, "/f.txt", b"data")
        assert k.read(a, "/f.txt") == b"data"
        k.close()
