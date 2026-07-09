"""v0.10 plasticity-loop-closure (RED-FIRST).

The v0.10 panel found the neuroplasticity substrate is DARK for the primary
agent surface: the MCP agent_memory_search tool never passes record_hits/
requesting_agent_id, so memory_hits stays empty, the Hebbian association
rebuild finds nothing, and plasticity-weighted ranking / promotions can never
fire from real MCP-driven agent activity. Also: deprecated skills are never
filtered out of skill search/list.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from kaos import Kaos
from kaos.memory import MemoryStore
from kaos.mcp.server import call_tool, init_server


@pytest.fixture
def mcp(tmp_path: Path):
    afs = Kaos(db_path=str(tmp_path / "kaos.db"))
    init_server(afs, None)  # type: ignore[arg-type]
    yield afs
    afs.close()


def _call(name, args):
    res = asyncio.run(call_tool(name, args))
    return res[0].text


class TestMcpMemorySearchFeedsPlasticity:
    def test_search_records_memory_hits(self, mcp):
        a = mcp.spawn("agent")
        mem = MemoryStore(mcp.conn)
        mem.write(a, "retrieval augmentation planner verifier", type="insight")
        mem.write(a, "checkpoint restore blob journal", type="result")

        before = mcp.conn.execute("SELECT COUNT(*) FROM memory_hits").fetchone()[0]
        out = _call("agent_memory_search",
                    {"query": "retrieval planner", "requesting_agent_id": a})
        assert not out.startswith("Error:"), out
        after = mcp.conn.execute("SELECT COUNT(*) FROM memory_hits").fetchone()[0]
        assert after > before, (
            "MCP agent_memory_search did not record memory_hits — "
            "the neuroplasticity loop is dark for the MCP surface"
        )

    def test_recorded_hit_carries_requesting_agent(self, mcp):
        a = mcp.spawn("consumer")
        mem = MemoryStore(mcp.conn)
        mem.write(mcp.spawn("producer"), "hebbian consolidation dream skill")
        _call("agent_memory_search",
              {"query": "hebbian dream", "requesting_agent_id": a})
        rows = mcp.conn.execute(
            "SELECT agent_id FROM memory_hits WHERE agent_id = ?", (a,)
        ).fetchall()
        assert rows, "requesting_agent_id not threaded into memory_hits"

    def test_schema_exposes_requesting_agent_id(self):
        from kaos.mcp.server import build_tool_list
        tool = next(t for t in build_tool_list() if t.name == "agent_memory_search")
        assert "requesting_agent_id" in tool.inputSchema["properties"], (
            "agent_memory_search schema must let callers attribute the hit"
        )


class TestDeprecatedSkillsFiltered:
    def test_deprecated_skill_excluded_from_search(self, mcp):
        from kaos.skills import SkillStore
        store = SkillStore(mcp.conn)
        good = store.save(name="live-skill",
                          description="retrieval augmentation planner",
                          template="do X", tags=["search"])
        dead = store.save(name="dead-skill",
                          description="retrieval augmentation planner",
                          template="do Y", tags=["search"])
        # Deprecate the second one.
        mcp.conn.execute(
            "UPDATE agent_skills SET deprecated = 1 WHERE skill_id = ?", (dead,)
        )
        mcp.conn.commit()

        results = store.search("retrieval planner", limit=10)
        ids = {r.skill_id for r in results}
        assert good in ids, "live skill missing from search"
        assert dead not in ids, (
            "deprecated skill still returned by search — prune/merge is cosmetic"
        )

    def test_include_deprecated_escape_hatch(self, mcp):
        from kaos.skills import SkillStore
        store = SkillStore(mcp.conn)
        dead = store.save(name="dead", description="unique dead marker phrase",
                          template="t", tags=[])
        mcp.conn.execute(
            "UPDATE agent_skills SET deprecated = 1 WHERE skill_id = ?", (dead,)
        )
        mcp.conn.commit()
        got = store.search("unique dead marker", limit=10, include_deprecated=True)
        assert any(r.skill_id == dead for r in got)
