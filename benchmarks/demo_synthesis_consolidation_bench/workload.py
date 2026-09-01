"""Organic workload — runs the incident world through REAL KAOS memory.

Co-retrieval is genuine: before writing an incident's memories the
handling agent searches memory (record_hits=True), which fires KAOS's
inline Hebbian hook and forms associations between co-retrieved incident
memories. Clusters are therefore DISCOVERED from retrieval dynamics, not
hand-placed (lock: episodic_memory_is_organic).

This module does NOT import the synthesis feature.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

os.environ.setdefault("KAOS_DREAM_THRESHOLD", "100000000")  # no auto-dream

from kaos import Kaos
from kaos.memory import MemoryStore

import re as _re

from world import Incident, generate_world

_FTS = _re.compile(r"[^\w\s]+")


def _fts_or(text: str) -> str:
    """OR-join sanitized tokens — robust against FTS5 hyphen/phrase
    pitfalls (same fix used in demo_realistic_retrieval_bench)."""
    toks = [t for t in _FTS.sub(" ", text).lower().split() if len(t) > 2]
    return " OR ".join(toks) if toks else text


@dataclass
class WorkloadIndex:
    db_path: str
    # incident id -> {"obs": mid, "err": mid, "result": mid}
    inc_mem: dict[int, dict[str, int]] = field(default_factory=dict)
    incidents: list[Incident] = field(default_factory=list)
    # memory_id -> text (for the judge's token-containment check)
    mem_text: dict[int, str] = field(default_factory=dict)
    # domain -> list of incident ids (non-distractor only)
    domain_incs: dict[str, list[int]] = field(default_factory=dict)


def build_workload(db_path: str, seed: int, *, days: int = 90,
                   incidents_per_day: int = 6) -> WorkloadIndex:
    p = Path(db_path)
    if p.exists():
        p.unlink()
    kaos = Kaos(db_path=db_path)
    mem = MemoryStore(kaos.conn)
    incidents = generate_world(seed, days=days,
                               incidents_per_day=incidents_per_day)
    idx = WorkloadIndex(db_path=db_path, incidents=incidents)
    try:
        for inc in incidents:
            agent = kaos.spawn(f"ir-{inc.iid}")
            # GENUINE co-retrieval: the agent looks for prior similar
            # incidents using vocabulary that actually appears in episode
            # text (service + symptom). Same-service / same-symptom
            # incidents co-retrieve -> clusters EMERGE from retrieval
            # dynamics, not from any hand-placed boundary.
            probe = _fts_or(f"{inc.service} {inc.symptom}")
            try:
                mem.search(probe, limit=8, rank="weighted",
                           record_hits=True, requesting_agent_id=agent)
            except Exception:
                pass
            o = mem.write(agent_id=agent, content=inc.obs_text,
                          type="observation", key=f"inc{inc.iid}-obs")
            e = mem.write(agent_id=agent, content=inc.err_text,
                          type="error", key=f"inc{inc.iid}-err")
            # tail detail lives only in the result memory of this incident
            r = mem.write(
                agent_id=agent,
                content=inc.result_text + f" detail {inc.tail_detail}",
                type="result", key=f"inc{inc.iid}-res")
            idx.inc_mem[inc.iid] = {"obs": o, "err": e, "result": r}
            idx.mem_text[o] = inc.obs_text
            idx.mem_text[e] = inc.err_text
            idx.mem_text[r] = inc.result_text + f" detail {inc.tail_detail}"
            if not inc.is_distractor:
                idx.domain_incs.setdefault(inc.domain, []).append(inc.iid)
            # KAOS's REAL offline Hebbian rebuild (what threshold-triggered
            # consolidation / `kaos dream` does). Associations are a
            # sleep-phase artifact by design, not an inline one.
            from kaos.dream.auto import rebuild_associations_for_agent
            try:
                rebuild_associations_for_agent(kaos.conn, agent)
            except Exception:
                pass
    finally:
        kaos.close()
    return idx
