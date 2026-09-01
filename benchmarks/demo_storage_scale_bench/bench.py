"""demo_storage_scale_bench — does the single kaos.db saturate?

The v0.10 scoping panel parked the per-agent-DB / Data-Vault sharding idea
behind ONE prerequisite: measure whether the single-file architecture
actually saturates before proposing to shard it. This is that measurement.
It is infrastructure, not a mechanism — no ISA lock, no ACCEPT/REJECT. The
deliverable is the saturation curve + an honest read on the premise.

What it measures, per scale (N agents populated):
  - populate throughput (agents/s, with realistic per-agent density:
    VFS files + memory entries + tool_calls + events)
  - concurrent mixed-workload op latency (p50/p95/p99) from K threads:
      * vfs_write, vfs_read
      * memory_search   <- THE metric: cross-agent FTS5 recall latency
      * checkpoint
  - SQLITE_BUSY / lock-error rate under contention
  - on-disk size: kaos.db + -wal growth

Pragma sweep: synchronous={FULL,NORMAL} x wal_autocheckpoint={100,1000,4000}.
The current code hardcodes wal_autocheckpoint=100 and never sets synchronous
(core.py) — both unmeasured guesses.

Run:
    uv run python -m demo_storage_scale_bench.bench --scales 1000,10000 --threads 8
    uv run python -m demo_storage_scale_bench.bench --scales 1000 --sweep

The panel's informal sanity line: cross-agent memory_search p95 < 500 ms at
10k agents. Above it, the single-DB premise is under real pressure; below it,
sharding would be optimizing a bottleneck that does not exist yet.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
import threading
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from kaos import Kaos  # noqa: E402
from kaos.memory import MemoryStore  # noqa: E402


# Deterministic-ish corpus so FTS has real terms to match.
_WORDS = (
    "retrieval augmentation planner verifier harness pareto frontier "
    "checkpoint restore blob journal isolation neuroplasticity hebbian "
    "consolidation dream skill memory shared log intent vote decide "
    "proposer stagnation pivot compaction surrogate taxonomy localizer "
    "quorum ideal state criteria federation vault signature capability"
).split()


def _sentence(rng: random.Random, n: int = 12) -> str:
    return " ".join(rng.choice(_WORDS) for _ in range(n))


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    idx = min(len(s) - 1, int(p * (len(s) - 1)))
    return s[idx]


def populate(db_path: str, n_agents: int, *, files_per=3, mems_per=5,
             tools_per=4, seed=7, fast=True) -> dict:
    """Create N agents each with realistic density.

    Seeding is NOT the thing under measurement — the concurrent op latency is.
    So the seeder uses batched executemany + periodic commits at
    synchronous=NORMAL to reach 10k agents in reasonable wall time, producing
    the SAME table/FTS state the per-op API would (memory_fts stays synced via
    its INSERT trigger). The measurement phase (measure()) uses the real Kaos
    API unchanged. `fast=False` falls back to the honest per-op API path (used
    to sanity-check that the batched seeder produces equivalent state).
    """
    import hashlib
    import sqlite3

    import ulid

    rng = random.Random(seed)
    # Ensure schema exists via a normal Kaos open, then seed on a raw conn.
    Kaos(db_path=db_path).close()

    t0 = time.perf_counter()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")  # seeding durability is irrelevant

    agent_ids: list[str] = []
    if not fast:
        k = Kaos(db_path=db_path)
        mem = MemoryStore(k.conn)
        for i in range(n_agents):
            aid = k.spawn(f"agent-{i}")
            agent_ids.append(aid)
            for f in range(files_per):
                k.write(aid, f"/work/file_{f}.txt", _sentence(rng, 20).encode())
            for _ in range(mems_per):
                mem.write(aid, _sentence(rng, 14),
                          type=rng.choice(("observation", "result", "insight")))
            for t in range(tools_per):
                k.log_tool_call(aid, "search", {"q": _sentence(rng, 4)})
        k.close()
    else:
        batch = 500
        agents_rows, file_rows, blob_rows, mem_rows, tc_rows = [], [], [], [], []

        def _flush():
            conn.executemany(
                "INSERT INTO agents (agent_id, name, config, metadata) VALUES (?,?,?,'{}')",
                agents_rows)
            conn.executemany(
                "INSERT OR IGNORE INTO blobs (content_hash, content, compressed, ref_count) "
                "VALUES (?,?,0,1)", blob_rows)
            conn.executemany(
                "INSERT INTO files (agent_id, path, content_hash, size, version, is_dir) "
                "VALUES (?,?,?,?,1,0)", file_rows)
            conn.executemany(
                "INSERT INTO memory (agent_id, type, key, content, metadata) "
                "VALUES (?,?,?,?,'{}')", mem_rows)
            conn.executemany(
                "INSERT INTO tool_calls (call_id, agent_id, tool_name, input, status) "
                "VALUES (?,?,?,?,'pending')", tc_rows)
            conn.commit()
            agents_rows.clear(); file_rows.clear(); blob_rows.clear()
            mem_rows.clear(); tc_rows.clear()

        for i in range(n_agents):
            aid = str(ulid.new())
            agent_ids.append(aid)
            agents_rows.append((aid, f"agent-{i}", "{}"))
            for f in range(files_per):
                content = _sentence(rng, 20).encode()
                h = hashlib.sha256(content).hexdigest()
                blob_rows.append((h, content))
                file_rows.append((aid, f"/work/file_{f}.txt", h, len(content)))
            for _ in range(mems_per):
                mem_rows.append((aid, rng.choice(("observation", "result", "insight")),
                                 None, _sentence(rng, 14)))
            for _ in range(tools_per):
                tc_rows.append((str(ulid.new()), aid, "search",
                                json.dumps({"q": _sentence(rng, 4)})))
            if (i + 1) % batch == 0:
                _flush()
        _flush()

    conn.close()
    dt = time.perf_counter() - t0
    return {
        "n_agents": n_agents,
        "populate_seconds": round(dt, 2),
        "agents_per_sec": round(n_agents / dt, 1) if dt else None,
        "agent_ids": agent_ids,
    }


def measure(db_path: str, agent_ids: list[str], *, threads: int,
            ops_per_thread: int, seed=11, kaos_kwargs: dict | None = None) -> dict:
    """Concurrent mixed workload. Each thread opens its OWN Kaos (own
    connection) — this is the real multi-agent contention pattern.

    kaos_kwargs (synchronous, wal_autocheckpoint) are applied to EVERY
    measurement connection — this is what makes the pragma sweep real, since
    synchronous/wal_autocheckpoint are per-connection pragmas."""
    kaos_kwargs = kaos_kwargs or {}
    lat: dict[str, list[float]] = {
        "vfs_write": [], "vfs_read": [], "memory_search": [], "checkpoint": []
    }
    lock_errors = [0]
    lat_lock = threading.Lock()

    def worker(tid: int):
        rng = random.Random(seed + tid)
        k = Kaos(db_path=db_path, **kaos_kwargs)
        mem = MemoryStore(k.conn)
        local: dict[str, list[float]] = {op: [] for op in lat}
        local_lockerr = 0
        for _ in range(ops_per_thread):
            aid = rng.choice(agent_ids)
            op = rng.choices(
                ("vfs_write", "vfs_read", "memory_search", "checkpoint"),
                weights=(30, 30, 35, 5),
            )[0]
            t0 = time.perf_counter()
            try:
                if op == "vfs_write":
                    k.write(aid, f"/work/file_{rng.randint(0, 2)}.txt",
                            _sentence(rng, 20).encode())
                elif op == "vfs_read":
                    try:
                        k.read(aid, f"/work/file_{rng.randint(0, 2)}.txt")
                    except FileNotFoundError:
                        continue
                elif op == "memory_search":
                    mem.search(_sentence(rng, 3), limit=10)
                elif op == "checkpoint":
                    k.checkpoint(aid, label="bench")
            except Exception as e:  # noqa: BLE001
                if "locked" in str(e).lower() or "busy" in str(e).lower():
                    local_lockerr += 1
                    continue
                raise
            local[op].append((time.perf_counter() - t0) * 1000.0)
        with lat_lock:
            for op in lat:
                lat[op].extend(local[op])
            lock_errors[0] += local_lockerr
        k.close()

    t0 = time.perf_counter()
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    wall = time.perf_counter() - t0

    total_ops = sum(len(v) for v in lat.values())
    return {
        "threads": threads,
        "ops_per_thread": ops_per_thread,
        "total_ops": total_ops,
        "wall_seconds": round(wall, 2),
        "throughput_ops_per_sec": round(total_ops / wall, 1) if wall else None,
        "lock_errors": lock_errors[0],
        "latency_ms": {
            op: {
                "n": len(v),
                "p50": round(_pct(v, 0.50), 3),
                "p95": round(_pct(v, 0.95), 3),
                "p99": round(_pct(v, 0.99), 3),
                "max": round(max(v), 3) if v else 0.0,
            }
            for op, v in lat.items()
        },
    }


def _disk(db_path: str) -> dict:
    def _sz(p):
        return os.path.getsize(p) if os.path.exists(p) else 0
    return {
        "db_bytes": _sz(db_path),
        "wal_bytes": _sz(db_path + "-wal"),
        "shm_bytes": _sz(db_path + "-shm"),
        "db_mb": round(_sz(db_path) / 1e6, 1),
    }


def run_scale(out_dir: Path, scale: int, *, threads: int, ops_per_thread: int,
              pragmas: dict | None = None) -> dict:
    db_path = str(out_dir / f"scale_{scale}.db")
    for suffix in ("", "-wal", "-shm"):
        p = db_path + suffix
        if os.path.exists(p):
            os.remove(p)

    pop = populate(db_path, scale)
    disk_after_populate = _disk(db_path)
    kaos_kwargs = {}
    if pragmas:
        kaos_kwargs = {
            "synchronous": pragmas.get("synchronous", "FULL"),
            "wal_autocheckpoint": pragmas.get("wal_autocheckpoint", 100),
        }
    meas = measure(db_path, pop["agent_ids"], threads=threads,
                   ops_per_thread=ops_per_thread, kaos_kwargs=kaos_kwargs)
    disk_after_measure = _disk(db_path)
    pop.pop("agent_ids", None)  # don't serialize thousands of ids
    return {
        "scale": scale,
        "pragmas": pragmas or {"synchronous": "default", "wal_autocheckpoint": 100},
        "populate": pop,
        "measure": meas,
        "disk_after_populate": disk_after_populate,
        "disk_after_measure": disk_after_measure,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scales", default="1000",
                    help="comma-separated agent counts, e.g. 1000,10000")
    ap.add_argument("--threads", type=int, default=8)
    ap.add_argument("--ops-per-thread", type=int, default=500)
    ap.add_argument("--sweep", action="store_true",
                    help="sweep synchronous x wal_autocheckpoint at each scale")
    ap.add_argument("--out-dir", default="demo_storage_scale_bench")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    scales = [int(s) for s in args.scales.split(",")]

    pragma_sets = [None]
    if args.sweep:
        pragma_sets = [
            {"synchronous": "FULL", "wal_autocheckpoint": 100},
            {"synchronous": "NORMAL", "wal_autocheckpoint": 1000},
            {"synchronous": "NORMAL", "wal_autocheckpoint": 4000},
        ]

    results = []
    for scale in scales:
        for pragmas in pragma_sets:
            tag = "default" if not pragmas else \
                f"{pragmas['synchronous']}/wal{pragmas['wal_autocheckpoint']}"
            print(f"[run] scale={scale} threads={args.threads} pragmas={tag} ...",
                  flush=True)
            r = run_scale(out, scale, threads=args.threads,
                          ops_per_thread=args.ops_per_thread, pragmas=pragmas)
            ms = r["measure"]["latency_ms"]["memory_search"]
            print(f"      populate={r['populate']['agents_per_sec']} ag/s  "
                  f"db={r['disk_after_measure']['db_mb']}MB  "
                  f"mem_search p95={ms['p95']}ms p99={ms['p99']}ms  "
                  f"lock_err={r['measure']['lock_errors']}", flush=True)
            results.append(r)

    (out / "results.json").write_text(json.dumps(results, indent=2))
    print(f"[done] wrote {out / 'results.json'} ({len(results)} runs)")


if __name__ == "__main__":
    main()
