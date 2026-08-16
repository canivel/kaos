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

import json
import logging
import sqlite3
from dataclasses import dataclass, field

import httpx

from kaos.bench.config import BenchConfig

logger = logging.getLogger(__name__)

PUSH_BATCH = 25


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

    records = []
    for r in rows:
        body = json.loads(r["body_json"])
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
        for r in rows:
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
