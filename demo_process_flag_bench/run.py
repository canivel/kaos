"""PFA probe runner — binding run.

Usage: uv run python -m demo_process_flag_bench.run [--db kaos.db] [--resume]

Persists each audit incrementally to audits.jsonl so an interrupted run
resumes without re-paying LLM calls (resume is a crash-recovery affordance,
not a re-roll: an episode already audited is NEVER re-audited).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from kaos.eval.harness import compute_verdict

from demo_process_flag_bench import auditor as A
from demo_process_flag_bench.gates import compute_gates, load
from demo_process_flag_bench.workload import leak_guard, render, sample

BENCH = Path(__file__).parent
AUDITS = BENCH / "audits.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="kaos.db")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    lock = load()
    print(f"lock OK: {lock['name']} {lock['version']}", flush=True)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    fails, oks = sample(conn)
    episodes = fails + oks
    print(f"sample: {len(fails)} failure-class + {len(oks)} completed "
          f"= {len(episodes)}", flush=True)

    done: dict[str, dict] = {}
    if args.resume and AUDITS.exists():
        for line in AUDITS.read_text(encoding="utf-8").splitlines():
            d = json.loads(line)
            done[d["agent_id"]] = d
        print(f"resume: {len(done)} audits already on disk", flush=True)

    leak_ok = True
    renders: dict[str, tuple[str, list[int]]] = {}
    for ep in episodes:
        trace, ids = render(conn, ep.agent_id)
        renders[ep.agent_id] = (trace, ids)
        if not leak_guard(A.PROMPT + trace):
            leak_ok = False
            print(f"LEAK GUARD VIOLATION: {ep.agent_id}", flush=True)
    print(f"leak guard over {len(renders)} prompts: {'OK' if leak_ok else 'VIOLATED'}",
          flush=True)

    with AUDITS.open("a", encoding="utf-8") as fh:
        for i, ep in enumerate(episodes):
            if ep.agent_id in done:
                continue
            trace, _ = renders[ep.agent_id]
            res = A.audit_episode(trace)
            rec = {"agent_id": ep.agent_id, "audit": res}
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            done[ep.agent_id] = rec
            if (i + 1) % 10 == 0:
                print(f"  audited {i + 1}/{len(episodes)}", flush=True)

    parse_ok = sum(1 for d in done.values()
                   if d["audit"] is not None) / len(episodes)
    full_flagged, failed_gt = [], []
    n_instances = 0
    n_resolved = 0
    for ep in episodes:
        aud = done[ep.agent_id]["audit"]
        flags = (aud or {}).get("flags", [])
        full_flagged.append(bool(flags))
        failed_gt.append(ep.failure_class)
        ids = set(renders[ep.agent_id][1])
        for f in flags:
            n_instances += 1
            ev = f.get("evidence_event_ids") or []
            if any(isinstance(e, int) and e in ids for e in ev):
                n_resolved += 1

    det_flagged = [A.det_flag(conn, ep.agent_id) for ep in episodes]
    rate = sum(full_flagged) / len(episodes)
    rmap = A.rand_flags([ep.agent_id for ep in episodes], rate)
    rand_flagged = [rmap[ep.agent_id] for ep in episodes]
    conn.close()

    outcomes = compute_gates(
        n_failure=len(fails), n_completed=len(oks),
        parse_ok_rate=parse_ok, leak_guard_ok=leak_ok,
        full_flagged=full_flagged, det_flagged=det_flagged,
        rand_flagged=rand_flagged, failed=failed_gt,
        evidence_resolved_rate=(n_resolved / n_instances) if n_instances else 0.0,
        n_flag_instances=n_instances,
    )
    verdict = compute_verdict(outcomes, judge_kappa=1.0, kappa_min=0.85)
    for g in outcomes:
        tag = "PASS" if g.passed else ("KILL" if g.kill else "VOID-FAIL")
        print(f"  [{tag}: {g.gate}] {g.name} — {g.detail}", flush=True)
    print(f"VERDICT: {verdict}", flush=True)

    per_flag: dict[str, int] = {}
    for d in done.values():
        for f in (d["audit"] or {}).get("flags", []):
            per_flag[f["flag"]] = per_flag.get(f["flag"], 0) + 1

    results = {
        "lock": {"name": lock["name"], "version": lock["version"]},
        "sample": {"n_failure": len(fails), "n_completed": len(oks)},
        "per_episode": [
            {"agent_id": ep.agent_id, "failure_class": ep.failure_class,
             "full": full_flagged[i], "det": det_flagged[i],
             "rand": rand_flagged[i],
             "flags": [f["flag"] for f in (done[ep.agent_id]["audit"] or {}).get("flags", [])]}
            for i, ep in enumerate(episodes)
        ],
        "flag_histogram": per_flag,
        "parse_ok_rate": parse_ok,
        "evidence": {"instances": n_instances, "resolved": n_resolved},
        "gates": [vars(g) for g in outcomes],
        "judge_kappa": 1.0,
        "verdict": verdict,
    }
    (BENCH / "results.json").write_text(json.dumps(results, indent=2))
    print(f"wrote {BENCH / 'results.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
