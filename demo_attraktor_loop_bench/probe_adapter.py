"""Binding-probe adapter — reads the live bench.db, applies the frozen gates.

The probe consumes ONLY ledgered evidence (bench_pulls with an arm assignment,
outcome_telemetry rows linked by pull_id) — it cannot see how episodes ran, and
episodes cannot see the probe. ``collect_stats`` is the single reader; the same
stats feed ``status()`` (progress surface, VOID until floors are met) and
``run_probe()`` (the binding verdict + results.json).

Falsification self-test (per the lock): before trusting its own verdict the
probe substitutes ON := OFF and requires G1 to fail. If the harness cannot
kill a provably-inert treatment, it is inadmissible and refuses to bind.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from demo_attraktor_loop_bench.gates import LoopStats, compute_gates, load
from kaos.eval.harness.verdict import compute_verdict


def collect_stats(bench: sqlite3.Connection) -> LoopStats:
    """Mechanical read per the lock's episode definition. Legacy rows (no arm /
    no pull_id — pre-lock) are excluded by construction, never by judgment."""
    stats = LoopStats(outcomes={"on": [], "off": [], "scrambled": []})

    for row in bench.execute(
        "SELECT p.arm AS arm, MAX(t.outcome) AS outcome "
        "FROM bench_pulls p JOIN outcome_telemetry t ON t.pull_id = p.pull_id "
        "WHERE p.arm IN ('on','off','scrambled') AND t.outcome IS NOT NULL "
        "  AND t.outcome_source IN ('runner','harness','mechanical') "
        "GROUP BY p.pull_id"
    ):
        stats.outcomes[row["arm"]].append(int(row["outcome"]))

    stats.latencies_ms = [
        float(r["latency_ms"]) for r in bench.execute(
            "SELECT latency_ms FROM bench_pulls "
            "WHERE arm IN ('on','off','scrambled') AND latency_ms IS NOT NULL")
    ]
    stats.n_pulls = bench.execute(
        "SELECT COUNT(*) FROM bench_pulls "
        "WHERE arm IN ('on','off','scrambled')").fetchone()[0]
    stats.n_matched_pulls = bench.execute(
        "SELECT COUNT(DISTINCT p.pull_id) FROM bench_pulls p "
        "JOIN bench_pull_decisions d ON d.pull_id = p.pull_id "
        "WHERE p.arm IN ('on','off','scrambled') "
        "  AND d.decision IN ('served','shadow')").fetchone()[0]
    return stats


def falsify(stats: LoopStats) -> tuple[bool, str]:
    """ON := OFF must fail G1. Returns (harness_can_kill, detail)."""
    stub = LoopStats(
        outcomes={"on": list(stats.outcomes.get("off", ())),
                  "off": list(stats.outcomes.get("off", ())),
                  "scrambled": list(stats.outcomes.get("scrambled", ()))},
        latencies_ms=stats.latencies_ms, n_pulls=stats.n_pulls,
        n_matched_pulls=stats.n_matched_pulls)
    g1 = next(g for g in compute_gates(stub) if g.gate == "G1")
    if g1.passed:
        return False, ("INADMISSIBLE: G1 passed with ON substituted by OFF — "
                       "the harness cannot kill an inert treatment. " + g1.detail)
    return True, "ON := OFF correctly fails G1 (" + g1.detail + ")"


def status(bench: sqlite3.Connection) -> dict:
    """Read-only progress surface: current gates + verdict-if-bound-now.
    Safe to run any time; a VOID here just means 'keep accumulating'."""
    lock = load()
    stats = collect_stats(bench)
    outcomes = compute_gates(stats)
    verdict = compute_verdict(outcomes, judge_kappa=None)
    return {
        "lock": lock["name"], "lock_version": lock["version"],
        "episodes": {a: stats.n(a) for a in ("on", "off", "scrambled")},
        "wins": {a: stats.wins(a) for a in ("on", "off", "scrambled")},
        "pulls": stats.n_pulls, "matched_pulls": stats.n_matched_pulls,
        "gates": [asdict(g) for g in outcomes],
        "verdict_if_bound_now": verdict,
    }


def run_probe(bench: sqlite3.Connection, *, out_dir: str | Path) -> dict:
    """THE binding run. Refuses to bind if the falsification self-test fails.
    Writes results.json; the verdict on file is final (no retune-and-rerun)."""
    lock = load()
    stats = collect_stats(bench)

    can_kill, self_test_detail = falsify(stats)
    outcomes = compute_gates(stats)
    if not can_kill:
        verdict = "VOID: harness cannot kill (falsification self-test failed)"
    else:
        verdict = compute_verdict(outcomes, judge_kappa=None)

    results = {
        "lock_name": lock["name"], "lock_version": lock["version"],
        "self_test_passed": can_kill, "self_test_detail": self_test_detail,
        "episodes": {a: stats.n(a) for a in ("on", "off", "scrambled")},
        "wins": {a: stats.wins(a) for a in ("on", "off", "scrambled")},
        "pulls": stats.n_pulls, "matched_pulls": stats.n_matched_pulls,
        "latency_n": len(stats.latencies_ms),
        "gates": [asdict(g) for g in outcomes],
        "judge_kappa": None,
        "verdict": verdict,
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
