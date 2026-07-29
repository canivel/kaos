"""Workload-shape metrics — the measured substrate for the transfer paper.

Four metric families, all mechanical, all read-only over an organic
kaos database. No LLM, no embeddings, no sampling: every number is a
deterministic function of the DB contents.

  M1  action-arg entropy      — per-agent normalized-label reuse
                                (frozen GDL normalization, reused verbatim)
  M2  outcome-signal density  — where ground truth about success lives,
                                and how much of the plasticity substrate
                                is actually populated organically
  M3  task-text anchoring     — lexical anchors that make BM25 pairing
                                possible without embeddings
  M4  expert availability     — failed episodes that HAVE a matched
                                successful counterpart to diff against

Usage: uv run python -m demo_workload_shape_bench.bench [--db kaos.db]
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

from demo_graphdiff_localizer_bench.graphdiff import Interner, node_label

OUT = Path(__file__).parent / "results.json"

_ANCHORS = {
    "path": re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+|\w+\.(py|json|yaml|md|sql|toml|txt|db)\b"),
    "identifier": re.compile(r"\b[a-z0-9]+_[a-z0-9_]+\b|\b[a-z]+[A-Z][A-Za-z]+\b"),
    "error_code": re.compile(r"\b(exit \d+|E\d{2,}|errno|traceback|exception)\b", re.I),
    "hex_or_hash": re.compile(r"\b[0-9a-f]{7,}\b"),
    "version_or_num": re.compile(r"\bv?\d+\.\d+(\.\d+)?\b"),
}
_TOKEN = re.compile(r"[A-Za-z0-9_]+")


def _task_of(raw: str) -> str:
    try:
        v = json.loads(raw)
        return v if isinstance(v, str) else raw
    except (json.JSONDecodeError, TypeError):
        return raw


def m1_arg_entropy(conn: sqlite3.Connection) -> dict:
    agents = [r[0] for r in conn.execute(
        "SELECT agent_id FROM tool_calls GROUP BY agent_id "
        "HAVING COUNT(*) >= 8").fetchall()]
    per = []
    for a in agents:
        rows = conn.execute(
            "SELECT tool_name, input FROM tool_calls WHERE agent_id=? "
            "ORDER BY started_at", (a,)).fetchall()
        it = Interner()
        labels = [it(node_label(t, i)) for t, i in rows]
        per.append({"agent": a, "n_calls": len(labels),
                    "n_labels": len(set(labels)),
                    "reuse": len(labels) / len(set(labels))})
    div = [p for p in per if p["n_labels"] >= 3]
    div5 = [p for p in per if p["n_labels"] >= 5]
    tools = Counter(r[0] for r in conn.execute(
        "SELECT tool_name FROM tool_calls").fetchall())
    return {
        "n_agents_ge8_calls": len(per),
        "pct_mono_label": (sum(1 for p in per if p["n_labels"] < 3) / len(per)
                           if per else None),
        "median_reuse_all": (statistics.median(p["reuse"] for p in per)
                             if per else None),
        "median_reuse_diverse_ge3": (statistics.median(p["reuse"] for p in div)
                                     if div else None),
        "median_reuse_diverse_ge5": (statistics.median(p["reuse"] for p in div5)
                                     if div5 else None),
        "n_diverse_ge3": len(div),
        "pct_diverse_ge3_reuse_ge_1_3": (sum(1 for p in div if p["reuse"] >= 1.3)
                                         / len(div) if div else None),
        "top_tools": tools.most_common(8),
        "per_agent": per,
    }


def m2_signal_density(conn: sqlite3.Connection) -> dict:
    one = lambda s: conn.execute(s).fetchone()[0]  # noqa: E731
    status = dict(conn.execute(
        "SELECT status, COUNT(*) FROM agents GROUP BY status").fetchall())
    return {
        "agents_by_status": status,
        "episode_signals_rows": one("SELECT COUNT(*) FROM episode_signals"),
        "skill_uses_rows": one("SELECT COUNT(*) FROM skill_uses"),
        "skill_uses_success_null": one(
            "SELECT COUNT(*) FROM skill_uses WHERE success IS NULL"),
        "failure_fingerprints_rows": one(
            "SELECT COUNT(*) FROM failure_fingerprints"),
        "critical_steps_rows": one("SELECT COUNT(*) FROM critical_steps"),
        "memory_rows": one("SELECT COUNT(*) FROM memory"),
        "tool_calls_error": one(
            "SELECT COUNT(*) FROM tool_calls WHERE status='error' "
            "OR error_message IS NOT NULL"),
        "tool_calls_total": one("SELECT COUNT(*) FROM tool_calls"),
    }


def _tasks_by_agent(conn: sqlite3.Connection) -> dict[str, str]:
    return {a: _task_of(v) for a, v in conn.execute(
        "SELECT agent_id, value FROM state WHERE key='task'").fetchall()}


def m3_anchoring(conn: sqlite3.Connection) -> dict:
    tasks = list(_tasks_by_agent(conn).values())
    per_kind = {k: sum(1 for t in tasks if rx.search(t)) for k, rx in _ANCHORS.items()}
    anchored = sum(1 for t in tasks
                   if any(rx.search(t) for rx in _ANCHORS.values()))
    return {
        "n_tasks": len(tasks),
        "anchored_any": anchored,
        "anchored_rate": anchored / len(tasks) if tasks else None,
        "per_anchor_kind": per_kind,
        "median_tokens": (statistics.median(len(_TOKEN.findall(t)) for t in tasks)
                          if tasks else None),
    }


def m4_expert_availability(conn: sqlite3.Connection) -> dict:
    tasks = _tasks_by_agent(conn)
    status = dict(conn.execute(
        "SELECT agent_id, status FROM agents").fetchall())
    failed = [a for a, s in status.items() if s in ("failed", "killed") and a in tasks]
    ok = [a for a, s in status.items() if s == "completed" and a in tasks]
    ok_exact = {}
    for a in ok:
        ok_exact.setdefault(tasks[a], []).append(a)
    ok_toks = [(a, set(_TOKEN.findall(tasks[a].lower()))) for a in ok]

    exact = sum(1 for a in failed if tasks[a] in ok_exact)
    jacc = 0
    for a in failed:
        ft = set(_TOKEN.findall(tasks[a].lower()))
        if not ft:
            continue
        best = max((len(ft & st) / len(ft | st) for _, st in ok_toks if st),
                   default=0.0)
        if best >= 0.5:
            jacc += 1
    return {
        "n_failed_with_task": len(failed),
        "n_success_with_task": len(ok),
        "exact_task_pair_coverage": exact / len(failed) if failed else None,
        "jaccard_ge_0_5_pair_coverage": jacc / len(failed) if failed else None,
        "n_exact": exact, "n_jaccard": jacc,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="kaos.db")
    args = ap.parse_args()
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    results = {
        "db": args.db,
        "M1_arg_entropy": m1_arg_entropy(conn),
        "M2_signal_density": m2_signal_density(conn),
        "M3_task_anchoring": m3_anchoring(conn),
        "M4_expert_availability": m4_expert_availability(conn),
    }
    conn.close()
    slim = json.loads(json.dumps(results))
    slim["M1_arg_entropy"].pop("per_agent")
    print(json.dumps(slim, indent=2))
    OUT.write_text(json.dumps(results, indent=2))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
