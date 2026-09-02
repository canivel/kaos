"""Paraphrase Recall Gap (PRG) bench.

Measures how often KAOS's FTS5 memory misses a paraphrased query whose stored
lesson exists (issue #42), with a verbatim control proving the instrument works.
Pre-registered in ``preregistration.json``; the runner refuses to run on a lock
whose sha256 is not in ``KNOWN_LOCK_SHA256``.

    uv run python benchmarks/prg/run_prg.py
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from kaos import Kaos
from kaos.eval.harness import load_lock
from kaos.memory import MemoryStore

HERE = Path(__file__).parent
LOCK_PATH = HERE / "preregistration.json"
PAIRS_PATH = HERE / "pairs.json"
RESULTS_DIR = HERE / "results"

# Pre-registered lock hashes — the runner refuses any other lock file.
KNOWN_LOCK_SHA256: dict[str, str] = {
    "42011e768a44dda2961d34d7b0b4d7c5a3b776830a2f96e01eb8b25045df3430": "v1-pre-registration",
}

STOPWORDS = frozenset(
    "a an the of on in to for by with and or is are was were be from at as it "
    "its this that when after before into over under not no".split()
)
TOP_K = 5
RANK_MODES = ("bm25", "weighted")
QUERY_MODES = ("and", "or")


def sanitize(text: str, mode: str) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]
    seen: list[str] = []
    for t in toks:
        if t not in seen:
            seen.append(t)
    return (" " if mode == "and" else " OR ").join(seen)


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    if len(xs) == 1:
        return xs[0]
    return statistics.quantiles(xs, n=20)[-1]


def run(pairs: list[dict], top_k: int = TOP_K) -> dict[str, dict]:
    """Run every (query kind, query mode, rank mode) condition on a fresh db."""
    kaos = Kaos(":memory:")
    agent = kaos.spawn("prg-writer")
    mem = MemoryStore(kaos.conn)
    for p in pairs:
        mem.write(agent, p["stored_phrase"], type="insight", key=f"prg-{p['id']}")

    conditions: dict[str, dict] = {}
    for qkind in ("paraphrase", "verbatim"):
        for qmode in QUERY_MODES:
            for rank in RANK_MODES:
                missed: list[int] = []
                latencies: list[float] = []
                for p in pairs:
                    text = p["paraphrase_query"] if qkind == "paraphrase" else p["stored_phrase"]
                    q = sanitize(text, qmode)
                    t0 = time.perf_counter()
                    try:
                        hits = mem.search(q, limit=top_k, rank=rank) if q else []
                    except Exception:  # malformed MATCH counts as a miss
                        hits = []
                    latencies.append((time.perf_counter() - t0) * 1000.0)
                    if not any(h.key == f"prg-{p['id']}" for h in hits):
                        missed.append(p["id"])
                conditions[f"{qkind}/{qmode}/{rank}"] = {
                    "n": len(pairs),
                    "misses": len(missed),
                    "miss_rate": round(len(missed) / len(pairs), 4) if pairs else None,
                    "p95_ms": round(_p95(latencies), 3),
                    "missed_ids": missed,
                }
    try:
        kaos.conn.close()
    except Exception:
        pass
    return conditions


def verdict_for(n_pairs: int, conditions: dict[str, dict], lock: dict) -> str:
    control = conditions["verbatim/and/bm25"]["miss_rate"]
    if n_pairs < lock["n_pairs_required"]:
        return f"VOID: only {n_pairs} pairs (< {lock['n_pairs_required']})"
    if control is None or control > 0.10:
        return f"VOID: control miss_rate {control} > 0.10 — instrument broken"
    return "ACCEPT: measurement stands (PRG is an instrument; see lock for meaning)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pairs", default=str(PAIRS_PATH))
    ap.add_argument("--out", default=None, help="results json path")
    args = ap.parse_args(argv)

    lock = load_lock(LOCK_PATH, KNOWN_LOCK_SHA256)  # raises LockTamperError
    pairs = json.loads(Path(args.pairs).read_text())["pairs"]
    conditions = run(pairs)
    verdict = verdict_for(len(pairs), conditions, lock)

    try:
        kaos_version = version("kaos-harness")
    except PackageNotFoundError:
        kaos_version = "unknown"
    from kaos.eval.harness import sha256_file

    result = {
        "bench": "prg",
        "pairs_version": json.loads(Path(args.pairs).read_text())["version"],
        "kaos_version": kaos_version,
        "lock_sha256": sha256_file(LOCK_PATH),
        "n_pairs": len(pairs),
        "headline": "paraphrase/and/bm25",
        "control": "verbatim/and/bm25",
        "conditions": conditions,
        "verdict": verdict,
    }
    out = Path(args.out) if args.out else RESULTS_DIR / f"kaos_v{kaos_version}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n")

    h = conditions["paraphrase/and/bm25"]
    c = conditions["verbatim/and/bm25"]
    print(f"PRG v1 · {len(pairs)} pairs · kaos-harness {kaos_version}")
    print(f"  headline paraphrase/and/bm25 miss rate : {h['miss_rate']:.0%}  ({h['misses']}/{h['n']})")
    print(f"  control  verbatim/and/bm25   miss rate : {c['miss_rate']:.0%}  ({c['misses']}/{c['n']})")
    for k, v in conditions.items():
        print(f"  {k:<26} miss {v['miss_rate']:.2f}  p95 {v['p95_ms']:.2f} ms")
    print(f"  verdict: {verdict}")
    print(f"  results: {out}")
    return 0 if verdict.startswith("ACCEPT") else 2


if __name__ == "__main__":
    sys.exit(main())
