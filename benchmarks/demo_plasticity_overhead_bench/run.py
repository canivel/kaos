"""Microbenchmark the inline plasticity hook overhead.

Each measured op is run N times twice — once with KAOS_DREAM_AUTO=1 (the
default; hooks fire), once with KAOS_DREAM_AUTO=0 (hooks disabled). The
difference is the true cost of the plasticity mechanism.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from statistics import median

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

# Don't trigger threshold consolidation during the bench — we're measuring
# the inline hook cost, not the periodic pass.
os.environ["KAOS_DREAM_THRESHOLD"] = "1000000"
os.environ["KAOS_SYSTEMIC_THRESHOLD"] = "1000000"

from kaos import Kaos  # noqa: E402
from kaos.memory import MemoryStore  # noqa: E402
from kaos.skills import SkillStore  # noqa: E402

# The dominant cost per op is SQLite's COMMIT fsync (~30 ms on Windows,
# ~1 ms on Linux with fast SSD). 200 ops is enough to see statistical
# significance while keeping wall-clock tolerable on slow-fsync hosts.
N_OPS = 200
N_SEED_SKILLS = 100
N_SEED_MEMORIES = 50

# Budget accepts the fsync floor — what we measure is the OVERHEAD ON TOP
# of it. Anything under 2 ms of extra work per op is fine.
LATENCY_BUDGET_OVERHEAD_MS = 2.0


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = min(len(s) - 1, int(len(s) * p))
    return s[idx]


def _seed_library(db_path: Path) -> tuple[Kaos, list[int], list[int]]:
    # Use a unique DB per call to avoid Windows file-lock issues if a prior
    # bench run is still holding a connection open.
    import tempfile
    db_file = Path(tempfile.mkstemp(suffix=".db", prefix="overhead-bench-")[1])
    kaos = Kaos(db_path=str(db_file))
    seed_agent = kaos.spawn("seed")
    sk = SkillStore(kaos.conn)
    mem = MemoryStore(kaos.conn)
    skill_ids = []
    for i in range(N_SEED_SKILLS):
        sid = sk.save(name=f"skill-{i:03d}",
                      description=f"stub description number {i}",
                      template=f"do thing {i}",
                      source_agent_id=seed_agent,
                      tags=["bench"])
        skill_ids.append(sid)
    memory_ids = []
    for i in range(N_SEED_MEMORIES):
        mid = mem.write(agent_id=seed_agent,
                        content=f"some memory snippet number {i} about things",
                        type="observation",
                        key=f"snippet-{i:03d}")
        memory_ids.append(mid)
    return kaos, skill_ids, memory_ids


def _time_op(fn, *args, n_ops: int = N_OPS) -> list[float]:
    """Return per-op latencies in microseconds."""
    timings: list[float] = []
    for _ in range(n_ops):
        t0 = time.perf_counter()
        fn(*args)
        timings.append((time.perf_counter() - t0) * 1e6)
    return timings


def bench_record_outcome(auto_mode: str) -> dict[str, float]:
    os.environ["KAOS_DREAM_AUTO"] = auto_mode
    kaos, skill_ids, _ = _seed_library(HERE / f"bench-skill-{auto_mode}.db")
    sk = SkillStore(kaos.conn)
    runner = kaos.spawn("bench-runner")

    def _do(i):
        sid = skill_ids[i % len(skill_ids)]
        sk.record_outcome(sid, success=(i % 2 == 0), agent_id=runner)

    timings = [_time_op(_do, i, n_ops=1)[0] for i in range(N_OPS)]
    kaos.close()
    return {
        "p50_us": median(timings),
        "p95_us": percentile(timings, 0.95),
        "p99_us": percentile(timings, 0.99),
        "max_us": max(timings),
    }


def bench_memory_search(auto_mode: str) -> dict[str, float]:
    os.environ["KAOS_DREAM_AUTO"] = auto_mode
    kaos, _, _ = _seed_library(HERE / f"bench-memory-{auto_mode}.db")
    mem = MemoryStore(kaos.conn)
    runner = kaos.spawn("bench-runner")

    def _do(i):
        mem.search(f"number {i % N_SEED_MEMORIES}", limit=5,
                   record_hits=True, requesting_agent_id=runner)

    timings = [_time_op(_do, i, n_ops=1)[0] for i in range(N_OPS)]
    kaos.close()
    return {
        "p50_us": median(timings),
        "p95_us": percentile(timings, 0.95),
        "p99_us": percentile(timings, 0.99),
        "max_us": max(timings),
    }


def bench_agent_complete(auto_mode: str) -> dict[str, float]:
    """One-off; each op spawns then completes a fresh agent."""
    os.environ["KAOS_DREAM_AUTO"] = auto_mode
    kaos, _, _ = _seed_library(HERE / f"bench-complete-{auto_mode}.db")

    # Pre-spawn agents to exclude spawn cost from the timing
    agent_ids = [kaos.spawn(f"ag-{i}") for i in range(N_OPS)]

    timings: list[float] = []
    for aid in agent_ids:
        t0 = time.perf_counter()
        kaos.complete(aid)
        timings.append((time.perf_counter() - t0) * 1e6)

    kaos.close()
    return {
        "p50_us": median(timings),
        "p95_us": percentile(timings, 0.95),
        "p99_us": percentile(timings, 0.99),
        "max_us": max(timings),
    }


def _format_us(us: float) -> str:
    if us >= 1000:
        return f"{us / 1000:.2f} ms"
    return f"{us:.1f} µs"


def _delta(on: dict[str, float], off: dict[str, float]) -> dict[str, float]:
    return {k: on[k] - off[k] for k in on}


def main() -> int:
    print("=" * 72)
    print(f"Plasticity hook overhead benchmark — {N_OPS} ops per measurement")
    print(f"Seeded: {N_SEED_SKILLS} skills, {N_SEED_MEMORIES} memory entries")
    print(f"Overhead budget: p50 < {LATENCY_BUDGET_OVERHEAD_MS:.1f} ms, "
          f"p99 < {LATENCY_BUDGET_OVERHEAD_MS * 10:.1f} ms")
    print("(Overhead = auto=ON minus auto=OFF. The auto=OFF baseline is "
          "SQLite commit+fsync; we measure what plasticity ADDS on top.)")
    print("=" * 72)

    results = {}
    for label, fn in [
        ("record_outcome", bench_record_outcome),
        ("memory_search",  bench_memory_search),
        ("agent_complete", bench_agent_complete),
    ]:
        print(f"\n[bench] {label}")
        on = fn("1")
        off = fn("0")
        diff = _delta(on, off)
        results[label] = {"auto_on": on, "auto_off": off, "delta": diff}
        print(f"   auto=ON   p50={_format_us(on['p50_us'])}  "
              f"p95={_format_us(on['p95_us'])}  "
              f"p99={_format_us(on['p99_us'])}  "
              f"max={_format_us(on['max_us'])}")
        print(f"   auto=OFF  p50={_format_us(off['p50_us'])}  "
              f"p95={_format_us(off['p95_us'])}  "
              f"p99={_format_us(off['p99_us'])}  "
              f"max={_format_us(off['max_us'])}")
        print(f"   overhead  p50={_format_us(diff['p50_us'])}  "
              f"p99={_format_us(diff['p99_us'])}")

    print("\n" + "=" * 72)
    print("Verdict")
    print("=" * 72)

    # Budget check: what plasticity ADDS on top of the baseline (auto=OFF).
    # The baseline is whatever the SQLite commit costs on this host — not
    # our problem to optimise. We only gate on the DELTA. p99 budget is 10×
    # the p50 budget to absorb filesystem noise on Windows without marking
    # the run as a regression for tail spikes.
    budget_us = LATENCY_BUDGET_OVERHEAD_MS * 1000
    budget_p99_us = LATENCY_BUDGET_OVERHEAD_MS * 10 * 1000
    ok = True
    for label, r in results.items():
        delta_p50 = r["delta"]["p50_us"]
        delta_p99 = r["delta"]["p99_us"]
        # Negative delta = hook made it faster (filesystem cache variance);
        # still counts as "not over budget".
        p50_ok = delta_p50 < budget_us
        p99_ok = delta_p99 < budget_p99_us
        verdict = "OK" if (p50_ok and p99_ok) else "OVER BUDGET"
        print(f"  {label:<16}  "
              f"overhead p50={_format_us(delta_p50)} "
              f"({'ok' if p50_ok else 'OVER'}), "
              f"p99={_format_us(delta_p99)} "
              f"({'ok' if p99_ok else 'OVER'})  [{verdict}]")
        if not (p50_ok and p99_ok):
            ok = False

    (HERE / "results.json").write_text(
        json.dumps({
            "config": {
                "n_ops": N_OPS,
                "n_seed_skills": N_SEED_SKILLS,
                "n_seed_memories": N_SEED_MEMORIES,
                "overhead_budget_ms": LATENCY_BUDGET_OVERHEAD_MS,
            },
            "results": results,
            "verdict": "ok" if ok else "over_budget",
        }, indent=2),
        encoding="utf-8",
    )

    md = ["# Plasticity hook overhead — measured\n",
          f"Config: {N_OPS} ops, seeded with {N_SEED_SKILLS} skills + "
          f"{N_SEED_MEMORIES} memories.\n",
          f"Overhead budget: **p50 < {LATENCY_BUDGET_OVERHEAD_MS:.1f} ms**, "
          f"p99 < {LATENCY_BUDGET_OVERHEAD_MS * 10:.1f} ms (10× the p50 budget "
          "to absorb filesystem fsync noise).",
          "Overhead = auto=ON minus auto=OFF baseline. The baseline is the "
          "intrinsic SQLite commit+fsync cost on this host, not our problem "
          "to optimise.\n",
          "",
          "## Per-op timings (median / p99, auto ON vs OFF)",
          "",
          "| Op | p50 auto=ON | p99 auto=ON | p50 auto=OFF | p99 auto=OFF | Overhead p50 | Overhead p99 |",
          "|---|---:|---:|---:|---:|---:|---:|"]
    for label, r in results.items():
        on, off, diff = r["auto_on"], r["auto_off"], r["delta"]
        md.append(
            f"| `{label}` | {_format_us(on['p50_us'])} | {_format_us(on['p99_us'])} | "
            f"{_format_us(off['p50_us'])} | {_format_us(off['p99_us'])} | "
            f"{_format_us(diff['p50_us'])} | {_format_us(diff['p99_us'])} |"
        )
    md.append("")
    md.append(f"**Verdict:** {'OK — within budget.' if ok else 'OVER BUDGET.'}")
    (HERE / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
