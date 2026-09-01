"""GDL probe runner — builds the workload, runs all four arms, computes
the frozen gates, emits the binding verdict, writes results.json.

Usage:  uv run python -m demo_graphdiff_localizer_bench.run [--organic-db kaos.db]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
from pathlib import Path

from kaos.eval.harness import ArmResults, QueryResult, compute_verdict

from demo_graphdiff_localizer_bench import arms as A
from demo_graphdiff_localizer_bench.gates import compute_gates, load
from demo_graphdiff_localizer_bench.graphdiff import reuse_rate
from demo_graphdiff_localizer_bench.workload import Episode, build

BENCH_DIR = Path(__file__).parent
DB_PATH = BENCH_DIR / "bench.db"

ARM_FNS = {"B0": A.arm_b0, "B1": A.arm_b1, "FULL": A.arm_full, "L1": A.arm_l1}


def organic_reuse(organic_db: str) -> tuple[float, int, list[float]]:
    conn = sqlite3.connect(f"file:{organic_db}?mode=ro", uri=True)
    agents = [r[0] for r in conn.execute(
        "SELECT agent_id FROM tool_calls GROUP BY agent_id "
        "HAVING COUNT(*) >= 8").fetchall()]
    rates = sorted(reuse_rate(conn, a) for a in agents)
    conn.close()
    med = statistics.median(rates) if rates else 0.0
    return med, len(agents), rates


def run_arms(
    conn: sqlite3.Connection, failed: list[Episode], successes: list[Episode],
) -> dict[str, ArmResults]:
    gt = {e.agent_id: e.gt_call_id for e in failed}
    out: dict[str, ArmResults] = {}
    for name, fn in ARM_FNS.items():
        ar = ArmResults(arm=name)
        for ep in failed:
            pred = fn(conn, ep, successes)
            ar.per_query.append(QueryResult(
                qid=ep.agent_id, qclass=ep.qclass,
                correct=(pred == gt[ep.agent_id]),
                extras={"predicted": pred, "family": ep.family},
            ))
        out[name] = ar
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--organic-db", default="kaos.db")
    args = ap.parse_args()

    lock = load()  # refuses to run on a tampered lock
    print(f"lock OK: {lock['name']} {lock['version']}")

    if DB_PATH.exists():
        DB_PATH.unlink()
    episodes = build(str(DB_PATH))
    failed = [e for e in episodes if e.qclass != "success"]
    successes = [e for e in episodes if e.qclass == "success"]
    print(f"workload: {len(failed)} failed "
          f"({sum(1 for e in failed if e.qclass=='silent_wrong_branch')} silent, "
          f"{sum(1 for e in failed if e.qclass=='error_visible')} error-visible), "
          f"{len(successes)} successes")

    conn = sqlite3.connect(DB_PATH)
    arm_results = run_arms(conn, failed, successes)
    pair_rate = A.pairing_same_family_rate(conn, failed, successes)
    conn.close()

    med_reuse, n_organic, rates = organic_reuse(args.organic_db)
    print(f"organic G3 slice: {n_organic} agents, median reuse {med_reuse:.3f}")

    outcomes = compute_gates(
        arm_results,
        organic_median_reuse=med_reuse,
        organic_n_agents=n_organic,
        pairing_same_family_rate=pair_rate,
    )
    verdict = compute_verdict(outcomes, judge_kappa=1.0, kappa_min=0.85)

    for g in outcomes:
        tag = "PASS" if g.passed else ("KILL" if g.kill else "VOID-FAIL")
        print(f"  [{tag}: {g.gate}] {g.name} — {g.detail}")
    print(f"VERDICT: {verdict}")

    results = {
        "lock": {"name": lock["name"], "version": lock["version"]},
        "arms": {
            n: {"per_query": [vars(q) for q in ar.per_query],
                "acc_overall": ar.acc({"silent_wrong_branch", "error_visible"}),
                "acc_silent": ar.acc({"silent_wrong_branch"}),
                "acc_error_visible": ar.acc({"error_visible"})}
            for n, ar in arm_results.items()
        },
        "pairing_same_family_rate": pair_rate,
        "organic": {"median_reuse": med_reuse, "n_agents": n_organic,
                    "per_agent_rates": rates},
        "gates": [vars(g) for g in outcomes],
        "judge_kappa": 1.0,
        "judge_kappa_note": "mechanical ground-truth labels; no judgment to audit (per lock)",
        "verdict": verdict,
        "external_validity_caveat": (
            "Localization slice is HARNESS-GENERATED (pre-registered as such in "
            "ISA.lock.json). Any ACCEPT is an accept ON CONSTRUCTED WORKLOAD; "
            "G3 alone is organic. Organic replication is a separate future probe."
        ),
    }
    (BENCH_DIR / "results.json").write_text(json.dumps(results, indent=2))
    print(f"wrote {BENCH_DIR / 'results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
