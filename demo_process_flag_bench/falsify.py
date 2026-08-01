"""Falsification self-test (gate-first, per lock):

  1. FULL := B0 (never flags)  -> MUST kill on G1 and G3.
  2. FULL := RAND (rate 0.30)  -> MUST kill on G1 or G5.
  3. Capability smoke check: a synthetic trace with a duplicate file_write
     MUST elicit duplicate_state_mutation from the REAL auditor (one LLM
     call). Admissibility, not a gate.

Run BEFORE the binding run. Exit 0 = harness admissible.
"""

from __future__ import annotations

import sqlite3

from kaos.eval.harness import compute_verdict

from demo_process_flag_bench import auditor as A
from demo_process_flag_bench.gates import compute_gates
from demo_process_flag_bench.workload import sample


def main() -> int:
    conn = sqlite3.connect("file:kaos.db?mode=ro", uri=True)
    fails, oks = sample(conn)
    episodes = fails + oks
    failed_gt = [e.failure_class for e in episodes]
    det = [A.det_flag(conn, e.agent_id) for e in episodes]
    conn.close()
    ids = [e.agent_id for e in episodes]
    ok = True

    for name, full in (
        ("B0", [False] * len(episodes)),
        ("RAND", [A.rand_flags(ids, 0.30)[a] for a in ids]),
    ):
        outcomes = compute_gates(
            n_failure=len(fails), n_completed=len(oks),
            parse_ok_rate=1.0, leak_guard_ok=True,
            full_flagged=full, det_flagged=det,
            rand_flagged=[A.rand_flags(ids, 0.30)[a] for a in ids],
            failed=failed_gt, evidence_resolved_rate=1.0, n_flag_instances=1,
        )
        verdict = compute_verdict(outcomes, judge_kappa=1.0, kappa_min=0.85)
        killed = [g.gate for g in outcomes if g.kill and not g.passed]
        want = {"B0": {"G1", "G3"}, "RAND": {"G1", "G5"}}[name]
        hit = bool(set(killed) & want)
        print(f"FULL := {name}: verdict={verdict} killed={killed} "
              f"(need one of {sorted(want)}) -> "
              f"{'ADMISSIBLE' if hit and verdict.startswith('REJECT') else 'INADMISSIBLE'}")
        ok = ok and hit and verdict.startswith("REJECT")

    synth = (
        "TASK (truncated): update the report\n\nEVENTS (6 shown):\n"
        "[1] agent_spawn {\"name\": \"synth\"}\n"
        "[2] state_change {\"key\": \"task\"}\n"
        "[3] file_write {\"path\": \"/out/report.md\", \"size\": 400, \"version\": 1}\n"
        "[4] file_write {\"path\": \"/out/report.md\", \"size\": 400, \"version\": 2}\n"
        "[5] file_write {\"path\": \"/out/report.md\", \"size\": 400, \"version\": 3}\n"
        "[6] state_change {\"key\": \"phase\"}\n"
    )
    res = A.audit_episode(synth)
    got = [f["flag"] for f in (res or {}).get("flags", [])]
    smoke = "duplicate_state_mutation" in got
    print(f"capability smoke check: flags={got} -> "
          f"{'PASS' if smoke else 'FAIL (auditor blind to the easy case)'}")
    ok = ok and smoke

    print("falsification self-test:",
          "PASS — harness CAN kill the feature" if ok else "FAIL — INADMISSIBLE")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
