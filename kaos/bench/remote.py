"""Remote sync — push local validated records to a shared Attraktor bench.

D5 publish routing happens SERVER-side from the token's workspace tier
(individual -> public admission queue, team/enterprise -> workspace); the
client only presents its env-held token. The payload carries the EXACT
canonical bytes stored at mint time, so the server re-derives the record_cid
and refuses anything that doesn't hash to its claimed identity — content
addressing is the trust anchor on both ends.

The outbox (bench_outbox) makes push idempotent and resumable: every record
gets a row per remote; only 'queued'/'sent'-with-error rows retry. Raw httpx,
per the KAOS rules — no SDK.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from dataclasses import dataclass, field

from kaos._extras import require

httpx = require("httpx", "router", "Attraktor remote sync")

from kaos.bench.config import BenchConfig
from kaos.bench.schema import bench_id, fts_index_record

logger = logging.getLogger(__name__)

PUSH_BATCH = 25
PULL_TIMEOUT_S = 2.5   # hook-path fetch must never stall an agent start


@dataclass
class PushReport:
    pushed: int = 0
    duplicates: int = 0
    refused: int = 0
    errors: int = 0
    details: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return self.__dict__.copy()


def _pending_records(bench: sqlite3.Connection, remote: str, limit: int) -> list[sqlite3.Row]:
    bench.execute(
        """INSERT OR IGNORE INTO bench_outbox (record_cid, remote)
           SELECT record_cid, ? FROM eval_records WHERE status = 'active'""",
        (remote,))
    bench.commit()
    return bench.execute(
        """SELECT r.record_cid, r.schema_id, r.kind, r.verdict, r.trust_level,
                  r.variant, r.envelope_json, r.body_json
           FROM bench_outbox o JOIN eval_records r ON r.record_cid = o.record_cid
           WHERE o.remote = ? AND o.state IN ('queued', 'rejected')
           ORDER BY r.created_at LIMIT ?""",
        (remote, limit)).fetchall()


def push_records(
    bench: sqlite3.Connection, cfg: BenchConfig, *,
    limit: int = PUSH_BATCH, client: httpx.Client | None = None,
) -> PushReport:
    """One push pass. Requires cfg.endpoint + a token in the environment."""
    rep = PushReport()
    if not cfg.is_remote:
        rep.details.append({"error": "no bench.endpoint configured — local-only mode"})
        return rep
    token = cfg.token()
    if not token:
        rep.details.append({"error": f"${cfg.token_env} is not set — generate a token "
                                     f"in the Attraktor dashboard and export it"})
        return rep

    rows = _pending_records(bench, cfg.endpoint, limit)
    if not rows:
        return rep

    # Knowledge requirement (D9): a record must carry something a consumer
    # can act on. Publishing name+hashes teaches nobody — refuse locally
    # with a fix-it reason instead of wasting the round trip.
    KNOWLEDGE_KEYS = ("lesson", "mechanism", "summary", "template",
                      "description", "content")

    def _has_knowledge(body: dict) -> bool:
        inner = body.get("payload") or {}
        return any(str(src.get(k) or "").strip()
                   for src in (body, inner) for k in KNOWLEDGE_KEYS)

    records = []
    sendable_rows = []
    for r in rows:
        body = json.loads(r["body_json"])
        if not _has_knowledge(body):
            reason = ("refused locally: no consumable knowledge — add "
                      "mechanism/summary/lesson to the experiment metadata "
                      "(kaos experiment log) or template/description for skills, "
                      "then re-mint")
            bench.execute(
                "UPDATE bench_outbox SET state='rejected', last_error=?,"
                " updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                " WHERE record_cid=? AND remote=?",
                (reason, r["record_cid"], cfg.endpoint))
            rep.refused += 1
            rep.details.append({"record_cid": r["record_cid"], "status": reason})
            continue
        sendable_rows.append(r)
        env = json.loads(r["envelope_json"] or "{}")
        records.append({
            "record_cid": r["record_cid"],
            "schema_id": r["schema_id"],
            "body_canonical": r["body_json"],       # exact canonical bytes
            "kind": r["kind"],
            "name": body.get("name", r["record_cid"][:16]),
            "family": (body.get("payload") or {}).get("family", ""),
            "verdict": r["verdict"],
            "trust_level": r["trust_level"],
            "variant": r["variant"],
            "envelope": env,
            "keys_text": " ".join(env.get("retrieval_keys", [])),
        })
    if rep.refused:
        bench.commit()
    if not records:
        return rep

    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    try:
        resp = client.post(
            f"{cfg.endpoint.rstrip('/')}/v1/push",
            json={"records": records},
            headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            rep.errors = len(records)
            rep.details.append({"error": f"push failed: HTTP {resp.status_code}",
                                "body": resp.text[:200]})
            return rep
        outcome = resp.json()
        by_cid = {p["record_cid"]: p["status"] for p in outcome.get("pushed", [])}
        for r in sendable_rows:
            status = by_cid.get(r["record_cid"], "missing from response")
            if (status.startswith("admitted") or status.startswith("queued")
                    or status.startswith("stored")):
                state, bucket = "accepted", "pushed"
            elif status.startswith("duplicate"):
                state, bucket = "accepted", "duplicates"
            else:
                state, bucket = "rejected", "refused"
            setattr(rep, bucket, getattr(rep, bucket) + 1)
            bench.execute(
                "UPDATE bench_outbox SET state = ?, last_error = ?,"
                " updated_at = strftime('%Y-%m-%dT%H:%M:%fZ','now')"
                " WHERE record_cid = ? AND remote = ?",
                (state, None if state == "accepted" else status,
                 r["record_cid"], cfg.endpoint))
            rep.details.append({"record_cid": r["record_cid"], "status": status})
        bench.commit()
        return rep
    except httpx.HTTPError as e:
        rep.errors = len(records)
        rep.details.append({"error": f"push failed: {e}"})
        return rep
    finally:
        if owns_client:
            client.close()


# ── feed-back: remote pull with sync-on-read caching ─────────────────
#
# The registry's /v1/pull is RECALL only; the transfer-match hard gate
# (Filter 2) stays client-side. Design: fetched records are VERIFIED
# (sha256 of the canonical bytes must equal the claimed cid — the same
# check the server ran on push, now run by the consumer) and cached into
# the local bench as first-class eval_records. The normal local pull()
# then serves them through the ONE audited pipeline: match gate, ranking,
# arm assignment, decision ledger, outcome telemetry. No second code path.


def fetch_and_cache(
    bench: sqlite3.Connection, cfg: BenchConfig, *,
    task_text: str, k: int = 6, client: httpx.Client | None = None,
) -> int:
    """One recall round-trip. Returns the number of NEWLY cached records.
    Best-effort by contract: any failure returns 0 and the workspace runs
    on its local brain exactly as before."""
    if not cfg.is_remote:
        return 0
    token = cfg.token()
    if not token:
        return 0
    from kaos.bench.fingerprint import anchor_tokens

    q = " ".join(sorted(anchor_tokens(task_text))[:16]) or task_text[:120]
    owns = client is None
    client = client or httpx.Client(timeout=PULL_TIMEOUT_S)
    try:
        resp = client.get(
            f"{cfg.endpoint.rstrip('/')}/v1/pull",
            params={"q": q, "k": k},
            headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            logger.warning("remote pull HTTP %s — using local brain only",
                           resp.status_code)
            return 0
        items = resp.json().get("items", [])
    except (httpx.HTTPError, ValueError) as e:
        logger.warning("remote pull failed (%s) — using local brain only", e)
        return 0
    finally:
        if owns:
            client.close()

    cached = 0
    origin = f"remote:{cfg.endpoint}"
    for it in items:
        cid = str(it.get("record_cid", ""))
        body_canonical = str(it.get("body_json", ""))
        # Consumer-side content verification: never cache bytes that do not
        # hash to their claimed identity, no matter who served them.
        if (not cid.startswith("tb1:") or not body_canonical
                or "tb1:" + hashlib.sha256(body_canonical.encode()).hexdigest() != cid):
            logger.warning("remote record %s failed cid verification — refused",
                           cid[:24])
            continue
        try:
            body = json.loads(body_canonical)
        except ValueError:
            continue
        cur = bench.execute(
            "INSERT OR IGNORE INTO eval_records (record_cid, schema_id, kind,"
            " self_test_passed, verdict, variant, faithful, trust_level,"
            " repro_class, envelope_json, body_json, origin_bench_id)"
            " VALUES (?, ?, ?, 1, ?, ?, 1, ?, 'llm_nondeterministic', ?, ?, ?)",
            (cid, str(it.get("schema_id") or body.get("schema_id")
                      or "attraktor/eval_record/v1"),
             str(it.get("kind", "learning")),
             str(it.get("verdict", "ACCEPT")),
             str(it.get("variant", "as-is")),
             int(it.get("trust_level", 1)),
             it.get("envelope_json") or "{}",
             body_canonical, bench_id(bench)))
        if cur.rowcount:
            cached += 1
            inner = body.get("payload") or {}
            fts_index_record(
                bench, cid,
                name=str(it.get("name") or body.get("name") or cid[:16]),
                family=str(it.get("family") or inner.get("family") or ""),
                variant=str(it.get("variant", "")),
                keys_text=" ".join(
                    json.loads(it.get("envelope_json") or "{}").get("retrieval_keys", [])
                ) + f" {inner.get('mechanism', '')} {inner.get('lesson', '')}")
    if cached:
        bench.commit()
        logger.info("cached %d record(s) from %s", cached, origin)
    return cached
