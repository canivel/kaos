"""Policies phase — promote recurring shared-log patterns to auto-policies.

Reads the shared_log for intent→vote→decide cycles. When the same `action`
string has been proposed N times and approved at >= 90%, promote it to the
`policies` table so future intents matching the pattern can short-circuit.

This is conservative on purpose: wrong auto-approval could be costly, so the
thresholds are deliberately high. Policies are disabled-by-default in M3 —
the table gets populated but nothing consults it yet. M4 will wire active
consultation into the shared-log write path.
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field


@dataclass
class PromotedPolicy:
    policy_id: int | None
    action_pattern: str
    approval_rate: float
    sample_size: int
    newly_promoted: bool = False


@dataclass
class PoliciesReport:
    candidates: list[PromotedPolicy] = field(default_factory=list)
    total_promoted: int = 0
    skipped_existing: int = 0


DEFAULT_MIN_SAMPLES = 3
DEFAULT_APPROVAL_THRESHOLD = 0.9


def run(
    conn: sqlite3.Connection,
    *,
    dry_run: bool = True,
    min_samples: int = DEFAULT_MIN_SAMPLES,
    approval_threshold: float = DEFAULT_APPROVAL_THRESHOLD,
) -> PoliciesReport:
    report = PoliciesReport()

    prev = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        try:
            intents = conn.execute(
                "SELECT log_id, agent_id, payload, created_at "
                "FROM shared_log WHERE type = 'intent' ORDER BY created_at"
            ).fetchall()
        except sqlite3.OperationalError:
            return report

        if not intents:
            return report

        # Bucket intents by normalised action
        buckets: dict[str, list[int]] = {}
        for row in intents:
            action = _action_of(row["payload"])
            if not action:
                continue
            buckets.setdefault(_normalise_action(action), []).append(row["log_id"])

        existing = set(_existing_patterns(conn))

        for pattern, log_ids in buckets.items():
            if len(log_ids) < min_samples:
                continue

            approvals, total = _count_votes(conn, log_ids)
            if total == 0:
                continue
            rate = approvals / total
            if rate < approval_threshold:
                continue

            candidate = PromotedPolicy(
                policy_id=None,
                action_pattern=pattern,
                approval_rate=round(rate, 3),
                sample_size=total,
                newly_promoted=pattern not in existing,
            )

            if pattern in existing:
                report.skipped_existing += 1
                candidate.newly_promoted = False
            elif not dry_run:
                try:
                    cur = conn.execute(
                        "INSERT INTO policies "
                        "(action_pattern, approval_rate, sample_size, source_runs) "
                        "VALUES (?, ?, ?, ?)",
                        (pattern, rate, total, json.dumps(log_ids)),
                    )
                    candidate.policy_id = cur.lastrowid
                    candidate.newly_promoted = True
                    report.total_promoted += 1
                except sqlite3.OperationalError:
                    pass

            report.candidates.append(candidate)
    finally:
        conn.row_factory = prev

    try:
        conn.commit()
    except sqlite3.OperationalError:
        pass

    return report


# ── Helpers ─────────────────────────────────────────────────────────


def _action_of(payload_json: str | None) -> str | None:
    if not payload_json:
        return None
    try:
        data = json.loads(payload_json)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict):
        return str(data.get("action") or data.get("intent") or "").strip() or None
    return None


_NORMALISE_RE = re.compile(r"\s+")


def _normalise_action(action: str) -> str:
    # Canonicalise so "migrate database" and "Migrate  database" match.
    return _NORMALISE_RE.sub(" ", action.strip().lower())


def _count_votes(
    conn: sqlite3.Connection,
    intent_ids: list[int],
) -> tuple[int, int]:
    """Return (approval_count, total_votes) for votes referencing these intents."""
    if not intent_ids:
        return 0, 0
    placeholders = ",".join("?" * len(intent_ids))
    try:
        rows = conn.execute(
            f"SELECT payload FROM shared_log "
            f"WHERE type = 'vote' AND ref_id IN ({placeholders})",
            intent_ids,
        ).fetchall()
    except sqlite3.OperationalError:
        return 0, 0
    total = 0
    approvals = 0
    for row in rows:
        try:
            d = json.loads(row["payload"] or "{}")
        except (json.JSONDecodeError, TypeError):
            d = {}
        total += 1
        if _is_approval(d):
            approvals += 1
    return approvals, total


def _is_approval(vote: dict) -> bool:
    approve = vote.get("approve")
    if approve is None:
        approve = vote.get("approved")
    if isinstance(approve, bool):
        return approve
    if isinstance(approve, str):
        return approve.strip().lower() in ("true", "yes", "approve", "approved", "1")
    return False


def _existing_patterns(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute(
            "SELECT action_pattern FROM policies WHERE enabled = 1"
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    return [r["action_pattern"] for r in rows]
