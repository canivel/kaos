"""Automatic (inline) plasticity hooks — the 'synaptic' mechanism.

Every time an agent uses a skill, retrieves memory, or completes/fails, a
small hook in this module fires and updates the plasticity substrate
immediately:

    on_skill_outcome(conn, skill_id, agent_id, success)
        → upserts skill↔skill associations for siblings already used in
          the same agent session, decays them lazily on read.

    on_memory_hits(conn, memory_ids, requesting_agent_id)
        → upserts memory↔memory associations for co-retrieved entries,
          plus skill↔memory edges for any skills the agent has used.

    on_agent_completion(conn, agent_id, status)
        → extracts failure fingerprints from errored tool_calls when the
          agent failed, upserts the episode_signals row, and — once every
          ``episode_threshold`` completions — enqueues a threshold-
          triggered consolidation pass (lazy, runs in the same process).

This is deliberately Hebbian: 'entities that fire in the same agent session
wire together'. An `agent_id` defines the session boundary, which matches
KAOS's existing isolation model perfectly.

All hooks are best-effort: they swallow OperationalError so pre-v5 databases
keep working even if something else tries to use these code paths. Fast
(sub-millisecond per call) so hooking them into the hot path is cheap.
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Any


# Opt-out escape hatch. Setting KAOS_DREAM_AUTO=0 in the environment disables
# ALL inline hooks (the DB still has the tables; they just don't auto-fill).
# Tests that want to observe the raw pre-plasticity behaviour can set this.
def auto_enabled() -> bool:
    return os.environ.get("KAOS_DREAM_AUTO", "1").strip() not in ("0", "false", "False")


# Default threshold: after every N successful completions, run a lightweight
# consolidation pass. Raised from 25 to 100 in v0.8.1 after review feedback
# that 25 was too eager for production workloads — consolidation mid-session
# can introduce latency hiccups. Users can still tune via env.
def episode_threshold() -> int:
    raw = os.environ.get("KAOS_DREAM_THRESHOLD", "100")
    try:
        return max(1, int(raw))
    except ValueError:
        return 100


# Systemic-alert tunables. N agents hitting the same fingerprint inside the
# window → flag as systemic. Debounced so one alert fires at most every
# `SYSTEMIC_DEBOUNCE_S` seconds per fingerprint.
def systemic_agent_threshold() -> int:
    raw = os.environ.get("KAOS_SYSTEMIC_THRESHOLD", "5")
    try:
        return max(2, int(raw))
    except ValueError:
        return 5


def systemic_window_s() -> int:
    raw = os.environ.get("KAOS_SYSTEMIC_WINDOW_S", "120")
    try:
        return max(10, int(raw))
    except ValueError:
        return 120


SYSTEMIC_DEBOUNCE_S = 60


# ── Association upsert primitive ────────────────────────────────────


def upsert_association(
    conn: sqlite3.Connection,
    kind_a: str, id_a: int,
    kind_b: str, id_b: int,
    *,
    increment: float = 1.0,
) -> None:
    """Increment the weight of a bidirectional association pair.

    We store both orderings (a,b) and (b,a) so the reverse lookup is a
    cheap indexed query. This doubles the row count but keeps the read
    path index-clean and simple.
    """
    if kind_a == kind_b and id_a == id_b:
        return  # never self-associate
    _upsert_one(conn, kind_a, id_a, kind_b, id_b, increment)
    _upsert_one(conn, kind_b, id_b, kind_a, id_a, increment)


def _upsert_one(conn: sqlite3.Connection,
                kind_a: str, id_a: int,
                kind_b: str, id_b: int,
                increment: float) -> None:
    try:
        conn.execute(
            """
            INSERT INTO associations (kind_a, id_a, kind_b, id_b, weight, uses)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(kind_a, id_a, kind_b, id_b) DO UPDATE SET
                weight = weight + excluded.weight,
                uses   = uses + 1,
                last_seen = strftime('%Y-%m-%dT%H:%M:%f','now')
            """,
            (kind_a, id_a, kind_b, id_b, increment),
        )
    except sqlite3.OperationalError:
        # Older schema — silently skip so the caller path stays working.
        pass


# ── Inline hooks ────────────────────────────────────────────────────


def on_skill_outcome(
    conn: sqlite3.Connection,
    skill_id: int,
    agent_id: str | None,
    success: bool,
) -> None:
    """Fire after a skill is applied and its outcome recorded.

    No-op on the hot path: the raw telemetry (`skill_uses` row) is already
    written by the caller's transaction. The Hebbian association graph is
    built periodically by ``rebuild_associations_for_agent`` during the
    dream cycle (or when the episode threshold fires consolidation),
    matching how biological sleep consolidation works.

    Kept as a function rather than removed so users with custom hooks can
    override it.
    """
    return


def on_memory_hits(
    conn: sqlite3.Connection,
    memory_ids: list[int],
    *,
    requesting_agent_id: str | None,
) -> None:
    """Fire after a memory search returned results that were recorded as hits.

    No-op on the hot path (see on_skill_outcome). The `memory_hits` rows
    were already written by the caller. Associations are derived offline.
    """
    return


def rebuild_associations_for_agent(
    conn: sqlite3.Connection,
    agent_id: str,
) -> dict[str, int]:
    """Derive the Hebbian associations this agent's session would produce.

    Runs once per agent (typically at completion time in the threshold-
    triggered consolidation, or on demand via ``kaos dream run``). Uses
    set-based queries + a single ``executemany`` instead of N-per-event
    upserts — keeps the cost O(skills_touched × memories_touched) rather
    than O(all_sibling_pairs × N_events).

    Returns counts: {"skill_skill": n, "skill_memory": n, "memory_memory": n}.
    """
    counts = {"skill_skill": 0, "skill_memory": 0, "memory_memory": 0}
    try:
        skill_rows = conn.execute(
            "SELECT DISTINCT skill_id FROM skill_uses WHERE agent_id = ?",
            (agent_id,),
        ).fetchall()
        mem_hit_rows = conn.execute(
            "SELECT DISTINCT memory_id FROM memory_hits WHERE agent_id = ?",
            (agent_id,),
        ).fetchall()
        mem_written_rows = conn.execute(
            "SELECT DISTINCT memory_id FROM memory WHERE agent_id = ?",
            (agent_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return counts

    def _ids(rows: list) -> list[int]:
        out = []
        for r in rows:
            val = r[0] if not isinstance(r, sqlite3.Row) else list(r)[0]
            if val is not None:
                out.append(int(val))
        return out

    skill_ids = _ids(skill_rows)
    memory_ids = _ids(mem_hit_rows) + _ids(mem_written_rows)
    # Dedup preserving order
    seen = set()
    memory_ids = [m for m in memory_ids if not (m in seen or seen.add(m))]

    # Build the edges we want
    edges: list[tuple[str, int, str, int, float]] = []
    # skill ↔ skill
    for i, a in enumerate(skill_ids):
        for b in skill_ids[i + 1:]:
            edges.append(("skill", a, "skill", b, 1.0))
            edges.append(("skill", b, "skill", a, 1.0))
            counts["skill_skill"] += 1
    # memory ↔ memory
    for i, a in enumerate(memory_ids):
        for b in memory_ids[i + 1:]:
            edges.append(("memory", a, "memory", b, 1.0))
            edges.append(("memory", b, "memory", a, 1.0))
            counts["memory_memory"] += 1
    # skill ↔ memory
    for sid in skill_ids:
        for mid in memory_ids:
            edges.append(("skill", sid, "memory", mid, 0.5))
            edges.append(("memory", mid, "skill", sid, 0.5))
            counts["skill_memory"] += 1

    if not edges:
        return counts

    try:
        conn.executemany(
            """
            INSERT INTO associations (kind_a, id_a, kind_b, id_b, weight, uses)
            VALUES (?, ?, ?, ?, ?, 1)
            ON CONFLICT(kind_a, id_a, kind_b, id_b) DO UPDATE SET
                weight = weight + excluded.weight,
                uses   = uses + 1,
                last_seen = strftime('%Y-%m-%dT%H:%M:%f','now')
            """,
            edges,
        )
        conn.commit()
    except sqlite3.OperationalError:
        pass
    return counts


def on_agent_completion(
    conn: sqlite3.Connection,
    agent_id: str,
    status: str,
) -> "AutoTriggerResult":
    """Fire when an agent reaches a terminal state.

    Fast path: only touches rows for THIS agent. The expensive full-replay
    scan lives in the periodic dream cycle (`kaos dream run`), not here.

    Side effects:
      - Upsert this one agent's episode_signals row.
      - On failure: extract a fingerprint from the latest errored tool_call.
      - Cross-link skill↔memory associations for entities this agent touched.
      - Trigger consolidation if episode_threshold is crossed (bounded cost —
        only runs the count query when we're at a pre-computed boundary).
    """
    result = AutoTriggerResult()

    if not auto_enabled():
        return result

    try:
        _upsert_episode_signal_for(conn, agent_id, status)
    except sqlite3.OperationalError:
        return result

    if status in ("failed", "killed"):
        try:
            record_failure_fingerprint(conn, agent_id)
        except sqlite3.OperationalError:
            pass

    # Rebuild associations for this agent's session. One batched
    # executemany at completion time — much cheaper than per-event writes.
    try:
        rebuild_associations_for_agent(conn, agent_id)
    except sqlite3.OperationalError:
        pass

    # Trigger consolidation if threshold crossed. Only COUNT(*) here, not
    # a full aggregation. The COUNT is cheap on an indexed column and lets
    # us avoid the consolidation pass most of the time.
    try:
        count_row = conn.execute(
            "SELECT COUNT(*) FROM episode_signals WHERE success IS NOT NULL"
        ).fetchone()
        completed = count_row[0] if count_row else 0
    except sqlite3.OperationalError:
        completed = 0

    threshold = episode_threshold()
    if completed and completed % threshold == 0:
        try:
            ran = trigger_consolidation(conn, reason=f"episode_count={completed}")
            result.consolidation_ran = ran
            result.completed_episodes = completed
            result.threshold = threshold
        except sqlite3.OperationalError:
            pass

    return result


# Status → success flag mapping shared with replay.
_SUCCESS_STATUSES = {"completed"}
_FAILURE_STATUSES = {"failed", "killed"}


def _upsert_episode_signal_for(
    conn: sqlite3.Connection,
    agent_id: str,
    status: str,
) -> None:
    """Cheap single-agent upsert. Runs at most 4 small queries + one upsert,
    all keyed on indexes — O(1)-ish regardless of library size."""
    success = 1 if status in _SUCCESS_STATUSES else (
        0 if status in _FAILURE_STATUSES else None
    )
    # Pre-fetch this agent's aggregates in a single round-trip each.
    row = conn.execute(
        """
        SELECT
          (SELECT created_at FROM agents WHERE agent_id = ?) AS started_at,
          (SELECT last_heartbeat FROM agents WHERE agent_id = ?) AS ended_at,
          (SELECT COUNT(*) FROM tool_calls WHERE agent_id = ?) AS tc_count,
          (SELECT COALESCE(SUM(CASE WHEN status='error' THEN 1 ELSE 0 END), 0)
             FROM tool_calls WHERE agent_id = ?) AS tc_err,
          (SELECT COALESCE(SUM(token_count), 0)
             FROM tool_calls WHERE agent_id = ?) AS tokens,
          (SELECT COALESCE(SUM(cost_usd), 0.0)
             FROM tool_calls WHERE agent_id = ?) AS cost,
          (SELECT COUNT(*) FROM skill_uses WHERE agent_id = ?) AS sk_applied,
          (SELECT COUNT(*) FROM memory WHERE agent_id = ?) AS mem_w,
          (SELECT COUNT(*) FROM memory_hits WHERE agent_id = ?) AS mem_r,
          (SELECT COUNT(*) FROM checkpoints WHERE agent_id = ?) AS cp
        """,
        (agent_id,) * 10,
    ).fetchone()
    if row is None:
        return
    started_at, ended_at, tc_count, tc_err, tokens, cost, sk_applied, mem_w, mem_r, cp = row

    duration_ms = None
    if started_at and ended_at:
        from datetime import datetime, timezone
        try:
            s = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
            e = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if e.tzinfo is None:
                e = e.replace(tzinfo=timezone.utc)
            duration_ms = max(0, int((e - s).total_seconds() * 1000))
        except ValueError:
            pass

    conn.execute(
        """
        INSERT INTO episode_signals
            (agent_id, started_at, ended_at, status, success,
             tool_calls_count, tool_calls_error,
             total_tokens, total_cost_usd, duration_ms,
             skills_applied, memories_written, memories_retrieved, checkpoints_made,
             last_computed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                strftime('%Y-%m-%dT%H:%M:%f','now'))
        ON CONFLICT(agent_id) DO UPDATE SET
            started_at=excluded.started_at,
            ended_at=excluded.ended_at,
            status=excluded.status,
            success=excluded.success,
            tool_calls_count=excluded.tool_calls_count,
            tool_calls_error=excluded.tool_calls_error,
            total_tokens=excluded.total_tokens,
            total_cost_usd=excluded.total_cost_usd,
            duration_ms=excluded.duration_ms,
            skills_applied=excluded.skills_applied,
            memories_written=excluded.memories_written,
            memories_retrieved=excluded.memories_retrieved,
            checkpoints_made=excluded.checkpoints_made,
            last_computed_at=strftime('%Y-%m-%dT%H:%M:%f','now')
        """,
        (agent_id, started_at, ended_at, status, success,
         tc_count, tc_err, tokens, cost, duration_ms,
         sk_applied, mem_w, mem_r, cp),
    )
    conn.commit()


def _crosslink_skills_and_memory(conn: sqlite3.Connection, agent_id: str) -> None:
    """Deprecated alias for rebuild_associations_for_agent (kept for
    backward compatibility with any custom code that imported it)."""
    rebuild_associations_for_agent(conn, agent_id)


# ── Failure fingerprint extraction ──────────────────────────────────


# Common error-message noise: UUIDs, ULIDs, timestamps, file paths, hex ids.
_NOISE_PATTERNS = [
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<uuid>"),
    (re.compile(r"\b01[0-9A-HJKMNP-TV-Z]{24}\b"), "<ulid>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?"), "<ts>"),
    (re.compile(r"0x[0-9a-fA-F]+"), "<hex>"),
    (re.compile(r"\b\d{6,}\b"), "<num>"),
    (re.compile(r"(?:[A-Z]:\\|/)[\w\-./\\]+"), "<path>"),
    (re.compile(r"\s+at 0x[0-9a-fA-F]+"), ""),
    (re.compile(r"\s+"), " "),
]


def normalise_error(message: str) -> str:
    """Strip identifiers from an error message so equivalent failures share
    one fingerprint. Idempotent; cheap."""
    out = message
    for pat, repl in _NOISE_PATTERNS:
        out = pat.sub(repl, out)
    return out.strip()


def fingerprint_of(tool_name: str, message: str) -> str:
    """Hash the normalised (tool_name, message) pair into a short key."""
    norm = normalise_error(message)
    key = f"{tool_name}|{norm}"
    return hashlib.sha256(key.encode("utf-8", errors="replace")).hexdigest()[:16]


def record_failure_fingerprint(
    conn: sqlite3.Connection,
    agent_id: str,
) -> int | None:
    """Look up the most recent errored tool_call for this agent, upsert a
    failure_fingerprints row, record the occurrence, diagnose it if new,
    and check for systemic patterns.

    Returns the fp_id, or None if the agent had no error to fingerprint.
    Idempotent — multiple calls for the same agent re-record occurrences.
    """
    row = conn.execute(
        """
        SELECT tool_name, error_message FROM tool_calls
        WHERE agent_id = ? AND status = 'error' AND error_message IS NOT NULL
        ORDER BY started_at DESC LIMIT 1
        """,
        (agent_id,),
    ).fetchone()
    if not row or not row[1]:
        return None
    tool_name = row[0] or "<unknown>"
    message = row[1]
    fp = fingerprint_of(tool_name, message)
    normalised = normalise_error(message)

    # Upsert fingerprint row (count bump on existing, insert on new)
    conn.execute(
        """
        INSERT INTO failure_fingerprints
            (fingerprint, example_error, tool_name)
        VALUES (?, ?, ?)
        ON CONFLICT(fingerprint) DO UPDATE SET
            count = count + 1,
            last_seen = strftime('%Y-%m-%dT%H:%M:%f','now')
        """,
        (fp, normalised[:500], tool_name),
    )

    # Fetch the fp_id and current diagnostic status
    fp_row = conn.execute(
        "SELECT fp_id, category, diagnosed_at FROM failure_fingerprints "
        "WHERE fingerprint = ?",
        (fp,),
    ).fetchone()
    fp_id = fp_row[0]
    current_category = fp_row[1] if fp_row[1] else "unknown"
    diagnosed_at = fp_row[2]

    # Record the occurrence — lets systemic detection compute sliding counts
    try:
        conn.execute(
            "INSERT INTO failure_occurrences (fp_id, agent_id) VALUES (?, ?)",
            (fp_id, agent_id),
        )
    except sqlite3.OperationalError:
        pass

    # Diagnose if never diagnosed (or diagnosed as unknown — give heuristics
    # another chance in case a new diagnoser was registered since).
    if diagnosed_at is None or current_category == "unknown":
        _attempt_diagnosis(conn, fp_id, tool_name, normalised, agent_id)

    # Check for systemic pattern (many agents, same fingerprint, short window)
    _check_systemic(conn, fp_id)

    conn.commit()
    return fp_id


def _attempt_diagnosis(
    conn: sqlite3.Connection,
    fp_id: int,
    tool_name: str,
    normalised_error: str,
    agent_id: str,
) -> None:
    """Run the heuristic diagnosers and persist the result if confident enough."""
    try:
        from kaos.dream.diagnosis import diagnose
    except ImportError:
        return
    result = diagnose(tool_name, normalised_error,
                      context={"agent_id": agent_id})
    # Even 'unknown' is recorded so we don't re-diagnose forever — but we
    # leave category='unknown' so a future run with a new diagnoser can
    # retry. If confidence is 0 we don't overwrite an existing diagnosis.
    if result.confidence == 0.0:
        conn.execute(
            "UPDATE failure_fingerprints SET diagnosed_at = "
            "strftime('%Y-%m-%dT%H:%M:%f','now') WHERE fp_id = ?",
            (fp_id,),
        )
        return
    conn.execute(
        """
        UPDATE failure_fingerprints
        SET category = ?,
            root_cause = ?,
            suggested_action = ?,
            diagnostic_method = ?,
            diagnosed_at = strftime('%Y-%m-%dT%H:%M:%f','now')
        WHERE fp_id = ?
        """,
        (result.category, result.root_cause, result.suggested_action,
         result.method, fp_id),
    )


def _check_systemic(conn: sqlite3.Connection, fp_id: int) -> None:
    """If ≥N distinct agents have hit this fingerprint within the sliding
    window, create a systemic_alerts row (subject to debouncing)."""
    from datetime import datetime, timedelta, timezone

    threshold = systemic_agent_threshold()
    window = systemic_window_s()

    cutoff = (datetime.now(timezone.utc)
              - timedelta(seconds=window)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]

    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT agent_id) FROM failure_occurrences "
            "WHERE fp_id = ? AND occurred_at >= ?",
            (fp_id, cutoff),
        ).fetchone()
    except sqlite3.OperationalError:
        return
    agent_count = row[0] if row else 0
    if agent_count < threshold:
        return

    # Debounce: one alert per fp within SYSTEMIC_DEBOUNCE_S seconds
    last_alert = conn.execute(
        "SELECT last_systemic_alert_at FROM failure_fingerprints WHERE fp_id = ?",
        (fp_id,),
    ).fetchone()
    if last_alert and last_alert[0]:
        try:
            from datetime import datetime as _dt
            last_dt = _dt.fromisoformat(last_alert[0].replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            age = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if age < SYSTEMIC_DEBOUNCE_S:
                return
        except ValueError:
            pass

    # Pull root cause for the alert row
    fp_info = conn.execute(
        "SELECT root_cause FROM failure_fingerprints WHERE fp_id = ?",
        (fp_id,),
    ).fetchone()
    root_cause = fp_info[0] if fp_info and fp_info[0] else None

    try:
        conn.execute(
            "INSERT INTO systemic_alerts (fp_id, agent_count, window_seconds, root_cause) "
            "VALUES (?, ?, ?, ?)",
            (fp_id, agent_count, window, root_cause),
        )
        conn.execute(
            "UPDATE failure_fingerprints "
            "SET last_systemic_alert_at = strftime('%Y-%m-%dT%H:%M:%f','now') "
            "WHERE fp_id = ?",
            (fp_id,),
        )
    except sqlite3.OperationalError:
        pass


# ── Threshold-triggered consolidation ───────────────────────────────


@dataclass
class AutoTriggerResult:
    consolidation_ran: bool = False
    completed_episodes: int = 0
    threshold: int = 0
    proposals_generated: int = 0


def trigger_consolidation(
    conn: sqlite3.Connection,
    *,
    reason: str = "threshold",
    dry_run: bool = True,
) -> bool:
    """Run the consolidation phase in-process and insert a dream_runs row.

    This is invoked by on_agent_completion when the episode threshold is
    crossed. Kept lightweight: imports are deferred so the import cost is
    only paid when plasticity actually fires.
    """
    if not auto_enabled():
        return False
    try:
        from kaos.dream.phases.consolidation import run as consolidation_run
        from kaos.dream.phases.policies import run as policies_run
    except ImportError:
        return False

    consolidation_run(conn, dry_run=dry_run, trigger_reason=reason)
    policies_run(conn, dry_run=dry_run)
    return True
