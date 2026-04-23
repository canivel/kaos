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
# consolidation pass. Configurable via env for easier testing.
def episode_threshold() -> int:
    raw = os.environ.get("KAOS_DREAM_THRESHOLD", "25")
    try:
        return max(1, int(raw))
    except ValueError:
        return 25


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

    Associates this skill with every other skill the same agent has used
    in its lifetime. Incrementing on every call means the graph weights
    naturally reflect how often entities co-fire.
    """
    if not auto_enabled() or agent_id is None:
        return
    try:
        siblings = conn.execute(
            "SELECT DISTINCT skill_id FROM skill_uses "
            "WHERE agent_id = ? AND skill_id != ?",
            (agent_id, skill_id),
        ).fetchall()
    except sqlite3.OperationalError:
        return
    increment = 1.0 if success else 0.3
    for row in siblings:
        other = row[0] if not isinstance(row, sqlite3.Row) else row["skill_id"]
        upsert_association(conn, "skill", skill_id, "skill", other,
                           increment=increment)
    conn.commit()


def on_memory_hits(
    conn: sqlite3.Connection,
    memory_ids: list[int],
    *,
    requesting_agent_id: str | None,
) -> None:
    """Fire after a memory search returns results that were recorded as hits.

    Two kinds of edges are created:
      - memory↔memory: the set of results that just co-occurred in one search.
      - skill↔memory: if the requesting agent has already used skills, each
        skill gets an edge to each retrieved memory (cross-modal plasticity).
    """
    if not auto_enabled() or not memory_ids:
        return
    for i, a in enumerate(memory_ids):
        for b in memory_ids[i + 1:]:
            upsert_association(conn, "memory", a, "memory", b)

    if requesting_agent_id is None:
        conn.commit()
        return

    try:
        skill_rows = conn.execute(
            "SELECT DISTINCT skill_id FROM skill_uses WHERE agent_id = ?",
            (requesting_agent_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.commit()
        return

    for srow in skill_rows:
        sid = srow[0] if not isinstance(srow, sqlite3.Row) else srow["skill_id"]
        for mid in memory_ids:
            upsert_association(conn, "skill", sid, "memory", mid,
                               increment=0.5)
    conn.commit()


def on_agent_completion(
    conn: sqlite3.Connection,
    agent_id: str,
    status: str,
) -> "AutoTriggerResult":
    """Fire when an agent reaches a terminal state.

    Side effects:
      - Upsert episode_signals row via the replay helpers.
      - On failure: extract a fingerprint from the latest errored tool_call.
      - Cross-link skill↔memory associations for everything the agent touched.
      - Enqueue a lightweight consolidation pass if the episode_threshold is
        crossed (see trigger_consolidation()).

    Returns an AutoTriggerResult so callers can observe whether consolidation
    ran.
    """
    result = AutoTriggerResult()

    if not auto_enabled():
        return result

    try:
        # Upsert this one agent's episode_signals immediately. Replay would
        # also do this but we want it visible right after completion for
        # subsequent hooks (failure lookup etc).
        from kaos.dream.phases.replay import run as replay_run
        replay_run(conn, since_ts=None, apply=True)
    except sqlite3.OperationalError:
        return result

    if status in ("failed", "killed"):
        try:
            record_failure_fingerprint(conn, agent_id)
        except sqlite3.OperationalError:
            pass

    _crosslink_skills_and_memory(conn, agent_id)

    # Trigger consolidation if threshold crossed
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


def _crosslink_skills_and_memory(conn: sqlite3.Connection, agent_id: str) -> None:
    """At agent completion, pair every skill the agent used with every memory
    it wrote. Lighter than doing it on every individual write."""
    try:
        skills = conn.execute(
            "SELECT DISTINCT skill_id FROM skill_uses WHERE agent_id = ?",
            (agent_id,),
        ).fetchall()
        memories = conn.execute(
            "SELECT DISTINCT memory_id FROM memory WHERE agent_id = ?",
            (agent_id,),
        ).fetchall()
    except sqlite3.OperationalError:
        return
    if not skills or not memories:
        return
    for srow in skills:
        sid = srow[0] if not isinstance(srow, sqlite3.Row) else srow["skill_id"]
        for mrow in memories:
            mid = mrow[0] if not isinstance(mrow, sqlite3.Row) else mrow["memory_id"]
            upsert_association(conn, "skill", sid, "memory", mid,
                               increment=0.5)
    conn.commit()


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
    """Look up the most recent errored tool_call for this agent and upsert
    a failure_fingerprints row. Returns the fp_id or None if nothing to record.
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
    conn.commit()
    return conn.execute(
        "SELECT fp_id FROM failure_fingerprints WHERE fingerprint = ?",
        (fp,),
    ).fetchone()[0]


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
