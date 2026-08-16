"""Local bench.db schema — the workspace brain's storage (MVP loop, schema v1).

One bench = one SQLite file beside kaos.db. This is the LOCAL subset of the
Attraktor DDL (the attraktor repo's ``schema/bench.sql`` is the interop-
normative shared-bench superset; table/column names here must stay aligned with
it). Shared-bench-only tables (signers, attestations, sync cursors) are not
created locally until a remote is added.

Design commitments encoded here:
- eval_records carries ``kind IN ('mechanism_eval','skill','learning')`` (PLAN v2 R1).
- REJECTIONS ARE FIRST-CLASS DATA (D0.1): every harvested candidate keeps its full
  E1/E2 reasoning — gate outcomes, arm numbers, rationale — whether admitted or
  rejected. ``bench_candidates`` is append-forever; a rejection is a validated
  negative result the workspace paid compute for, and the UNIQUE(source_kind,
  source_ref) key doubles as the never-re-harvest-the-same-dud guard.
- Outcome telemetry cannot represent self-report: ``outcome_source`` is CHECKed to
  runner/harness/mechanical only.
- Item state is a monotone lattice (serving → quarantined → evicted); a trigger
  makes regression unrepresentable, mirroring the no-retune ethos in storage.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

BENCH_SCHEMA_VERSION = 2

_DDL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS bench_schema_version (version INTEGER NOT NULL);

CREATE TABLE IF NOT EXISTS bench_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- content-addressed artifact store (lock bytes, results.json, falsification.json)
CREATE TABLE IF NOT EXISTS artifacts (
    artifact_sha256 TEXT PRIMARY KEY,
    media_type      TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL,
    content         BLOB NOT NULL,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE IF NOT EXISTS mechanisms (
    mechanism_id  TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    family        TEXT,
    arxiv_id      TEXT, doi TEXT, source_url TEXT, source_title TEXT,
    authors_json  TEXT NOT NULL DEFAULT '[]',
    first_seen_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

-- THE table: one immutable row per ADMITTED item (any kind).
CREATE TABLE IF NOT EXISTS eval_records (
    record_cid       TEXT PRIMARY KEY,
    schema_id        TEXT NOT NULL,
    kind             TEXT NOT NULL CHECK (kind IN ('mechanism_eval','skill','learning')),
    mechanism_id     TEXT REFERENCES mechanisms(mechanism_id),
    lock_sha256      TEXT,
    lock_artifact_sha256 TEXT REFERENCES artifacts(artifact_sha256),
    self_test_passed INTEGER NOT NULL CHECK (self_test_passed IN (0,1)),
    verdict          TEXT NOT NULL CHECK (verdict IN ('ACCEPT','REJECT','VOID')),
    verdict_detail   TEXT,
    disposition      TEXT NOT NULL DEFAULT 'AS_VERDICT'
                     CHECK (disposition IN ('AS_VERDICT','DO_NOT_SHIP','PARKED','RETRACTED')),
    judge_kappa      REAL,
    variant          TEXT NOT NULL,
    faithful         INTEGER NOT NULL CHECK (faithful IN (0,1)),
    trust_level      INTEGER NOT NULL DEFAULT 0 CHECK (trust_level BETWEEN 0 AND 3),
    repro_class      TEXT NOT NULL CHECK (repro_class IN
                     ('deterministic_seeded','llm_nondeterministic','organic_private')),
    envelope_json    TEXT NOT NULL DEFAULT '{}',   -- transfer envelope: consumed/measured axes
    results_sha256   TEXT REFERENCES artifacts(artifact_sha256),
    supersedes_cid   TEXT REFERENCES eval_records(record_cid),
    status           TEXT NOT NULL DEFAULT 'active'
                     CHECK (status IN ('active','superseded','retracted')),
    body_json        TEXT NOT NULL,                -- authoritative canonical bytes
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    origin_bench_id  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_records_kind ON eval_records(kind, status);
CREATE INDEX IF NOT EXISTS idx_records_verdict ON eval_records(verdict, status);

CREATE TABLE IF NOT EXISTS record_gates (
    record_cid TEXT NOT NULL REFERENCES eval_records(record_cid),
    gate_id    TEXT NOT NULL,
    gate_name  TEXT NOT NULL,
    kill       INTEGER NOT NULL CHECK (kill IN (0,1)),
    passed     INTEGER,
    detail     TEXT,
    PRIMARY KEY (record_cid, gate_id)
);

CREATE TRIGGER IF NOT EXISTS eval_records_immutable
BEFORE UPDATE OF body_json, verdict, record_cid, kind ON eval_records
BEGIN SELECT RAISE(ABORT, 'eval_records are immutable'); END;
CREATE TRIGGER IF NOT EXISTS eval_records_no_delete
BEFORE DELETE ON eval_records
BEGIN SELECT RAISE(ABORT, 'eval_records are append-only'); END;

-- ── The loop: harvest → validate → (admit | REJECT-with-reasoning) ──
-- Append-forever. A rejection row IS the dataset entry (D0.1): e1_json/e2_json
-- hold the full gate outcomes + arm numbers; rejection_reason the human-readable
-- why. UNIQUE(source_kind, source_ref) = idempotent harvest + never re-try a dud.
CREATE TABLE IF NOT EXISTS bench_candidates (
    candidate_id  TEXT PRIMARY KEY,
    source_kind   TEXT NOT NULL CHECK (source_kind IN
                  ('skill_telemetry','dream_promotion','experiment')),
    source_ref    TEXT NOT NULL,
    kind          TEXT NOT NULL CHECK (kind IN ('mechanism_eval','skill','learning')),
    payload_json  TEXT NOT NULL DEFAULT '{}',      -- the harvested content
    status        TEXT NOT NULL DEFAULT 'harvested' CHECK (status IN
                  ('harvested','e1_rejected','e1_passed','e2_rejected','admitted','error')),
    e1_json       TEXT,                            -- six-condition outcomes + numbers
    e2_json       TEXT,                            -- arms (WITH/WITHOUT/SCRAMBLED), gates, verdict
    rejection_reason TEXT,                         -- REQUIRED when rejected (trigger below)
    record_cid    TEXT REFERENCES eval_records(record_cid),  -- set iff admitted
    harvested_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    decided_at    TEXT,
    UNIQUE (source_kind, source_ref)
);
CREATE INDEX IF NOT EXISTS idx_candidates_status ON bench_candidates(status);

-- D0.1 enforcement: a rejection without reasoning is unrepresentable.
CREATE TRIGGER IF NOT EXISTS candidates_reject_needs_reason
BEFORE UPDATE OF status ON bench_candidates
WHEN NEW.status IN ('e1_rejected','e2_rejected','error')
     AND (NEW.rejection_reason IS NULL OR NEW.rejection_reason = '')
BEGIN SELECT RAISE(ABORT, 'rejection requires rejection_reason (D0.1: rejections are data)'); END;
CREATE TRIGGER IF NOT EXISTS candidates_no_delete
BEFORE DELETE ON bench_candidates
BEGIN SELECT RAISE(ABORT, 'bench_candidates are append-forever (rejections are data)'); END;

-- ── Feed-back close: per-pull outcome telemetry ──
-- outcome_source CHECK makes agent self-report UNREPRESENTABLE: outcomes come from
-- the runner, an eval harness, or a mechanical check — never the agent's own claim.
CREATE TABLE IF NOT EXISTS outcome_telemetry (
    telemetry_id  TEXT PRIMARY KEY,
    record_cid    TEXT NOT NULL REFERENCES eval_records(record_cid),
    agent_id      TEXT NOT NULL,
    task_hash     TEXT,
    invoked       INTEGER NOT NULL CHECK (invoked IN (0,1)),
    outcome       INTEGER CHECK (outcome IN (0,1)),          -- NULL = not yet known
    outcome_source TEXT NOT NULL CHECK (outcome_source IN ('runner','harness','mechanical')),
    fidelity      REAL CHECK (fidelity IS NULL OR (fidelity >= 0 AND fidelity <= 1)),
    shadow        INTEGER NOT NULL DEFAULT 0 CHECK (shadow IN (0,1)),
    pull_id       TEXT,                                       -- v2: episode link
    arm           TEXT,                                       -- v2: on|off|scrambled
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_telemetry_record ON outcome_telemetry(record_cid, created_at);

-- ── Monotone item-state lattice: serving → quarantined → evicted ──
CREATE TABLE IF NOT EXISTS bench_item_state (
    record_cid  TEXT PRIMARY KEY REFERENCES eval_records(record_cid),
    state       TEXT NOT NULL CHECK (state IN ('serving','quarantined','evicted')),
    reason_json TEXT NOT NULL DEFAULT '{}',
    changed_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TRIGGER IF NOT EXISTS item_state_monotone
BEFORE UPDATE OF state ON bench_item_state
WHEN (CASE NEW.state WHEN 'serving' THEN 0 WHEN 'quarantined' THEN 1 ELSE 2 END)
   < (CASE OLD.state WHEN 'serving' THEN 0 WHEN 'quarantined' THEN 1 ELSE 2 END)
BEGIN SELECT RAISE(ABORT, 'item state is monotone: serving -> quarantined -> evicted'); END;

-- ── Pull ledger: EVERY pull decision is data, including what was NOT served ──
-- A WITHHOLD ("consumed axis M1 absent") is validated reasoning the workspace
-- computed; an empty pull is a success state and gets its row. D0.1 extended to
-- the pull side.
CREATE TABLE IF NOT EXISTS bench_pulls (
    pull_id          TEXT PRIMARY KEY,
    agent_id         TEXT NOT NULL,
    task_hash        TEXT,
    fingerprint_json TEXT NOT NULL DEFAULT '{}',
    k                INTEGER NOT NULL,
    latency_ms       REAL,                                    -- v2: G2 evidence
    arm              TEXT,                                    -- v2: on|off|scrambled (hook pulls)
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TABLE IF NOT EXISTS bench_pull_decisions (
    pull_id     TEXT NOT NULL REFERENCES bench_pulls(pull_id),
    record_cid  TEXT NOT NULL REFERENCES eval_records(record_cid),
    decision    TEXT NOT NULL CHECK (decision IN ('served','shadow','withheld','outranked')),
    reason      TEXT,                                -- REQUIRED for 'withheld' (trigger)
    axis        TEXT,                                -- withholding axis, if any
    weight      REAL,
    fidelity    TEXT CHECK (fidelity IN (NULL,'full','partial')),
    rank_score  REAL,
    PRIMARY KEY (pull_id, record_cid)
);
CREATE TRIGGER IF NOT EXISTS pull_withhold_needs_reason
BEFORE INSERT ON bench_pull_decisions
WHEN NEW.decision = 'withheld' AND (NEW.reason IS NULL OR NEW.reason = '')
BEGIN SELECT RAISE(ABORT, 'withhold requires a reason (D0.1: decisions are data)'); END;
CREATE TRIGGER IF NOT EXISTS pull_decisions_no_delete
BEFORE DELETE ON bench_pull_decisions
BEGIN SELECT RAISE(ABORT, 'pull decisions are append-forever'); END;

-- ── Automatic history: state transitions + candidate decisions journal ──
-- Append-only event log, WRITTEN BY TRIGGERS — no code path can forget to
-- record history, and old reasoning survives every later transition.
CREATE TABLE IF NOT EXISTS bench_events (
    event_seq   INTEGER PRIMARY KEY AUTOINCREMENT,
    entity      TEXT NOT NULL CHECK (entity IN ('candidate','item_state')),
    entity_id   TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE TRIGGER IF NOT EXISTS bench_events_no_delete
BEFORE DELETE ON bench_events
BEGIN SELECT RAISE(ABORT, 'bench_events are append-only'); END;
CREATE TRIGGER IF NOT EXISTS bench_events_no_update
BEFORE UPDATE ON bench_events
BEGIN SELECT RAISE(ABORT, 'bench_events are immutable'); END;

CREATE TRIGGER IF NOT EXISTS journal_item_state_change
AFTER UPDATE OF state ON bench_item_state
BEGIN
    INSERT INTO bench_events (entity, entity_id, event_type, payload_json)
    VALUES ('item_state', NEW.record_cid,
            'transition:' || OLD.state || '->' || NEW.state,
            json_object('old_reason', OLD.reason_json, 'new_reason', NEW.reason_json));
END;
CREATE TRIGGER IF NOT EXISTS journal_item_state_insert
AFTER INSERT ON bench_item_state
BEGIN
    INSERT INTO bench_events (entity, entity_id, event_type, payload_json)
    VALUES ('item_state', NEW.record_cid, 'enter:' || NEW.state, NEW.reason_json);
END;
CREATE TRIGGER IF NOT EXISTS journal_candidate_decision
AFTER UPDATE OF status ON bench_candidates
BEGIN
    INSERT INTO bench_events (entity, entity_id, event_type, payload_json)
    VALUES ('candidate', NEW.candidate_id, 'status:' || OLD.status || '->' || NEW.status,
            json_object('rejection_reason', NEW.rejection_reason));
END;

-- FTS5 recall index over admitted records (the SkillStore.search pattern) —
-- BM25 lexical recall only, no embeddings, ever.
CREATE VIRTUAL TABLE IF NOT EXISTS bench_fts USING fts5(
    record_cid UNINDEXED, name, family, variant, keys_text
);

-- push queue for later shared-bench phases; zero rows = pure local bench
CREATE TABLE IF NOT EXISTS bench_outbox (
    record_cid TEXT NOT NULL REFERENCES eval_records(record_cid),
    remote     TEXT NOT NULL,
    state      TEXT NOT NULL DEFAULT 'queued'
               CHECK (state IN ('queued','sent','accepted','rejected')),
    last_error TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    PRIMARY KEY (record_cid, remote)
);
"""


def _migrate(conn: sqlite3.Connection, from_version: int) -> None:
    """Additive-only migrations (the bench never rewrites history)."""
    if from_version < 2:
        # v2: probe evidence columns — pull latency (G2), episode arm
        # assignment (G1/G4), and the outcome→pull episode link.
        have = {r[1] for r in conn.execute("PRAGMA table_info(bench_pulls)")}
        if "latency_ms" not in have:
            conn.execute("ALTER TABLE bench_pulls ADD COLUMN latency_ms REAL")
        if "arm" not in have:
            conn.execute("ALTER TABLE bench_pulls ADD COLUMN arm TEXT")
        have = {r[1] for r in conn.execute("PRAGMA table_info(outcome_telemetry)")}
        if "pull_id" not in have:
            conn.execute("ALTER TABLE outcome_telemetry ADD COLUMN pull_id TEXT")
        if "arm" not in have:
            conn.execute("ALTER TABLE outcome_telemetry ADD COLUMN arm TEXT")
    conn.execute("UPDATE bench_schema_version SET version = ?", (BENCH_SCHEMA_VERSION,))


def init_bench_db(conn: sqlite3.Connection, *, bench_tier: str = "personal") -> None:
    """Create (or no-op on) the bench schema; stamps bench_id/tier on first init."""
    conn.executescript(_DDL)
    if conn.execute("SELECT COUNT(*) FROM bench_schema_version").fetchone()[0] == 0:
        conn.execute("INSERT INTO bench_schema_version VALUES (?)", (BENCH_SCHEMA_VERSION,))
    else:
        v = conn.execute("SELECT version FROM bench_schema_version").fetchone()[0]
        if v < BENCH_SCHEMA_VERSION:
            _migrate(conn, v)
    if conn.execute("SELECT COUNT(*) FROM bench_meta WHERE key='bench_id'").fetchone()[0] == 0:
        conn.execute("INSERT INTO bench_meta VALUES ('bench_id', ?)", (str(uuid.uuid4()),))
        conn.execute("INSERT INTO bench_meta VALUES ('bench_tier', ?)", (bench_tier,))
    conn.commit()


def open_bench(path: str | Path, *, bench_tier: str = "personal") -> sqlite3.Connection:
    """Open (creating if needed) the workspace's local bench.db."""
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_bench_db(conn, bench_tier=bench_tier)
    return conn


def bench_id(conn: sqlite3.Connection) -> str:
    return conn.execute(
        "SELECT value FROM bench_meta WHERE key='bench_id'").fetchone()[0]


def fts_index_record(
    conn: sqlite3.Connection, record_cid: str, *, name: str,
    family: str = "", variant: str = "", keys_text: str = "",
) -> None:
    """Add an admitted record to the BM25 recall index (idempotent)."""
    conn.execute("DELETE FROM bench_fts WHERE record_cid = ?", (record_cid,))
    conn.execute(
        "INSERT INTO bench_fts (record_cid, name, family, variant, keys_text) "
        "VALUES (?, ?, ?, ?, ?)",
        (record_cid, name, family, variant, keys_text))
    conn.commit()
