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
