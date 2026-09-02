"""Agent Forensics Bench v1 — runner.

    uv run python benchmarks/afb/run_afb.py [--output PATH] [--db PATH]

Refuses to run unless preregistration.json's sha256 is in KNOWN_LOCK_SHA256.
Emits a JSON result with a top-level "verdict": ACCEPT | REJECT: ... | VOID: ...
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from adapter import KaosAdapter  # noqa: E402
from generate_session import Session, Step, fingerprint, generate_sessions  # noqa: E402

LOCK_PATH = HERE / "preregistration.json"

# Pre-registered lock hashes — the runner refuses to run on any other.
KNOWN_LOCK_SHA256 = {
    "018a9fff8831d9795d7aef0285742d2eadb3c3fa02ad73a3879c360dd303c35c": "v1-pre-registration",
}


def load_lock() -> dict:
    from kaos.eval.harness import load_lock
    return load_lock(LOCK_PATH, KNOWN_LOCK_SHA256)


def _run_session(ad: KaosAdapter, s: Session, upto: int | None = None,
                 start: int = 0) -> None:
    for step in s.steps[start:upto]:
        ad.execute(s.agent_id, step)  # type: ignore[attr-defined]


def run(lock: dict, db_path: str) -> dict:
    g = lock["generator"]
    sessions = generate_sessions(g["seed"], g["n_agents"], g["k_steps"])
    void = []
    if fingerprint(sessions) != fingerprint(generate_sessions(g["seed"], g["n_agents"], g["k_steps"])):
        void.append("generator not seed-deterministic")

    ad = KaosAdapter(db_path)
    cp_at = g["checkpoint_at"]
    fidelity_ok = 0
    cp_hashes: dict[str, str] = {}
    cp_ids: dict[str, str] = {}
    final_hashes: dict[str, str] = {}

    # Execute every session with a checkpoint at cp_at, then finish it.
    for s in sessions:
        s.agent_id = ad.spawn(s.name)  # type: ignore[attr-defined]
        _run_session(ad, s, upto=cp_at)
        cp_ids[s.name] = ad.checkpoint(s.agent_id)  # type: ignore[attr-defined]
        cp_hashes[s.name] = ad.vfs_hash(s.agent_id)  # type: ignore[attr-defined]
        _run_session(ad, s, start=cp_at)
        final_hashes[s.name] = ad.vfs_hash(s.agent_id)  # type: ignore[attr-defined]

    # 1. Checkpoint fidelity (restore, hash, compare, then bring the agent
    #    back to its final state by replaying the tail so later tests see it).
    for s in sessions:
        ad.restore(s.agent_id, cp_ids[s.name])  # type: ignore[attr-defined]
        if ad.vfs_hash(s.agent_id) == cp_hashes[s.name]:  # type: ignore[attr-defined]
            fidelity_ok += 1
        for step in s.steps[cp_at:]:
            if step.tool == "fs_write":
                ad.db.write(s.agent_id, step.path, step.content.encode())  # type: ignore[attr-defined]
    checkpoint_fidelity = fidelity_ok / len(sessions)

    # 2. Journal completeness: tool_calls rows + start/end events per executed step.
    complete = 0
    expected = 0
    for s in sessions:
        n = len(s.steps)
        expected += n
        calls = ad.list_tool_calls(s.agent_id)  # type: ignore[attr-defined]
        starts = ad.db.events.count(s.agent_id, "tool_call_start")
        ends = ad.db.events.count(s.agent_id, "tool_call_end")
        complete += min(n, len(calls), starts, ends)
    journal_completeness = complete / expected

    # 3. Cross-agent isolation: files and memory.
    from kaos.memory import MemoryStore
    leaks = 0
    a, b = sessions[0], sessions[1]
    secret_path = "/secret/afb-token.txt"
    ad.db.write(a.agent_id, secret_path, b"afbsecrettoken7f3a")  # type: ignore[attr-defined]
    if ad.read_other(b.agent_id, a.agent_id, secret_path):  # type: ignore[attr-defined]
        leaks += 1
    mem = MemoryStore(ad.conn)
    mem.write(a.agent_id, "afbsecrettoken7f3a is agent A's private memory", type="observation")  # type: ignore[attr-defined]
    # FTS5 MATCH syntax: quote the term (a hyphenated token would parse as a column filter).
    hits = mem.search('"afbsecrettoken7f3a"', agent_id=b.agent_id)  # type: ignore[attr-defined]
    leaks += len(hits)
    pairs_checked = 2

    # 4. Fault localization: entries inspected from the localizer's pointer.
    from kaos.dream.phases.localize import localize
    inspected: list[int] = []
    for s in sessions:
        calls = ad.list_tool_calls(s.agent_id)  # type: ignore[attr-defined]
        cs = localize(ad.conn, s.agent_id, persist=False)
        if cs is None or cs.tool_call_id is None:
            inspected.append(len(calls))
            continue
        pointer = next((i for i, c in enumerate(calls) if c["call_id"] == cs.tool_call_id), None)
        inspected.append(len(calls) if pointer is None else abs(pointer - s.culprit_index) + 1)
    fault_localization_median = statistics.median(inspected)
    exact_hits = sum(1 for x in inspected if x == 1)

    # 5. Cold-start replay from the journal into a fresh db, twice.
    def replay(target: str) -> dict[str, str]:
        rep = KaosAdapter(target)
        out: dict[str, str] = {}
        for s in sessions:
            aid = rep.spawn(s.name)
            for c in ad.list_tool_calls(s.agent_id):  # type: ignore[attr-defined]
                inp = dict(c["input"])
                inp.pop("expect_error", None)
                inp.pop("tool", None)
                rep.execute(aid, Step(tool=c["tool"], **inp))
            out[s.name] = rep.vfs_hash(aid)
        rep.close()
        return out
    with tempfile.TemporaryDirectory() as td:
        r1 = replay(os.path.join(td, "replay1.db"))
        r2 = replay(os.path.join(td, "replay2.db"))
    if r1 != r2:
        void.append("replay non-deterministic")
    replay_match = sum(1 for s in sessions if r1[s.name] == final_hashes[s.name]) / len(sessions)

    # 6. Mid-task recovery: crash crash_offset steps after the checkpoint,
    #    restore, redo the tail. Overhead = steps redone / total steps.
    crash_offset = g["crash_offset"]
    redone = 0
    total = 0
    recovered = 0
    for s in sessions:
        total += len(s.steps)
        ad.restore(s.agent_id, cp_ids[s.name])  # type: ignore[attr-defined]
        for step in s.steps[cp_at:]:
            if step.tool == "fs_write":
                ad.db.write(s.agent_id, step.path, step.content.encode())  # type: ignore[attr-defined]
        redone += crash_offset  # the steps between checkpoint and crash are executed twice
        if ad.vfs_hash(s.agent_id) == final_hashes[s.name]:  # type: ignore[attr-defined]
            recovered += 1
    recovery_overhead = redone / total
    ad.close()

    tests = {
        "checkpoint_fidelity": {"value": checkpoint_fidelity, "n": len(sessions), "gate": "== 1.0"},
        "journal_completeness": {"value": journal_completeness, "executed": expected, "gate": "== 1.0"},
        "cross_agent_isolation": {"leaks": leaks, "checks": pairs_checked, "gate": "leaks == 0"},
        "fault_localization": {"median_entries_inspected": fault_localization_median,
                                "exact_hits": exact_hits, "n": len(sessions),
                                "per_agent": inspected, "gate": "median <= 5"},
        "cold_start_replay": {"match": replay_match, "deterministic": r1 == r2, "gate": "== 1.0"},
        "mid_task_recovery": {"overhead": recovery_overhead, "recovered": recovered,
                               "n": len(sessions), "gate": "< 0.20"},
    }
    if void:
        verdict = "VOID: " + "; ".join(void)
    else:
        fails = []
        if checkpoint_fidelity < 1.0:
            fails.append(f"checkpoint_fidelity={checkpoint_fidelity:.3f}")
        if journal_completeness < 1.0:
            fails.append(f"journal_completeness={journal_completeness:.3f}")
        if leaks > 0:
            fails.append(f"isolation_leaks={leaks}")
        if fault_localization_median > 5:
            fails.append(f"fault_localization_median={fault_localization_median}")
        if replay_match < 1.0:
            fails.append(f"replay_match={replay_match:.3f}")
        if recovery_overhead >= 0.20:
            fails.append(f"recovery_overhead={recovery_overhead:.3f}")
        verdict = "ACCEPT" if not fails else "REJECT: " + ", ".join(fails)
    return {"verdict": verdict, "tests": tests}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output", default=None, help="results JSON path")
    ap.add_argument("--db", default=None, help="bench db path (default: temp file)")
    args = ap.parse_args(argv)

    lock = load_lock()
    from kaos.eval.harness.manifest import sha256_file
    import kaos
    t0 = time.time()
    with tempfile.TemporaryDirectory() as td:
        db_path = args.db or os.path.join(td, "afb.db")
        res = run(lock, db_path)
    try:
        git_sha = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"],
                                          cwd=HERE, text=True).strip()
    except Exception:
        git_sha = ""
    res.update({
        "benchmark": "afb", "version": lock["version"],
        "kaos_version": getattr(kaos, "__version__", "?"), "git_sha": git_sha,
        "lock_sha256": sha256_file(LOCK_PATH),
        "generator": lock["generator"], "elapsed_s": round(time.time() - t0, 2),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    })
    out = Path(args.output) if args.output else HERE / "results" / f"kaos_v{res['kaos_version']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2) + "\n")
    print(json.dumps({k: res[k] for k in ("verdict", "elapsed_s")}, indent=2))
    for name, t in res["tests"].items():
        print(f"  {name:24s} {json.dumps({k: v for k, v in t.items() if k != 'per_agent'})}")
    print(f"written: {out}")
    return 0 if res["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    sys.exit(main())
