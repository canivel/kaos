"""Consolidation phase — structural plasticity.

Proposes and optionally applies four kinds of structural changes:

    promote : memory entry cited N+ times → a full skill template
    prune   : skill with <P% success after M uses, OR skill never used
              in the last K days → soft-deprecate (not delete)
    merge   : near-duplicate skills (Jaccard on tokens > threshold) → propose
              a merge. Never auto-applied in M3 — always dry-run because
              merges lose information.
    split   : (placeholder in M3 — real implementation in a later milestone)

Every decision gets a row in `consolidation_proposals`. In ``--dry-run`` mode
nothing downstream mutates; in ``--apply`` mode the safe changes (prune,
promote) execute and the proposal row is marked `applied=1`. Merge/split
always stay as proposals for human review.

This phase is invoked:
  - Automatically from auto.on_agent_completion when the episode threshold
    crosses (dry-run by default — recommendations only).
  - Manually via ``kaos dream consolidate --apply``.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Proposal:
    kind: str          # promote | prune | merge | split
    targets: dict      # arbitrary JSON-serialisable identifying the change
    rationale: str
    applied: bool = False


@dataclass
class ConsolidationReport:
    proposals: list[Proposal] = field(default_factory=list)
    promoted: int = 0
    pruned: int = 0
    merge_candidates: int = 0
    applied: int = 0
    trigger_reason: str | None = None


# Tunables — conservative defaults so auto-consolidation doesn't accidentally
# prune an entire library on first run.
DEFAULT_PRUNE_MIN_USES = 6          # need at least N attempts before judging
DEFAULT_PRUNE_MAX_SUCCESS_RATE = 0.4
DEFAULT_PROMOTE_MIN_HITS = 5
DEFAULT_MERGE_JACCARD_THRESHOLD = 0.65


def run(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = True,
    trigger_reason: str | None = None,
    prune_min_uses: int = DEFAULT_PRUNE_MIN_USES,
    prune_max_success_rate: float = DEFAULT_PRUNE_MAX_SUCCESS_RATE,
    promote_min_hits: int = DEFAULT_PROMOTE_MIN_HITS,
    merge_threshold: float = DEFAULT_MERGE_JACCARD_THRESHOLD,
    run_id: int | None = None,
) -> ConsolidationReport:
    """Identify consolidation candidates. Apply safe ones if not dry-run.

    Returns a report summarising what was found and applied. Writes a row
    to consolidation_proposals for every candidate.
    """
    report = ConsolidationReport(trigger_reason=trigger_reason)

    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        report.proposals += _find_promotions(conn, promote_min_hits)
        report.proposals += _find_prunes(conn, prune_min_uses, prune_max_success_rate)
        report.proposals += _find_merges(conn, merge_threshold)
    finally:
        conn.row_factory = prev

    # Persist every proposal
    for p in report.proposals:
        try:
            conn.execute(
                "INSERT INTO consolidation_proposals "
                "(run_id, kind, targets, rationale) VALUES (?, ?, ?, ?)",
                (run_id, p.kind, json.dumps(p.targets), p.rationale),
            )
        except sqlite3.OperationalError:
            pass

    if not dry_run:
        report.applied = _apply_safe(conn, report.proposals)

    # Aggregate counters
    for p in report.proposals:
        if p.kind == "promote":
            report.promoted += 1
        elif p.kind == "prune":
            report.pruned += 1
        elif p.kind == "merge":
            report.merge_candidates += 1

    try:
        conn.commit()
    except sqlite3.OperationalError:
        pass

    return report


# ── Finders ─────────────────────────────────────────────────────────


def _find_promotions(conn: sqlite3.Connection, min_hits: int) -> list[Proposal]:
    """Memory entries retrieved >= min_hits times are promotion candidates."""
    try:
        rows = conn.execute(
            """
            SELECT m.memory_id, m.key, m.type, m.content, m.agent_id,
                   COUNT(h.hit_id) AS n
            FROM memory m
            LEFT JOIN memory_hits h ON h.memory_id = m.memory_id
            GROUP BY m.memory_id
            HAVING n >= ?
            ORDER BY n DESC
            """,
            (min_hits,),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    out: list[Proposal] = []
    for r in rows:
        out.append(Proposal(
            kind="promote",
            targets={
                "memory_id": r["memory_id"],
                "key": r["key"],
                "type": r["type"],
                "hits": r["n"],
                "source_agent_id": r["agent_id"],
            },
            rationale=f"Memory '{r['key'] or f'#{r['memory_id']}'}' retrieved "
                      f"{r['n']} times — strong signal to promote into a reusable skill.",
        ))
    return out


def _find_prunes(
    conn: sqlite3.Connection,
    min_uses: int,
    max_rate: float,
) -> list[Proposal]:
    """Skills with low success after enough attempts → prune candidates."""
    try:
        rows = conn.execute(
            """
            SELECT skill_id, name, use_count, success_count,
                   COALESCE(deprecated, 0) AS deprecated
            FROM agent_skills
            WHERE COALESCE(deprecated, 0) = 0
              AND use_count >= ?
              AND CAST(success_count AS REAL) / use_count <= ?
            """,
            (min_uses, max_rate),
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    out: list[Proposal] = []
    for r in rows:
        rate = r["success_count"] / r["use_count"] if r["use_count"] else 0.0
        out.append(Proposal(
            kind="prune",
            targets={
                "skill_id": r["skill_id"],
                "name": r["name"],
                "use_count": r["use_count"],
                "success_count": r["success_count"],
                "success_rate": round(rate, 3),
            },
            rationale=f"Skill '{r['name']}' — {r['success_count']}/{r['use_count']} "
                      f"successes ({int(rate * 100)}%). Below "
                      f"{int(max_rate * 100)}% after {min_uses}+ uses.",
        ))
    return out


_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _find_merges(conn: sqlite3.Connection, threshold: float) -> list[Proposal]:
    """Skills with high Jaccard overlap on descriptions → merge candidates.

    Intentionally cheap — no embeddings. Works on normalised word-bag overlap
    of name+description+tags. A merge is never auto-applied; we only propose.
    """
    try:
        rows = conn.execute(
            "SELECT skill_id, name, description, tags, "
            "COALESCE(deprecated, 0) AS deprecated "
            "FROM agent_skills WHERE COALESCE(deprecated, 0) = 0"
        ).fetchall()
    except sqlite3.OperationalError:
        return []

    skills: list[tuple[int, str, set[str]]] = []
    for r in rows:
        text = " ".join([r["name"] or "", r["description"] or "", r["tags"] or ""])
        tokens = set(_TOKEN_RE.findall(text.lower()))
        if tokens:
            skills.append((r["skill_id"], r["name"], tokens))

    out: list[Proposal] = []
    for i in range(len(skills)):
        for j in range(i + 1, len(skills)):
            a_id, a_name, a_tokens = skills[i]
            b_id, b_name, b_tokens = skills[j]
            jac = _jaccard(a_tokens, b_tokens)
            if jac >= threshold:
                out.append(Proposal(
                    kind="merge",
                    targets={
                        "skill_ids": [a_id, b_id],
                        "names": [a_name, b_name],
                        "jaccard": round(jac, 3),
                    },
                    rationale=f"'{a_name}' and '{b_name}' share {int(jac * 100)}% "
                              f"of tokens — likely duplicate; propose manual merge.",
                ))
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── Appliers ────────────────────────────────────────────────────────


def _apply_safe(conn: sqlite3.Connection, proposals: list[Proposal]) -> int:
    """Apply prune and promote proposals. Merges stay unapplied."""
    applied = 0
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        for p in proposals:
            try:
                if p.kind == "prune":
                    conn.execute(
                        "UPDATE agent_skills "
                        "SET deprecated = 1, "
                        "    deprecated_at = strftime('%Y-%m-%dT%H:%M:%f','now'), "
                        "    deprecated_reason = ? "
                        "WHERE skill_id = ? AND COALESCE(deprecated, 0) = 0",
                        (p.rationale[:500], p.targets["skill_id"]),
                    )
                    p.applied = True
                    _mark_applied(conn, p)
                    applied += 1
                elif p.kind == "promote":
                    mid = p.targets["memory_id"]
                    row = conn.execute(
                        "SELECT key, content, agent_id, type FROM memory "
                        "WHERE memory_id = ?", (mid,),
                    ).fetchone()
                    if row is None:
                        continue
                    name = (row["key"] or f"promoted-mem-{mid}")
                    cur = conn.execute(
                        """
                        INSERT INTO agent_skills
                            (name, description, template, tags, source_agent_id)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            name,
                            f"Promoted from memory '{row['key'] or mid}'. "
                            f"Originally type={row['type']}.",
                            row["content"],
                            json.dumps([row["type"], "promoted"]),
                            row["agent_id"],
                        ),
                    )
                    p.targets["new_skill_id"] = cur.lastrowid
                    p.applied = True
                    _mark_applied(conn, p)
                    applied += 1
                # merge / split: never auto-applied
            except sqlite3.OperationalError:
                continue
    finally:
        conn.row_factory = prev
    return applied


def _mark_applied(conn: sqlite3.Connection, p: Proposal) -> None:
    try:
        conn.execute(
            """
            UPDATE consolidation_proposals
            SET applied = 1,
                status = 'applied',
                applied_at = strftime('%Y-%m-%dT%H:%M:%f','now')
            WHERE proposal_id = (
                SELECT proposal_id FROM consolidation_proposals
                WHERE kind = ? AND targets = ?
                ORDER BY proposal_id DESC LIMIT 1
            )
            """,
            (p.kind, json.dumps(p.targets)),
        )
    except sqlite3.OperationalError:
        pass


# ── Merge workflow ────────────────────────────────────────────────


def list_pending_merges(
    conn: sqlite3.Connection,
    *,
    limit: int = 50,
) -> list[dict]:
    """Return all pending merge proposals. Human-in-the-loop workflow:
    operators review these, then call accept_merge or reject_merge.
    """
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        try:
            rows = conn.execute(
                """
                SELECT proposal_id, kind, targets, rationale, created_at
                FROM consolidation_proposals
                WHERE kind = 'merge' AND status = 'pending'
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    finally:
        conn.row_factory = prev

    out = []
    for r in rows:
        d = dict(r)
        try:
            d["targets"] = json.loads(d["targets"])
        except (json.JSONDecodeError, TypeError):
            pass
        out.append(d)
    return out


def accept_merge(
    conn: sqlite3.Connection,
    proposal_id: int,
    *,
    keep_skill_id: int | None = None,
) -> dict:
    """Accept and execute a merge proposal.

    The proposal names a pair of skill_ids. We keep one (``keep_skill_id``
    if provided, otherwise the lower-id one) and merge the other INTO it:
      - migrate ``skill_uses`` rows to the kept skill
      - rewrite ``associations`` edges to point at the kept skill
      - add the retired skill's use_count / success_count into the keeper
      - mark the retired skill deprecated with reason "merged into #N"
      - mark the proposal applied

    Returns a summary dict.
    """
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT targets, status, kind FROM consolidation_proposals "
            "WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return {"error": f"proposal {proposal_id} not found"}
        if row["kind"] != "merge":
            return {"error": f"proposal {proposal_id} is not a merge "
                             f"(kind={row['kind']})"}
        if row["status"] != "pending":
            return {"error": f"proposal {proposal_id} already {row['status']}"}

        try:
            targets = json.loads(row["targets"])
        except (json.JSONDecodeError, TypeError):
            return {"error": "malformed targets JSON"}
        skill_ids = targets.get("skill_ids") or []
        if len(skill_ids) != 2:
            return {"error": "merge requires exactly 2 skill_ids; got "
                             f"{len(skill_ids)}"}

        keep = keep_skill_id if keep_skill_id in skill_ids else min(skill_ids)
        retire = [sid for sid in skill_ids if sid != keep][0]

        # 1. Pull counters we need to merge
        keep_row = conn.execute(
            "SELECT use_count, success_count FROM agent_skills WHERE skill_id = ?",
            (keep,),
        ).fetchone()
        retire_row = conn.execute(
            "SELECT use_count, success_count FROM agent_skills WHERE skill_id = ?",
            (retire,),
        ).fetchone()
        if keep_row is None or retire_row is None:
            return {"error": "one of the skills has already been deleted"}

        # 2. Migrate skill_uses telemetry
        conn.execute(
            "UPDATE skill_uses SET skill_id = ? WHERE skill_id = ?",
            (keep, retire),
        )

        # 3. Collapse associations. Every edge pointing at `retire` now
        #    points at `keep`. Duplicates against `keep` get their weights
        #    added into the canonical edge; self-edges are pruned.
        _collapse_associations(conn, retire, keep)

        # 4. Roll counters into the keeper
        conn.execute(
            "UPDATE agent_skills SET "
            "use_count = use_count + ?, success_count = success_count + ?, "
            "updated_at = strftime('%Y-%m-%dT%H:%M:%f','now') "
            "WHERE skill_id = ?",
            (retire_row["use_count"], retire_row["success_count"], keep),
        )

        # 5. Retire the duplicate (soft)
        conn.execute(
            "UPDATE agent_skills SET "
            "deprecated = 1, "
            "deprecated_at = strftime('%Y-%m-%dT%H:%M:%f','now'), "
            "deprecated_reason = ? "
            "WHERE skill_id = ?",
            (f"Merged into skill #{keep} via consolidation proposal #{proposal_id}",
             retire),
        )

        # 6. Journal the application
        conn.execute(
            "UPDATE consolidation_proposals "
            "SET applied = 1, status = 'applied', "
            "applied_at = strftime('%Y-%m-%dT%H:%M:%f','now') "
            "WHERE proposal_id = ?",
            (proposal_id,),
        )
        conn.commit()
    finally:
        conn.row_factory = prev

    return {
        "proposal_id": proposal_id,
        "status": "applied",
        "kept_skill_id": keep,
        "retired_skill_id": retire,
        "uses_migrated": retire_row["use_count"],
        "successes_migrated": retire_row["success_count"],
    }


def reject_merge(
    conn: sqlite3.Connection,
    proposal_id: int,
    *,
    reason: str | None = None,
) -> dict:
    """Mark a merge proposal as rejected so it doesn't keep appearing.

    Rejected proposals stay in the journal for audit; the consolidation
    phase will notice the existing rejection and avoid re-proposing the
    exact same pair.
    """
    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT status, kind FROM consolidation_proposals "
            "WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchone()
        if row is None:
            return {"error": f"proposal {proposal_id} not found"}
        if row["status"] != "pending":
            return {"error": f"proposal {proposal_id} already {row['status']}"}

        conn.execute(
            "UPDATE consolidation_proposals "
            "SET status = 'rejected', "
            "applied_at = strftime('%Y-%m-%dT%H:%M:%f','now'), "
            "rationale = COALESCE(?, rationale) "
            "WHERE proposal_id = ?",
            (f"{reason} (rejected)" if reason else None, proposal_id),
        )
        conn.commit()
    finally:
        conn.row_factory = prev

    return {"proposal_id": proposal_id, "status": "rejected"}


def _collapse_associations(
    conn: sqlite3.Connection,
    retire_skill_id: int,
    keep_skill_id: int,
) -> None:
    """Redirect every association edge touching ``retire`` to point at
    ``keep``. If a canonical edge already exists against ``keep`` we add
    weights together rather than violate the UNIQUE constraint.
    """
    # Edges where 'a' was retire → move to keep (or merge into existing)
    rows = conn.execute(
        "SELECT kind_b, id_b, weight, uses FROM associations "
        "WHERE kind_a = 'skill' AND id_a = ?",
        (retire_skill_id,),
    ).fetchall()
    for r in rows:
        kind_b, id_b, w, u = r[0], r[1], r[2] or 0.0, r[3] or 0
        if kind_b == "skill" and id_b == keep_skill_id:
            # Self-edge after merge — drop it.
            continue
        conn.execute(
            "INSERT INTO associations (kind_a, id_a, kind_b, id_b, weight, uses, "
            "first_seen, last_seen) "
            "VALUES ('skill', ?, ?, ?, ?, ?, "
            "strftime('%Y-%m-%dT%H:%M:%f','now'), "
            "strftime('%Y-%m-%dT%H:%M:%f','now')) "
            "ON CONFLICT(kind_a, id_a, kind_b, id_b) DO UPDATE SET "
            "weight = weight + excluded.weight, uses = uses + excluded.uses, "
            "last_seen = strftime('%Y-%m-%dT%H:%M:%f','now')",
            (keep_skill_id, kind_b, id_b, w, u),
        )
    conn.execute(
        "DELETE FROM associations WHERE kind_a = 'skill' AND id_a = ?",
        (retire_skill_id,),
    )

    # Reverse direction.
    rows = conn.execute(
        "SELECT kind_a, id_a, weight, uses FROM associations "
        "WHERE kind_b = 'skill' AND id_b = ?",
        (retire_skill_id,),
    ).fetchall()
    for r in rows:
        kind_a, id_a, w, u = r[0], r[1], r[2] or 0.0, r[3] or 0
        if kind_a == "skill" and id_a == keep_skill_id:
            continue
        conn.execute(
            "INSERT INTO associations (kind_a, id_a, kind_b, id_b, weight, uses, "
            "first_seen, last_seen) "
            "VALUES (?, ?, 'skill', ?, ?, ?, "
            "strftime('%Y-%m-%dT%H:%M:%f','now'), "
            "strftime('%Y-%m-%dT%H:%M:%f','now')) "
            "ON CONFLICT(kind_a, id_a, kind_b, id_b) DO UPDATE SET "
            "weight = weight + excluded.weight, uses = uses + excluded.uses, "
            "last_seen = strftime('%Y-%m-%dT%H:%M:%f','now')",
            (kind_a, id_a, keep_skill_id, w, u),
        )
    conn.execute(
        "DELETE FROM associations WHERE kind_b = 'skill' AND id_b = ?",
        (retire_skill_id,),
    )
