"""Validation driver — processes pending candidates through the entry ladder.

Two candidate classes, two paths:
- ``experiment`` (mechanism evals): their pre-registered hash-locked probe IS the
  validation — minted directly at trust T1 (lock-anchored), verdict preserved
  (REJECT/VOID mint too: rejections are data, D0.1; pull() serves only ACCEPT).
  Needs NO model — this is how the seed content (the dogfooded probe verdicts)
  enters the brain.
- ``skill``/``learning``: run the E2 held-out replay probe (needs a completion
  fn + judge). Without a model available these stay E1, accumulating — never
  silently skipped, always counted.

Also here: the deterministic blind judge (documented-weak MVP default; the judge
is injectable and upgrades to an LLM-blind judge later without touching the
probe), the async-router completion adapter, and the dream-cycle phase entry.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from kaos.bench.fingerprint import anchor_tokens
from kaos.bench.replay import CompletionFn, JudgeFn, mint_record, validate_candidate_e2

logger = logging.getLogger(__name__)

_REFUSAL_MARKS = ("i cannot", "i can't", "unable to", "as an ai")


def heuristic_judge(task: str, output: str) -> float:
    """Deterministic, blind, documented-weak MVP judge.

    Scores structure, not truth: empty/refusal-shaped outputs score low; outputs
    engaging the task's anchor tokens score higher. This is honest scaffolding —
    E2's falsification self-tests still hold (a padding-rewarding judge gets
    caught by the SCRAMBLED arm), but real semantic judging needs the LLM-blind
    judge upgrade. Injectable everywhere for exactly that reason."""
    if not output or not output.strip():
        return 0.0
    low = output.lower()
    if any(m in low for m in _REFUSAL_MARKS):
        return 0.2
    t_anchors = anchor_tokens(task)
    if not t_anchors:
        return 0.5
    overlap = len(t_anchors & anchor_tokens(output)) / len(t_anchors)
    return round(min(1.0, 0.3 + 0.7 * overlap), 3)


def completion_from_router(router, *, force_model: str | None = None) -> CompletionFn:
    """Sync adapter over the async GEPA router (the E2 probe is synchronous;
    dream/CLI contexts have no running loop)."""
    import asyncio

    def _complete(prompt: str) -> str:
        async def _go():
            cfg = {"force_model": force_model} if force_model else {}
            resp = await router.route(
                agent_id="bench-validate",
                messages=[{"role": "user", "content": prompt}],
                tools=[], config=cfg)
            return resp.content or ""
        return asyncio.run(_go())

    return _complete


@dataclass
class ValidateReport:
    minted_mechanism_evals: int = 0
    e2_passed: int = 0
    e2_rejected: int = 0
    harness_inadmissible: int = 0
    not_runnable: int = 0
    skipped_no_model: int = 0
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def validate_pending(
    kaos_conn: sqlite3.Connection, bench: sqlite3.Connection, *,
    complete: CompletionFn | None = None, judge: JudgeFn | None = None,
    limit: int | None = None,
) -> ValidateReport:
    """One pass over every ``e1_passed`` candidate. Idempotent; safe to run from
    the dream cycle or the CLI. Never raises past a candidate (liveness)."""
    rep = ValidateReport()
    judge = judge or heuristic_judge
    rows = bench.execute(
        "SELECT candidate_id, source_kind, source_ref, kind, payload_json "
        "FROM bench_candidates WHERE status='e1_passed' ORDER BY harvested_at"
        + (f" LIMIT {int(limit)}" if limit else "")).fetchall()

    for row in rows:
        import json as _json
        payload = _json.loads(row["payload_json"] or "{}")
        try:
            if row["source_kind"] == "experiment":
                name = payload.get("name") or row["source_ref"]
                verdict_raw = str(payload.get("verdict") or "VOID")
                verdict = ("ACCEPT" if verdict_raw.startswith("ACCEPT")
                           else "REJECT" if verdict_raw.startswith("REJECT") else "VOID")
                cid = mint_record(
                    bench, candidate_id=row["candidate_id"], name=name,
                    payload=payload, kind="mechanism_eval",
                    retrieval_keys_text=f"{name} {payload.get('family', '')}",
                    validation={"ladder": "skipped — pre-registered probe is the validation",
                                "verdict": verdict_raw,
                                "lock_sha256": payload.get("lock_sha256"),
                                "git_sha": payload.get("git_sha")},
                    verdict=verdict, trust_level=1, variant="as-probed",
                )
                rep.minted_mechanism_evals += 1
                rep.details.append({"candidate": row["source_ref"],
                                    "outcome": f"minted {verdict}", "record_cid": cid})
            elif complete is None:
                rep.skipped_no_model += 1
                rep.details.append({"candidate": row["source_ref"],
                                    "outcome": "skipped — no model available; stays E1"})
            else:
                res = validate_candidate_e2(
                    kaos_conn, bench, row["candidate_id"],
                    complete=complete, judge=judge)
                key = {"passed": "e2_passed", "rejected": "e2_rejected",
                       "harness_cannot_kill": "harness_inadmissible"}.get(
                    res.status, "not_runnable")
                setattr(rep, key, getattr(rep, key) + 1)
                rep.details.append({"candidate": row["source_ref"],
                                    "outcome": res.status, "reason": res.reason[:160]})
        except Exception as e:  # noqa: BLE001 — one bad candidate never stops the pass
            logger.warning("validate_pending: candidate %s failed: %s",
                           row["candidate_id"], e)
            rep.not_runnable += 1
            rep.details.append({"candidate": row["source_ref"], "outcome": f"error: {e}"})
    return rep


def dream_phase(
    kaos_conn: sqlite3.Connection, kaos_db_path: str | Path, *,
    complete: CompletionFn | None = None, judge: JudgeFn | None = None,
    bench_path: str | Path | None = None,
) -> dict:
    """The dream-cycle entry: auto-harvest + validate pending. Best-effort — a
    broken bench must never break the dream cycle. Without a completion fn the
    phase still harvests and mints mechanism evals (no model needed)."""
    from kaos.bench.harvest import harvest_all
    from kaos.bench.schema import open_bench

    try:
        path = Path(bench_path) if bench_path else Path(kaos_db_path).parent / "bench.db"
        bench = open_bench(path)
        try:
            h = harvest_all(kaos_conn, bench)
            v = validate_pending(kaos_conn, bench, complete=complete, judge=judge)
        finally:
            bench.close()
        return {"harvest": h.to_dict(), "validate": v.to_dict()}
    except Exception as e:  # noqa: BLE001
        logger.warning("bench dream phase degraded to no-op: %s", e)
        return {"error": str(e)}
