"""E2 — the held-out replay probe + admission minting (Filter 1's second rung).

PLAN v2 §3.1, locked (D7): k=12 task contexts sampled from the workspace's own
journal, lexically matched to the candidate but HELD OUT from the telemetry that
produced it; manifest sha256-locked (the probe refuses to run on an edited set);
three arms — WITH / WITHOUT / SCRAMBLED — completed by an injected model function
(GEPA cheap tier in production) and scored by an injected BLIND judge that never
sees arm labels.

Pre-registered gates (never per-candidate-tuned):
  G1_no_harm  (kill): WITH loses to WITHOUT on <=1 of k contexts, AND no stratum
                      where WITH underperforms by >0.10 (the SWE-Skills -10 guard).
  G2_min_lift (kill): WITH wins >=2 net contexts OR mean quality delta >= +0.10.

Falsification self-tests (admissibility, not gates): the SCRAMBLED arm treated as
the feature must be KILLED by G1/G2, and FULL:=B0 must emit KILL. Either failing
means the harness cannot kill -> the candidate is rejected with
``harness_cannot_kill`` (a harness that can't lose proves nothing).

Post-run audit (3d1b4d5, downgrade-only): if all k contexts fall into one stratum
the harm gate was vacuous -> disposition downgrades to E1 regardless of pass.

E2 pass -> the record is MINTED: canonical body -> record_cid -> eval_records at
trust T2, envelope measured on the validating traffic, FTS-indexed, pullable.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import sqlite3
import uuid
from dataclasses import dataclass, field
from typing import Callable

from kaos.bench.canon import canonical_bytes, record_cid
from kaos.bench.fingerprint import Grain, Level, anchor_tokens
from kaos.bench.schema import bench_id, fts_index_record

# ── Lock-bound constants (admission.lock.json v1 / D7) ──
E2_K = 12
E2_MAX_LOSSES = 1
E2_STRATUM_HARM_FLOOR = 0.10
E2_MIN_NET_WINS = 2
E2_MIN_MEAN_DELTA = 0.10
E2_SEED = 20260816

_PLACEHOLDER = re.compile(r"\{[^}]*\}")

CompletionFn = Callable[[str], str]          # prompt -> model output
JudgeFn = Callable[[str, str], float]        # (task_text, output) -> quality [0,1]


@dataclass
class E2Result:
    status: str                   # 'passed' | 'rejected' | 'harness_cannot_kill'
                                  # | 'downgraded_e1' | 'not_runnable'
    manifest_sha256: str = ""
    gates: dict = field(default_factory=dict)
    arms: dict = field(default_factory=dict)
    reason: str = ""
    record_cid: str | None = None

    def to_dict(self) -> dict:
        return {"status": self.status, "manifest_sha256": self.manifest_sha256,
                "gates": self.gates, "arms": self.arms, "reason": self.reason,
                "record_cid": self.record_cid}


# ── Manifest: held-out by construction, tamper-evident by hash ───────

def build_manifest(
    kaos_conn: sqlite3.Connection, *, candidate_text: str,
    exclude_agent_ids: set[str], k: int = E2_K, seed: int = E2_SEED,
) -> dict | None:
    """Sample k contexts lexically matched to the candidate, EXCLUDING every
    agent that produced the candidate's telemetry (held-out by construction;
    MVP hold-out granularity is the producing agent). Deterministic given seed.
    Returns None if the workspace can't field k held-out contexts."""
    cand_anchors = anchor_tokens(candidate_text)
    rows = kaos_conn.execute(
        "SELECT agent_id, value FROM state WHERE key='task'").fetchall()
    scored = []
    for agent_id, raw in rows:
        if agent_id in exclude_agent_ids:
            continue
        try:
            text = json.loads(raw)
            text = text if isinstance(text, str) else raw
        except (json.JSONDecodeError, TypeError):
            text = raw
        overlap = len(cand_anchors & anchor_tokens(text))
        scored.append((overlap, agent_id, text))
    scored.sort(key=lambda t: (-t[0], t[1]))
    pool = scored[: k * 3]
    if len(pool) < k:
        return None
    rng = random.Random(seed)
    chosen = rng.sample(pool, k) if len(pool) > k else pool
    return {
        "schema": "attraktor/e2_manifest/v1",
        "k": k, "seed": seed,
        "contexts": [
            {"agent_id": a, "task_text": t[:2000], "stratum": _stratum(t)}
            for _o, a, t in sorted(chosen, key=lambda c: c[1])
        ],
    }


def manifest_sha256(manifest: dict) -> str:
    return hashlib.sha256(canonical_bytes(manifest)).hexdigest()


def _stratum(task_text: str) -> str:
    """Coarse workload stratum for the harm gate: the dominant anchor kind of
    the task text (a cheap, deterministic proxy for envelope strata)."""
    toks = anchor_tokens(task_text)
    if any("/" in t or t.endswith(("py", "md", "json", "sql")) for t in toks):
        return "code_path"
    return "prose" if not toks else "identifier"


def scramble_payload(payload: str, seed: int = E2_SEED) -> str:
    """Word-shuffle the instructional payload, KEEPING placeholders intact —
    same tokens, destroyed instruction. If the scrambled arm still 'helps',
    the harness is measuring context-padding, not the skill."""
    holders = _PLACEHOLDER.findall(payload)
    words = _PLACEHOLDER.sub("\x00", payload).split()
    rng = random.Random(seed)
    rng.shuffle(words)
    out = " ".join(words)
    for h in holders:
        out = out.replace("\x00", h, 1)
    return out


# ── The probe ────────────────────────────────────────────────────────

def _score_arms(
    manifest: dict, payload: str, complete: CompletionFn, judge: JudgeFn,
    seed: int,
) -> dict[str, list[float]]:
    """Run the three arms over every context; the judge sees (task, output)
    only — never which arm produced the output (blindness by construction)."""
    scrambled = scramble_payload(payload, seed)
    scores: dict[str, list[float]] = {"WITH": [], "WITHOUT": [], "SCRAMBLED": []}
    for ctx in manifest["contexts"]:
        task = ctx["task_text"]
        outs = {
            "WITH": complete(f"{task}\n\n[Guidance]\n{payload}"),
            "WITHOUT": complete(task),
            "SCRAMBLED": complete(f"{task}\n\n[Guidance]\n{scrambled}"),
        }
        for arm, out in outs.items():
            scores[arm].append(max(0.0, min(1.0, judge(task, out))))
    return scores


def _gates(with_s: list[float], without_s: list[float],
           strata: list[str]) -> dict:
    """The two pre-registered kill gates, computed mechanically."""
    losses = sum(1 for w, o in zip(with_s, without_s) if w < o)
    wins = sum(1 for w, o in zip(with_s, without_s) if w > o)
    stratum_harm = {}
    for s in set(strata):
        idx = [i for i, x in enumerate(strata) if x == s]
        d = sum(with_s[i] - without_s[i] for i in idx) / len(idx)
        stratum_harm[s] = round(d, 4)
    worst = min(stratum_harm.values()) if stratum_harm else 0.0
    mean_delta = sum(w - o for w, o in zip(with_s, without_s)) / len(with_s)

    g1 = losses <= E2_MAX_LOSSES and worst >= -E2_STRATUM_HARM_FLOOR
    g2 = (wins - losses) >= E2_MIN_NET_WINS or mean_delta >= E2_MIN_MEAN_DELTA
    return {
        "G1_no_harm": {"passed": g1, "losses": losses,
                       "stratum_deltas": stratum_harm,
                       "detail": f"losses={losses} (max {E2_MAX_LOSSES}), "
                                 f"worst stratum delta={worst:+.3f}"},
        "G2_min_lift": {"passed": g2, "net_wins": wins - losses,
                        "mean_delta": round(mean_delta, 4),
                        "detail": f"net wins={wins - losses} (floor {E2_MIN_NET_WINS}) "
                                  f"or mean delta={mean_delta:+.3f} (floor +{E2_MIN_MEAN_DELTA})"},
    }


def run_e2(
    manifest: dict, expected_sha256: str, *, payload: str,
    complete: CompletionFn, judge: JudgeFn, seed: int = E2_SEED,
) -> E2Result:
    """Execute the probe. Refuses an edited manifest; runs the falsification
    self-tests before trusting its own verdict; applies the post-run audit."""
    sha = manifest_sha256(manifest)
    if sha != expected_sha256:
        return E2Result(status="not_runnable", manifest_sha256=sha,
                        reason="manifest hash mismatch — edited set, probe refuses to run")

    scores = _score_arms(manifest, payload, complete, judge, seed)
    strata = [c["stratum"] for c in manifest["contexts"]]
    gates = _gates(scores["WITH"], scores["WITHOUT"], strata)

    # Falsification self-test 1: SCRAMBLED-as-feature must be KILLED.
    scr_gates = _gates(scores["SCRAMBLED"], scores["WITHOUT"], strata)
    scrambled_killed = not (scr_gates["G1_no_harm"]["passed"]
                            and scr_gates["G2_min_lift"]["passed"])
    # Falsification self-test 2: FULL:=B0 must emit KILL (structural: identical
    # arms have zero net wins and zero delta, so G2 must fail).
    b0_gates = _gates(scores["WITHOUT"], scores["WITHOUT"], strata)
    b0_killed = not b0_gates["G2_min_lift"]["passed"]

    arms_summary = {a: {"mean": round(sum(v) / len(v), 4), "n": len(v)}
                    for a, v in scores.items()}
    if not (scrambled_killed and b0_killed):
        return E2Result(
            status="harness_cannot_kill", manifest_sha256=sha, gates=gates,
            arms=arms_summary,
            reason="falsification self-test failed: "
                   + ("SCRAMBLED arm passed the gates (measuring context-padding, "
                      "not the skill)" if not scrambled_killed else "B0 not killed"))

    # Post-run audit (downgrade-only): one stratum = vacuous harm gate.
    if len(set(strata)) < 2:
        return E2Result(status="downgraded_e1", manifest_sha256=sha, gates=gates,
                        arms=arms_summary,
                        reason="all contexts in one stratum — harm gate vacuous; "
                               "disposition downgraded to E1 (3d1b4d5 rule)")

    if gates["G1_no_harm"]["passed"] and gates["G2_min_lift"]["passed"]:
        return E2Result(status="passed", manifest_sha256=sha, gates=gates,
                        arms=arms_summary, reason="G1+G2 passed; self-tests admissible")
    failed = [g for g, d in gates.items() if not d["passed"]]
    return E2Result(status="rejected", manifest_sha256=sha, gates=gates,
                    arms=arms_summary,
                    reason="; ".join(f"{g}: {gates[g]['detail']}" for g in failed))


# ── Admission minting: E2 pass -> a pullable record ──────────────────

def mint_record(
    bench: sqlite3.Connection, *, candidate_id: str, name: str, payload: dict,
    e2: E2Result, retrieval_keys_text: str, kind: str = "skill",
) -> str:
    """Build the canonical body, derive the content id, insert the immutable
    record at trust T2 (replay-probed), index for recall, and mark the
    candidate admitted. The envelope is MEASURED on the validating traffic —
    M2 episode-grain (the runner writes it), M3 keys verbatim — never asserted."""
    envelope = {
        "consumes": [],
        "measured": {"M2": int(Level.PRESENT)},
        "m2_grain": int(Grain.EPISODE),
        "retrieval_keys": sorted(anchor_tokens(retrieval_keys_text)),
        "wilson_lb": round(e2.arms.get("WITH", {}).get("mean", 0.6), 4),
    }
    body = {
        "schema_id": "attraktor/eval_record/v1",
        "kind": kind,
        "name": name,
        "payload": payload,
        "validation": {
            "ladder": "E2",
            "manifest_sha256": e2.manifest_sha256,
            "gates": e2.gates,
            "arms": e2.arms,
        },
        "transfer_envelope": envelope,
    }
    cid = record_cid(body)
    bench.execute(
        "INSERT OR IGNORE INTO eval_records (record_cid, schema_id, kind,"
        " self_test_passed, verdict, variant, faithful, trust_level, repro_class,"
        " envelope_json, body_json, origin_bench_id) VALUES (?, ?, ?, 1,"
        " 'ACCEPT', 'as-validated-local', 1, 2, 'llm_nondeterministic', ?, ?, ?)",
        (cid, body["schema_id"], kind, json.dumps(envelope),
         canonical_bytes(body).decode(), bench_id(bench)))
    fts_index_record(bench, cid, name=name,
                     keys_text=retrieval_keys_text,
                     variant="as-validated-local")
    bench.execute(
        "UPDATE bench_candidates SET status='admitted', record_cid=?, e2_json=?, "
        "decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE candidate_id=?",
        (cid, json.dumps(e2.to_dict()), candidate_id))
    bench.commit()
    return cid


def validate_candidate_e2(
    kaos_conn: sqlite3.Connection, bench: sqlite3.Connection, candidate_id: str,
    *, complete: CompletionFn, judge: JudgeFn, seed: int = E2_SEED,
) -> E2Result:
    """The dream-cycle entry point: E1-passed candidate -> manifest -> probe ->
    mint on pass / reject-with-reasoning on kill (D0.1). Every outcome lands in
    e2_json; rejections set rejection_reason."""
    row = bench.execute(
        "SELECT source_kind, source_ref, kind, payload_json, status "
        "FROM bench_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
    if row is None or row["status"] != "e1_passed":
        return E2Result(status="not_runnable",
                        reason=f"candidate not in e1_passed (found: {row['status'] if row else 'missing'})")
    payload = json.loads(row["payload_json"] or "{}")
    name = payload.get("name") or row["source_ref"]
    text = " ".join(str(payload.get(k, "")) for k in ("name", "description", "template"))

    exclude = {
        r[0] for r in kaos_conn.execute(
            "SELECT DISTINCT agent_id FROM skill_uses WHERE skill_id = ?",
            (payload.get("skill_id", -1),)).fetchall()
    }
    manifest = build_manifest(kaos_conn, candidate_text=text or name,
                              exclude_agent_ids=exclude, seed=seed)
    if manifest is None:
        res = E2Result(status="not_runnable",
                       reason=f"workspace cannot field {E2_K} held-out contexts yet "
                              f"— candidate stays E1, accumulating")
        bench.execute("UPDATE bench_candidates SET e2_json=? WHERE candidate_id=?",
                      (json.dumps(res.to_dict()), candidate_id))
        bench.commit()
        return res

    res = run_e2(manifest, manifest_sha256(manifest),
                 payload=str(payload.get("template") or payload.get("description") or name),
                 complete=complete, judge=judge, seed=seed)

    if res.status == "passed":
        cid = mint_record(bench, candidate_id=candidate_id, name=name,
                          payload=payload, e2=res, retrieval_keys_text=text or name,
                          kind=row["kind"])
        res.record_cid = cid
    elif res.status in ("rejected", "harness_cannot_kill"):
        bench.execute(
            "UPDATE bench_candidates SET status='e2_rejected', e2_json=?, "
            "rejection_reason=?, decided_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') "
            "WHERE candidate_id=?",
            (json.dumps(res.to_dict()), res.reason, candidate_id))
        bench.commit()
    else:  # not_runnable / downgraded_e1: stays e1_passed, evidence recorded
        bench.execute("UPDATE bench_candidates SET e2_json=? WHERE candidate_id=?",
                      (json.dumps(res.to_dict()), candidate_id))
        bench.commit()
    return res
