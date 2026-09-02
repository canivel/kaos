"""LongMemEval on KAOS FTS5 memory — split-reported recall@5.

Pre-registered in ``preregistration.json`` (dataset hashes, split function,
query sanitizer, gates). The runner refuses to run on a lock whose sha256 is
not in ``KNOWN_LOCK_SHA256``.

    uv run python benchmarks/longmemeval/download.py
    uv run python benchmarks/longmemeval/run_longmemeval.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics
import sys
import time
from collections import defaultdict
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from kaos import Kaos
from kaos.eval.harness import load_lock, sha256_file
from kaos.memory import MemoryStore

HERE = Path(__file__).parent
LOCK_PATH = HERE / "preregistration.json"
DATA = HERE / "data"
RESULTS_DIR = HERE / "results"

# Pre-registered lock hashes — the runner refuses any other lock file.
KNOWN_LOCK_SHA256: dict[str, str] = {
    "fc191bfb93454f3bec6b7e8ff65fddc946b2cef077a1424dc46cc7cc162070d8": "v1-pre-registration",
}

STOPWORDS = frozenset(
    "a an the of on in to for by with and or is are was were be been from at as it "
    "its this that these those when after before into over under not no i me my we "
    "our you your he she they them his her their what which who whom how why where "
    "did do does done have has had was am is".split()
)
TOP_K = 5


def content_tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


def query_of(question: str) -> str:
    seen: list[str] = []
    for t in content_tokens(question):
        if t not in seen:
            seen.append(t)
    return " OR ".join(seen)


def trigrams(tokens: list[str]) -> set[tuple[str, str, str]]:
    return set(zip(tokens, tokens[1:], tokens[2:]))


def bucket_of(question: str, evidence_texts: list[str]) -> str:
    q = trigrams(content_tokens(question))
    for text in evidence_texts:
        if q & trigrams(content_tokens(text)):
            return "verbatim"
    return "paraphrase"


def session_text(session: list[dict]) -> str:
    return "\n".join(f"{t.get('role', '?')}: {t.get('content', '')}" for t in session)


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    if len(xs) == 1:
        return xs[0]
    return statistics.quantiles(xs, n=20)[-1]


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def score_question(q: dict, top_k: int = TOP_K) -> dict:
    """Fresh db, one memory per haystack session, one timed search."""
    ids = q["haystack_session_ids"]
    sessions = q["haystack_sessions"]
    answer_ids = set(q.get("answer_session_ids") or [])
    texts = {sid: session_text(s) for sid, s in zip(ids, sessions)}
    bucket = bucket_of(q["question"], [texts[a] for a in answer_ids if a in texts])

    kaos = Kaos(":memory:")
    agent = kaos.spawn("lme-writer")
    mem = MemoryStore(kaos.conn)
    for sid in ids:
        mem.write(agent, texts[sid], type="observation", key=sid)

    query = query_of(q["question"])
    t0 = time.perf_counter()
    try:
        hits = mem.search(query, limit=top_k, rank="bm25") if query else []
    except Exception:
        hits = []
    latency_ms = (time.perf_counter() - t0) * 1000.0
    try:
        kaos.conn.close()
    except Exception:
        pass
    return {
        "question_id": q["question_id"],
        "question_type": q["question_type"],
        "bucket": bucket,
        "n_sessions": len(ids),
        "hit": any(h.key in answer_ids for h in hits),
        "latency_ms": round(latency_ms, 3),
        "has_evidence": bool(answer_ids),
    }


def run_file(path: Path, limit: int | None = None) -> dict:
    data = json.loads(path.read_text())
    if limit:
        data = data[:limit]
    rows = [score_question(q) for q in data]
    scored = [r for r in rows if r["has_evidence"]]
    excluded = [r["question_id"] for r in rows if not r["has_evidence"]]

    def recall(sub: list[dict]) -> float | None:
        return round(sum(r["hit"] for r in sub) / len(sub), 4) if sub else None

    by_bucket = defaultdict(list)
    by_type = defaultdict(list)
    for r in scored:
        by_bucket[r["bucket"]].append(r)
        by_type[r["question_type"]].append(r)
    return {
        "file": path.name,
        "n_questions": len(rows),
        "n_scored": len(scored),
        "excluded_no_evidence": excluded,
        "buckets": {b: {"n": len(v), "recall_at_5": recall(v)} for b, v in sorted(by_bucket.items())},
        "by_question_type": {t: {"n": len(v), "recall_at_5": recall(v)} for t, v in sorted(by_type.items())},
        "aggregate_recall_at_5": recall(scored),
        "p95_latency_ms": round(_p95([r["latency_ms"] for r in scored]), 3),
        "median_sessions_per_question": statistics.median(r["n_sessions"] for r in rows) if rows else None,
        "per_question": [{k: r[k] for k in ("question_id", "question_type", "bucket", "hit", "latency_ms")} for r in rows],
    }


def verdict_for(primary: dict, control: dict | None, lock: dict, dataset_ok: bool) -> str:
    if not dataset_ok:
        return "VOID: primary dataset missing or sha256 mismatch"
    verb = primary["buckets"].get("verbatim", {"n": 0, "recall_at_5": None})
    if verb["n"] < 50:
        return f"VOID: verbatim bucket has {verb['n']} questions (< 50)"
    if control is not None and (control["aggregate_recall_at_5"] or 0) < 0.80:
        return f"VOID: control (oracle) recall@5 {control['aggregate_recall_at_5']} < 0.80 — instrument broken"
    r, p95 = verb["recall_at_5"], primary["p95_latency_ms"]
    if r >= 0.70 and p95 < 25.0:
        return f"ACCEPT: verbatim recall@5 {r:.3f} >= 0.70 and p95 {p95:.1f} ms < 25 ms"
    return f"REJECT: verbatim recall@5 {r:.3f} (gate >= 0.70), p95 {p95:.1f} ms (gate < 25 ms)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=None, help="score only the first N questions (smoke)")
    ap.add_argument("--skip-control", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)

    lock = load_lock(LOCK_PATH, KNOWN_LOCK_SHA256)
    ds = lock["dataset"]
    primary_path = DATA / ds["primary_file"]
    dataset_ok = primary_path.exists() and _file_sha256(primary_path) == ds["primary_sha256"]
    try:
        kaos_version = version("kaos-harness")
    except PackageNotFoundError:
        kaos_version = "unknown"

    primary = run_file(primary_path, args.limit) if dataset_ok else None
    control = None
    control_path = DATA / ds["control_file"]
    if not args.skip_control and control_path.exists():
        control = run_file(control_path, args.limit)

    verdict = verdict_for(primary, control, lock, dataset_ok) if primary else \
        "VOID: primary dataset missing or sha256 mismatch"

    result = {
        "bench": "longmemeval",
        "kaos_version": kaos_version,
        "lock_sha256": sha256_file(LOCK_PATH),
        "dataset_sha256_verified": dataset_ok,
        "limit": args.limit,
        "primary": primary,
        "control_oracle": ({k: v for k, v in control.items() if k != "per_question"} if control else None),
        "verdict": verdict,
    }
    out = Path(args.out) if args.out else RESULTS_DIR / f"kaos_v{kaos_version}{'_smoke' if args.limit else ''}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")

    print(f"LongMemEval · kaos-harness {kaos_version} · {ds['primary_file']} sha ok={dataset_ok}")
    if primary:
        for b, v in primary["buckets"].items():
            print(f"  {b:<10} n={v['n']:<4} recall@5={v['recall_at_5']}")
        for t, v in primary["by_question_type"].items():
            print(f"  {t:<28} n={v['n']:<4} recall@5={v['recall_at_5']}")
        print(f"  aggregate (not comparable to embedding systems): {primary['aggregate_recall_at_5']}")
        print(f"  p95 search latency: {primary['p95_latency_ms']} ms · excluded(no evidence): {len(primary['excluded_no_evidence'])}")
    if control:
        print(f"  control oracle recall@5: {control['aggregate_recall_at_5']} (n={control['n_scored']})")
    print(f"  verdict: {verdict}")
    print(f"  results: {out}")
    return 0 if verdict.startswith("ACCEPT") else 2


if __name__ == "__main__":
    sys.exit(main())
