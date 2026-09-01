"""Consolidation-phase-at-scale benchmark.

Measures the wall-clock cost of running a full dream consolidation pass
over databases seeded with increasing numbers of skills, memories, and
skill uses. Addresses whitepaper §6.1: we never characterised how the
phase scales past a few dozen skills. This benchmark reports p50 / p95
latencies for {100, 1000, 10000}-skill libraries.

Reproducible. No external services. Each scale runs consolidation three
times and reports the median + max across repeats.
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

os.environ["KAOS_DREAM_THRESHOLD"] = "100000000"

from kaos import Kaos  # noqa: E402
from kaos.skills import SkillStore  # noqa: E402
from kaos.memory import MemoryStore  # noqa: E402
from kaos.dream.phases.consolidation import run as run_consolidation  # noqa: E402


SCALES = [100, 1000, 10000]
REPEATS = 3


def _seed_database(n_skills: int, db_path: Path, *, seed: int = 42) -> None:
    if db_path.exists():
        db_path.unlink()
    kaos = Kaos(db_path=str(db_path))
    try:
        sk = SkillStore(kaos.conn)
        mem = MemoryStore(kaos.conn)
        # One agent that owns everything is fine — the consolidation phase
        # iterates over skills globally.
        owner = kaos.spawn("owner")
        rng = random.Random(seed)

        # Build a vocabulary so descriptions share tokens, giving the Jaccard
        # merge detector something to see at scale.
        VOCAB = [
            "load", "save", "transform", "index", "scan", "emit", "ingest",
            "sync", "check", "retry", "validate", "deduplicate", "parse",
            "render", "compile", "encrypt", "hash", "mirror", "mutate",
            "notify", "rotate", "expire", "prune", "shard", "replicate",
            "snapshot", "restore", "classify", "extract", "embed",
            "schedule", "dispatch", "drain", "buffer", "throttle",
            "segment", "merge", "split", "enqueue", "dequeue",
        ]
        DOMAINS = [
            "postgres", "redis", "sqs", "kafka", "s3", "dynamodb", "http",
            "grpc", "kubernetes", "docker", "csv", "json", "parquet", "xml",
            "spark", "dbt", "airflow",
        ]

        for i in range(n_skills):
            verb = rng.choice(VOCAB)
            domain = rng.choice(DOMAINS)
            name = f"{verb}-{domain}-{i}"
            desc_tokens = rng.sample(VOCAB, k=rng.randint(3, 6)) + [domain]
            sk.save(
                name=name,
                description=" ".join(desc_tokens),
                template=f"Run {verb} against {domain}",
                source_agent_id=owner,
                tags=[verb, domain],
            )

        # Add ~5% memories so promotion logic has work to do too.
        n_mem = max(5, n_skills // 20)
        for i in range(n_mem):
            mid = mem.write(agent_id=owner, content=f"note {i}",
                            type="insight", key=f"hot-{i}")
            # Half the memories get enough hits to qualify for promotion
            if i % 2 == 0:
                for _ in range(5):
                    kaos.conn.execute(
                        "INSERT INTO memory_hits (memory_id, agent_id, "
                        "query, rank_pos) VALUES (?, ?, ?, 1)",
                        (mid, owner, f"hot-{i}"),
                    )

        # Add some skill_uses so prune/weights phases have telemetry.
        skill_ids = [r[0] for r in kaos.conn.execute(
            "SELECT skill_id FROM agent_skills"
        ).fetchall()]
        uses_per_skill = 5
        rows = []
        for sid in skill_ids:
            for _ in range(uses_per_skill):
                rows.append((sid, owner, rng.choice([0, 1])))
        kaos.conn.executemany(
            "INSERT INTO skill_uses (skill_id, agent_id, success) "
            "VALUES (?, ?, ?)",
            rows,
        )
        kaos.conn.commit()
    finally:
        kaos.close()


def _time_consolidation(db_path: Path) -> float:
    """Open, run consolidation once, close; return wall time in seconds."""
    kaos = Kaos(db_path=str(db_path))
    try:
        t0 = time.perf_counter()
        run_consolidation(kaos.conn, dry_run=True)
        return time.perf_counter() - t0
    finally:
        kaos.close()


def _summarise(durations: list[float]) -> dict:
    durations = sorted(durations)
    p50 = durations[len(durations) // 2]
    pmax = durations[-1]
    pmin = durations[0]
    return {"p50_ms": round(p50 * 1000, 2),
            "max_ms": round(pmax * 1000, 2),
            "min_ms": round(pmin * 1000, 2),
            "samples": len(durations)}


def main() -> int:
    print("=" * 70)
    print(f"Consolidation-at-scale benchmark ({REPEATS} repeats per scale)")
    print("=" * 70)

    all_results = []
    for n in SCALES:
        db = HERE / f"bench-scale-{n}.db"
        print(f"\n[{n} skills] seeding...", end=" ", flush=True)
        seed_t0 = time.perf_counter()
        _seed_database(n, db)
        seed_elapsed = time.perf_counter() - seed_t0
        print(f"seeded in {seed_elapsed:.1f}s")

        runs = []
        for rep in range(REPEATS):
            t = _time_consolidation(db)
            runs.append(t)
            print(f"  run {rep + 1}/{REPEATS}: {t * 1000:.1f} ms")

        stats = _summarise(runs)
        stats["n_skills"] = n
        stats["seed_seconds"] = round(seed_elapsed, 2)
        all_results.append(stats)
        print(f"  p50: {stats['p50_ms']} ms   max: {stats['max_ms']} ms")

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  {'n_skills':>10}  {'p50 ms':>10}  {'max ms':>10}")
    for r in all_results:
        print(f"  {r['n_skills']:>10}  {r['p50_ms']:>10.1f}  "
              f"{r['max_ms']:>10.1f}")

    # Complexity check: a well-behaved consolidation should scale ~linearly
    # or sub-quadratically. Report the effective growth exponent between
    # adjacent scales.
    print("\n  Effective growth exponent p50(n2) / p50(n1) vs n2 / n1:")
    for i in range(1, len(all_results)):
        prev, cur = all_results[i - 1], all_results[i]
        if prev["p50_ms"] > 0:
            ratio = cur["p50_ms"] / prev["p50_ms"]
            scale_ratio = cur["n_skills"] / prev["n_skills"]
            # effective exponent: ratio = scale_ratio ** exp
            import math
            exp = (math.log(ratio) / math.log(scale_ratio)
                   if scale_ratio > 1 and ratio > 0 else float("nan"))
            print(f"  {prev['n_skills']:>6} -> {cur['n_skills']:>6}: "
                  f"time ×{ratio:.2f} for {scale_ratio:.0f}× skills "
                  f"(exponent ~{exp:.2f})")

    out = {"scales": all_results, "repeats_per_scale": REPEATS}
    (HERE / "results.json").write_text(json.dumps(out, indent=2),
                                       encoding="utf-8")

    md = [
        "# Consolidation-at-scale benchmark\n",
        f"{REPEATS} repeats per scale. Dry-run mode (no side effects).\n",
        "| n skills | p50 (ms) | max (ms) |",
        "|---:|---:|---:|",
    ]
    for r in all_results:
        md.append(f"| {r['n_skills']} | {r['p50_ms']} | {r['max_ms']} |")
    md.append("")
    md.append("Raw JSON: [results.json](results.json)")
    (HERE / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
