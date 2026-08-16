"""Feed-forward harvest — zero user actions (loop liveness is a product requirement).

PLAN v2 §2.2: three automatic surfaces feed `bench_candidates`, idempotently
(UNIQUE(source_kind, source_ref) — INSERT OR IGNORE):

1. **Skill telemetry** (`skill_uses`) — candidates crossing the quick floors get
   E1 evaluated at harvest, pure SQL, zero model calls. Rows without an
   admissible outcome source (today's legacy rows are caller-claimed →
   ``self_report``) are excluded as evidence by construction, so the flagship
   workspace's M2 famine surfaces as honest E0 rows, not fake validation.
2. **Dream promotions** — applied consolidation promotions enter as E0
   candidates (they have no use telemetry yet; the ladder validates them as it
   accrues).
3. **Experiments journal** — every mechanism verdict (ACCEPT *and* REJECT/VOID)
   harvests as ``mechanism_eval``; the full pre-registered probe IS its
   validation, so it skips the E1/E2 ladder (status ``e1_passed`` at harvest,
   admission builds the record later).

Outcome-status transitions on candidates:
  floors unmet  -> stays 'harvested' (E0 — not a dud; re-evaluated as n grows)
  floors met + E1 fail -> 'e1_rejected' with full reasoning (a dataset row, D0.1)
  floors met + E1 pass -> 'e1_passed' (queued for the E2 replay probe)
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass

from kaos.bench.entry import TelemetryRow, evaluate_e1

# Quick SQL prefilter floors (mirror E1 A1/A2; cheap superset check).
_PREFILTER_MIN_USES = 10
_LEGACY_SOURCE = "self_report"   # skill_uses has no outcome_source column (yet)


@dataclass
class HarvestReport:
    skills_seen: int = 0
    skills_harvested: int = 0
    promotions_harvested: int = 0
    experiments_harvested: int = 0
    e1_passed: int = 0
    e1_rejected: int = 0
    e0_accumulating: int = 0

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _insert_candidate(
    bench: sqlite3.Connection, *, source_kind: str, source_ref: str,
    kind: str, payload: dict,
) -> str | None:
    """INSERT OR IGNORE; returns candidate_id if newly inserted, else None."""
    cid = str(uuid.uuid4())
    cur = bench.execute(
        "INSERT OR IGNORE INTO bench_candidates "
        "(candidate_id, source_kind, source_ref, kind, payload_json) "
        "VALUES (?, ?, ?, ?, ?)",
        (cid, source_kind, source_ref, kind, json.dumps(payload)),
    )
    return cid if cur.rowcount else None


def _decide_e1(bench: sqlite3.Connection, candidate_id: str,
               exposed: list[TelemetryRow], unexposed: list[TelemetryRow],
               report: HarvestReport) -> None:
    res = evaluate_e1(exposed, unexposed)
    e1_json = json.dumps(res.to_dict())
    if not res.floors_met:
        # E0: record the evaluation, keep status 'harvested' — still accumulating.
        bench.execute(
            "UPDATE bench_candidates SET e1_json=? WHERE candidate_id=?",
            (e1_json, candidate_id))
        report.e0_accumulating += 1
    elif res.passed:
        bench.execute(
            "UPDATE bench_candidates SET status='e1_passed', e1_json=?, "
            "decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE candidate_id=?",
            (e1_json, candidate_id))
        report.e1_passed += 1
    else:
        bench.execute(
            "UPDATE bench_candidates SET status='e1_rejected', e1_json=?, "
            "rejection_reason=?, decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE candidate_id=?",
            (e1_json, res.reason, candidate_id))
        report.e1_rejected += 1


def harvest_skills(
    kaos_conn: sqlite3.Connection, bench: sqlite3.Connection,
    report: HarvestReport, *, source_map: dict[int, str] | None = None,
) -> None:
    """Harvest skills whose reported-use count crosses the prefilter floor.

    ``source_map`` maps use_id -> outcome_source for rows whose provenance IS
    known (runner-written going forward); unmapped rows are honestly
    ``self_report`` and count as nothing.
    """
    source_map = source_map or {}
    skills = kaos_conn.execute(
        "SELECT skill_id, COUNT(*) AS n FROM skill_uses "
        "WHERE success IS NOT NULL GROUP BY skill_id HAVING n >= ?",
        (_PREFILTER_MIN_USES,),
    ).fetchall()
    report.skills_seen = len(skills)

    for skill_id, _n in skills:
        cid = _insert_candidate(
            bench, source_kind="skill_telemetry", source_ref=f"skill:{skill_id}",
            kind="skill", payload={"skill_id": skill_id})
        if cid is None:
            continue  # already harvested (dud-dedup / idempotency)
        report.skills_harvested += 1

        rows = kaos_conn.execute(
            "SELECT use_id, agent_id, task_hash, success, quality "
            "FROM skill_uses WHERE skill_id=? AND success IS NOT NULL",
            (skill_id,),
        ).fetchall()
        exposed = [
            TelemetryRow(
                agent_id=r[1] or "unknown",
                task_hash=r[2] or "unbucketed",
                success=bool(r[3]),
                outcome_source=source_map.get(r[0], _LEGACY_SOURCE),
                quality=r[4],
            )
            for r in rows
        ]
        # Unexposed arm: comparable non-use outcomes. No organic source exists yet
        # (PLAN v2 risk #3 — pulling itself will write exposure rows); empty for now.
        _decide_e1(bench, cid, exposed, [], report)
    bench.commit()


def harvest_dream_promotions(
    kaos_conn: sqlite3.Connection, bench: sqlite3.Connection, report: HarvestReport,
) -> None:
    try:
        rows = kaos_conn.execute(
            "SELECT proposal_id, kind, targets, rationale FROM consolidation_proposals "
            "WHERE kind='promote' AND (applied=1 OR status='applied')").fetchall()
    except sqlite3.OperationalError:
        rows = []
    for pid, kind, targets, rationale in rows:
        cid = _insert_candidate(
            bench, source_kind="dream_promotion", source_ref=f"proposal:{pid}",
            kind="skill",
            payload={"proposal_kind": kind, "targets": json.loads(targets or "{}"),
                     "rationale": rationale})
        if cid is not None:
            report.promotions_harvested += 1  # enters at E0; ladder validates later
    bench.commit()


def harvest_experiments(
    kaos_conn: sqlite3.Connection, bench: sqlite3.Connection, report: HarvestReport,
) -> None:
    """Every mechanism verdict — ACCEPT AND REJECT/VOID — is a candidate. The
    rejections are the credibility of the dataset (D0.1)."""
    try:
        rows = kaos_conn.execute(
            "SELECT exp_id, name, family, verdict, lock_sha256, git_sha "
            "FROM experiments WHERE verdict IS NOT NULL").fetchall()
    except sqlite3.OperationalError:
        rows = []
    for exp_id, name, family, verdict, lock_sha, git_sha in rows:
        cid = _insert_candidate(
            bench, source_kind="experiment", source_ref=f"exp:{exp_id}",
            kind="mechanism_eval",
            payload={"name": name, "family": family, "verdict": verdict,
                     "lock_sha256": lock_sha, "git_sha": git_sha})
        if cid is None:
            continue
        report.experiments_harvested += 1
        # The full pre-registered probe IS the validation — ladder skipped.
        bench.execute(
            "UPDATE bench_candidates SET status='e1_passed', "
            "e1_json='{\"ladder\": \"skipped — full pre-registered probe is the validation\"}', "
            "decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE candidate_id=?",
            (cid,))
        report.e1_passed += 1
    bench.commit()


def harvest_all(
    kaos_conn: sqlite3.Connection, bench: sqlite3.Connection,
    *, source_map: dict[int, str] | None = None,
) -> HarvestReport:
    """One idempotent pass over all three surfaces. Safe to run any number of
    times; already-harvested sources are skipped by the UNIQUE key."""
    report = HarvestReport()
    harvest_skills(kaos_conn, bench, report, source_map=source_map)
    harvest_dream_promotions(kaos_conn, bench, report)
    harvest_experiments(kaos_conn, bench, report)
    return report
