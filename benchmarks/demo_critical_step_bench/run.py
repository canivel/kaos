"""Track B2 (v0.8.3) benchmark — does the localizer find the EARLIEST
decisive error, not just the visible one?

Five synthetic trajectories. Each plants the decisive mistake N steps
before the visible error and records the ground-truth index. The
localizer must land within +/-1 step of ground truth on >=4/5.

Reproducible. No LLM (pure heuristic path). No pre-engineered winners.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

os.environ["KAOS_DREAM_THRESHOLD"] = "1000000"

from kaos import Kaos  # noqa: E402
from kaos.shared_log import SharedLog  # noqa: E402
from kaos.dream.phases.localize import localize, _load_trace  # noqa: E402


def _tool(conn, aid, cid, name, status="success", err=None):
    conn.execute(
        "INSERT INTO tool_calls (call_id, agent_id, tool_name, input, "
        "status, error_message, started_at) VALUES "
        "(?, ?, ?, '{}', ?, ?, strftime('%Y-%m-%dT%H:%M:%f','now'))",
        (cid, aid, name, status, err),
    )
    conn.commit()


# Each scenario builds a trajectory and returns the ground-truth
# trace-index of the decisive step (the step a human would point at).
def scenario_bad_intent(kaos):
    """Agent commits to the wrong plan up front; error surfaces 3 tools later."""
    aid = kaos.spawn("s1")
    log = SharedLog(kaos.conn)
    log.intent(aid, "wrong: delete the prod table to free space")  # DECISIVE
    _tool(kaos.conn, aid, "s1a", "read-disk-usage")
    _tool(kaos.conn, aid, "s1b", "read-table-stats")
    _tool(kaos.conn, aid, "s1c", "run-drop-table", status="error",
          err="FATAL: cannot drop table referenced by FK")
    steps = _load_trace(kaos.conn, aid)
    gt = next(i for i, s in enumerate(steps) if s.kind == "log")
    return aid, gt


def scenario_immediate_error(kaos):
    """No prior decision — the error itself is the critical step."""
    aid = kaos.spawn("s2")
    _tool(kaos.conn, aid, "s2a", "fetch-remote", status="error",
          err="Connection refused")
    steps = _load_trace(kaos.conn, aid)
    return aid, 0


def scenario_wrong_write_midway(kaos):
    """Two reads, a decisive write with bad input, then the failure."""
    aid = kaos.spawn("s3")
    _tool(kaos.conn, aid, "s3a", "read-config")
    _tool(kaos.conn, aid, "s3b", "read-schema")
    _tool(kaos.conn, aid, "s3c", "write-migration")   # DECISIVE (write hint)
    _tool(kaos.conn, aid, "s3d", "read-status")
    _tool(kaos.conn, aid, "s3e", "apply-migration", status="error",
          err="syntax error near 'COLUM'")
    steps = _load_trace(kaos.conn, aid)
    gt = next(i for i, s in enumerate(steps)
              if s.kind == "tool" and "write" in s.label)
    return aid, gt


def scenario_long_gap(kaos):
    """Decisive intent, then a long innocent stretch, then failure."""
    aid = kaos.spawn("s4")
    log = SharedLog(kaos.conn)
    log.intent(aid, "deploy unverified build to staging")  # DECISIVE
    for i in range(6):
        _tool(kaos.conn, aid, f"s4_{i}", f"poll-step-{i}")
    _tool(kaos.conn, aid, "s4E", "smoke-test", status="error",
          err="healthcheck never turned green")
    steps = _load_trace(kaos.conn, aid)
    gt = next(i for i, s in enumerate(steps) if s.kind == "log")
    return aid, gt


def scenario_vote_then_fail(kaos):
    """A vote locks the direction; the action fails two steps later."""
    aid = kaos.spawn("s5")
    log = SharedLog(kaos.conn)
    iid = log.intent(aid, "merge skill A into B")
    log.vote(aid, iid, approve=True, reason="looks safe")  # DECISIVE-ish
    _tool(kaos.conn, aid, "s5a", "read-skill-a")
    _tool(kaos.conn, aid, "s5b", "run-merge", status="error",
          err="merge produced an orphaned association")
    steps = _load_trace(kaos.conn, aid)
    # Ground truth: the intent (earliest decisive). Localizer landing on
    # the vote (one step later) is within +/-1 and acceptable.
    gt = next(i for i, s in enumerate(steps) if s.kind == "log")
    return aid, gt


SCENARIOS = [
    ("bad_intent_up_front", scenario_bad_intent),
    ("immediate_error", scenario_immediate_error),
    ("wrong_write_midway", scenario_wrong_write_midway),
    ("long_gap_before_failure", scenario_long_gap),
    ("vote_then_fail", scenario_vote_then_fail),
]


def main() -> int:
    db = HERE / "bench.db"
    if db.exists():
        db.unlink()
    kaos = Kaos(db_path=str(db))

    print("=" * 68)
    print("Critical-step localizer benchmark (heuristic path, no LLM)")
    print("=" * 68)

    results = []
    try:
        for name, fn in SCENARIOS:
            aid, gt = fn(kaos)
            cs = localize(kaos.conn, aid, persist=False)
            got = cs.log_position if cs else None
            within = got is not None and abs(got - gt) <= 1
            results.append({
                "scenario": name, "ground_truth": gt,
                "localized": got, "within_1": within,
                "confidence": cs.confidence if cs else None,
                "method": cs.method if cs else None,
            })
            mark = "OK " if within else "XX "
            print(f"  [{mark}] {name:<26} gt={gt}  got={got}  "
                  f"conf={cs.confidence if cs else 0:.2f}")
    finally:
        kaos.close()

    hits = sum(1 for r in results if r["within_1"])
    n = len(results)
    print("\n" + "=" * 68)
    print(f"RESULT: {hits}/{n} within +/-1 step of ground truth")
    print("=" * 68)

    out = {"scenarios": results, "hits": hits, "total": n,
           "acceptance": "hits >= 4/5"}
    (HERE / "results.json").write_text(json.dumps(out, indent=2),
                                       encoding="utf-8")
    md = [
        "# Critical-step localizer benchmark\n",
        "Five planted-bug trajectories where the decisive mistake is N "
        "steps before the visible error. Heuristic path only (no LLM).\n",
        "| Scenario | ground truth | localized | within +/-1 |",
        "|---|:-:|:-:|:-:|",
    ]
    for r in results:
        md.append(f"| {r['scenario']} | {r['ground_truth']} | "
                  f"{r['localized']} | {'Y' if r['within_1'] else 'N'} |")
    md.append("")
    md.append(f"**{hits}/{n} within +/-1 step.** Acceptance gate: >= 4/5.")
    md.append("")
    md.append("Raw JSON: [results.json](results.json)")
    (HERE / "results.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    if hits >= 4:
        print(f"\n  [OK] localizer hit {hits}/{n} (gate: >=4/5)")
        return 0
    print(f"\n  [WARN] localizer only hit {hits}/{n} (gate: >=4/5)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
