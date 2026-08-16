"""Feed-back pull — recall → hard gate → rank → K, with the full decision ledger.

PLAN v2 §2.3 pipeline, local code path (the hosted API runs the identical logic):
  1. RECALL   — FTS5/BM25 over name/family/variant/retrieval-keys, over-fetch 4×K.
  2. HARD GATE — Filter 2 (fingerprint.match): consumed axes, monitorability.
                 Every withhold is LOGGED with reason+axis (D0.1).
  3. RANK     — bm25 × wilson_lb × 0.5^(age_days/45) × trust_mult × fidelity_penalty.
  4. TOP-K=3  — the EMPTY pull is a success state and gets its ledger row.
  5. ε-SHADOW — 5% of pulls swap slot K for the best outranked-but-eligible record
                (deterministic by pull_id), tagged shadow — the calibration data
                that keeps the filters from becoming self-sealing. A record
                withheld on a consumed axis is NEVER shadow-served.

T0 is never served — no opt-out, no exception (R14). Quarantined/evicted records
never surface (no bench_item_state row = serving).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from kaos.bench.fingerprint import Envelope, Grain, Level, TaskShape, match

# ── Lock-bound constants ──
K_DEFAULT = 3                      # R6: smallest proposed K — context crowding poisons
OVERFETCH = 4                      # recall 4×K
TRUST_MULT = {1: 0.8, 2: 1.0, 3: 1.1}   # R8; T0 absent on purpose
RECENCY_HALF_LIFE_DAYS = 45.0
PARTIAL_FIDELITY_PENALTY = 0.85
SHADOW_RATE = 0.05                 # ε-shadow

_TOKEN = re.compile(r"[A-Za-z0-9_]+")


@dataclass
class PulledItem:
    record_cid: str
    kind: str
    payload: dict
    trust_level: int
    fidelity: str            # 'full' | 'partial'
    weight: float
    score: float
    shadow: bool = False
    envelope: dict = field(default_factory=dict)


@dataclass
class PullResult:
    pull_id: str
    items: list[PulledItem] = field(default_factory=list)
    withheld_count: int = 0


def _envelope_from_json(raw: str) -> Envelope:
    d = json.loads(raw or "{}")
    return Envelope(
        consumes=tuple(d.get("consumes", ())),
        measured={a: Level(v) for a, v in d.get("measured", {}).items()},
        m2_grain=Grain(d.get("m2_grain", int(Grain.EPISODE))),
        retrieval_keys=set(d.get("retrieval_keys", ())),
    )


def _age_days(created_at: str) -> float:
    try:
        ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds() / 86400.0)


def _fts_query(task_text: str, anchors: set[str]) -> str:
    toks = sorted(anchors) or _TOKEN.findall(task_text.lower())[:16]
    return " OR ".join(f'"{t}"' for t in toks)


def pull(
    bench: sqlite3.Connection,
    *,
    agent_id: str,
    task_text: str,
    task_shape: TaskShape,
    kinds: tuple[str, ...] = ("skill", "learning"),
    k: int = K_DEFAULT,
    task_hash: str | None = None,
    shadow_rate: float = SHADOW_RATE,
) -> PullResult:
    """One pull. Writes the complete ledger (bench_pulls + a decision row for every
    considered record) and returns at most ``k`` served items."""
    pull_id = str(uuid.uuid4())
    bench.execute(
        "INSERT INTO bench_pulls (pull_id, agent_id, task_hash, fingerprint_json, k) "
        "VALUES (?, ?, ?, ?, ?)",
        (pull_id, agent_id, task_hash,
         json.dumps({"m1": int(task_shape.m1), "m2": int(task_shape.m2),
                     "m4": int(task_shape.m4), "m2_grain": int(task_shape.m2_grain),
                     "anchors": sorted(task_shape.m3_anchor_tokens)[:64]}),
         k))

    q = _fts_query(task_text, task_shape.m3_anchor_tokens)
    if not q:
        bench.commit()
        return PullResult(pull_id=pull_id)   # empty pull: logged success state

    placeholders = ",".join("?" for _ in kinds)
    rows = bench.execute(
        f"""
        SELECT r.record_cid, r.kind, r.body_json, r.trust_level, r.envelope_json,
               r.created_at, bm25(bench_fts) AS neg_bm25
        FROM bench_fts
        JOIN eval_records r ON r.record_cid = bench_fts.record_cid
        LEFT JOIN bench_item_state s ON s.record_cid = r.record_cid
        WHERE bench_fts MATCH ?
          AND r.kind IN ({placeholders})
          AND r.status = 'active'
          AND r.verdict = 'ACCEPT'
          AND r.trust_level >= 1                      -- T0 never served, ever
          AND (s.state IS NULL OR s.state = 'serving')
        ORDER BY neg_bm25 LIMIT ?
        """,
        (q, *kinds, k * OVERFETCH),
    ).fetchall()

    served: list[tuple[float, PulledItem]] = []
    outranked_pool: list[tuple[float, PulledItem]] = []
    withheld = 0

    for r in rows:
        env = _envelope_from_json(r["envelope_json"])
        m = match(env, task_shape)
        if m.decision == "WITHHOLD":
            withheld += 1
            bench.execute(
                "INSERT INTO bench_pull_decisions (pull_id, record_cid, decision,"
                " reason, axis) VALUES (?, ?, 'withheld', ?, ?)",
                (pull_id, r["record_cid"], m.reason, m.axis))
            continue

        env_d = json.loads(r["envelope_json"] or "{}")
        wilson = float(env_d.get("wilson_lb", 0.6))
        bm25_score = max(0.0, -float(r["neg_bm25"]))   # fts5 bm25() is negative-better
        recency = 0.5 ** (_age_days(r["created_at"]) / RECENCY_HALF_LIFE_DAYS)
        trust_mult = TRUST_MULT.get(int(r["trust_level"]), 0.0)
        fid_pen = 1.0 if m.fidelity == "full" else PARTIAL_FIDELITY_PENALTY
        score = bm25_score * wilson * recency * trust_mult * fid_pen
        if score <= 0.0:
            continue
        item = PulledItem(
            record_cid=r["record_cid"], kind=r["kind"],
            payload=json.loads(r["body_json"] or "{}"),
            trust_level=int(r["trust_level"]), fidelity=m.fidelity,
            weight=m.weight, score=round(score, 6), envelope=env_d)
        served.append((score, item))

    served.sort(key=lambda t: (-t[0], t[1].record_cid))
    top, rest = served[:k], served[k:]
    outranked_pool = rest

    # ε-shadow: deterministic by pull_id; swap slot K with the best outranked
    # eligible record. Withheld records were never candidates here — I2 holds.
    if top and outranked_pool and shadow_rate > 0:
        h = int(hashlib.sha256(pull_id.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        if h < shadow_rate:
            _, shadow_item = outranked_pool[0]
            shadow_item.shadow = True
            top[-1] = (outranked_pool[0][0], shadow_item)
            outranked_pool = outranked_pool[1:] + [served[k - 1]] if len(served) >= k else outranked_pool[1:]

    for score, item in top:
        bench.execute(
            "INSERT INTO bench_pull_decisions (pull_id, record_cid, decision,"
            " weight, fidelity, rank_score) VALUES (?, ?, ?, ?, ?, ?)",
            (pull_id, item.record_cid, "shadow" if item.shadow else "served",
             item.weight, item.fidelity, score))
    for score, item in outranked_pool:
        bench.execute(
            "INSERT OR IGNORE INTO bench_pull_decisions (pull_id, record_cid,"
            " decision, rank_score) VALUES (?, ?, 'outranked', ?)",
            (pull_id, item.record_cid, score))
    bench.commit()

    return PullResult(pull_id=pull_id, items=[i for _, i in top],
                      withheld_count=withheld)


def report_outcome(
    bench: sqlite3.Connection, *, record_cid: str, agent_id: str,
    invoked: bool, outcome: bool | None, outcome_source: str,
    task_hash: str | None = None, fidelity: float | None = None,
    shadow: bool = False,
) -> None:
    """Close the loop: one outcome row per pulled item. outcome_source must be
    runner/harness/mechanical — the schema makes self-report unrepresentable."""
    bench.execute(
        "INSERT INTO outcome_telemetry (telemetry_id, record_cid, agent_id,"
        " task_hash, invoked, outcome, outcome_source, fidelity, shadow)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), record_cid, agent_id, task_hash,
         1 if invoked else 0,
         None if outcome is None else (1 if outcome else 0),
         outcome_source, fidelity, 1 if shadow else 0))
    bench.commit()
