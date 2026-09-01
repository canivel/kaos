"""The four pre-registered arms. Each maps a failed Episode to a
predicted decisive call_id. Arms NEVER see ground truth or family labels
— except L1, which receives family labels solely to EXCLUDE the correct
family (the wrong-pair lesion, per the lock).
"""

from __future__ import annotations

import random
import sqlite3

from kaos.dream.phases.localize import localize

from demo_graphdiff_localizer_bench.graphdiff import bm25_pair, gdl_predict
from demo_graphdiff_localizer_bench.workload import SEED, Episode


def _calls(conn: sqlite3.Connection, agent_id: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT call_id FROM tool_calls WHERE agent_id = ? "
        "ORDER BY started_at, call_id", (agent_id,)).fetchall()]


def arm_b0(conn: sqlite3.Connection, ep: Episode, _s) -> str:
    rng = random.Random(f"{SEED}:{ep.agent_id}")
    return rng.choice(_calls(conn, ep.agent_id))


def arm_b1(conn: sqlite3.Connection, ep: Episode, _s) -> str:
    """v0.8.3 native heuristic localizer, single trajectory, no LLM.

    localize() returns None when no step errors (the silent-branch blind
    spot) — coverage fallback: predict the last call. It may also return
    a log-step (tool_call_id None); same fallback applies.
    """
    cs = localize(conn, ep.agent_id, llm_call_fn=None, persist=False)
    if cs is not None and cs.tool_call_id is not None:
        return cs.tool_call_id
    return _calls(conn, ep.agent_id)[-1]


def arm_full(conn: sqlite3.Connection, ep: Episode, successes: list[Episode]) -> str:
    pool = [(s.agent_id, s.task) for s in successes]
    paired = bm25_pair(ep.task, pool)
    if paired is None:
        return _calls(conn, ep.agent_id)[-1]
    return gdl_predict(conn, ep.agent_id, paired)


def arm_l1(conn: sqlite3.Connection, ep: Episode, successes: list[Episode]) -> str:
    """Wrong-pair lesion: seeded-random success from OTHER families."""
    rng = random.Random(f"{SEED}:L1:{ep.agent_id}")
    others = [s for s in successes if s.family != ep.family]
    paired = rng.choice(others)
    return gdl_predict(conn, ep.agent_id, paired.agent_id)


def pairing_same_family_rate(
    conn: sqlite3.Connection, failed: list[Episode], successes: list[Episode],
) -> float:
    """G4 metric — mechanical, generator family labels as ground truth."""
    fam_of = {s.agent_id: s.family for s in successes}
    pool = [(s.agent_id, s.task) for s in successes]
    hits = sum(
        1 for ep in failed
        if (p := bm25_pair(ep.task, pool)) is not None and fam_of[p] == ep.family
    )
    return hits / len(failed) if failed else 0.0
