"""Tests for cross-agent memory store (MemoryStore)."""

from __future__ import annotations

import pytest

from kaos.core import Kaos
from kaos.memory import MemoryStore, MemoryEntry, MEMORY_TYPES


@pytest.fixture
def afs(tmp_path):
    db_path = str(tmp_path / "test.db")
    fs = Kaos(db_path=db_path)
    yield fs
    fs.close()


@pytest.fixture
def mem(afs):
    return MemoryStore(afs.conn)


@pytest.fixture
def agent_id(afs):
    return afs.spawn("test-agent")


class TestMemoryWrite:
    def test_write_basic(self, mem, agent_id):
        mid = mem.write(agent_id=agent_id, content="Hello world")
        assert isinstance(mid, int)
        assert mid > 0

    def test_write_returns_incremental_ids(self, mem, agent_id):
        id1 = mem.write(agent_id=agent_id, content="first")
        id2 = mem.write(agent_id=agent_id, content="second")
        assert id2 > id1

    def test_write_all_types(self, mem, agent_id):
        for t in MEMORY_TYPES:
            mid = mem.write(agent_id=agent_id, content=f"content for {t}", type=t)
            entry = mem.get(mid)
            assert entry is not None
            assert entry.type == t

    def test_write_invalid_type_raises(self, mem, agent_id):
        with pytest.raises(ValueError, match="type must be one of"):
            mem.write(agent_id=agent_id, content="x", type="invalid")

    def test_write_with_key(self, mem, agent_id):
        mid = mem.write(agent_id=agent_id, content="keyed entry", key="my-key")
        entry = mem.get(mid)
        assert entry.key == "my-key"

    def test_write_with_metadata(self, mem, agent_id):
        meta = {"score": 0.87, "iteration": 3}
        mid = mem.write(agent_id=agent_id, content="with meta", metadata=meta)
        entry = mem.get(mid)
        assert entry.metadata["score"] == 0.87
        assert entry.metadata["iteration"] == 3


class TestMemoryGet:
    def test_get_existing(self, mem, agent_id):
        mid = mem.write(agent_id=agent_id, content="fetchable")
        entry = mem.get(mid)
        assert entry is not None
        assert isinstance(entry, MemoryEntry)
        assert entry.content == "fetchable"
        assert entry.agent_id == agent_id

    def test_get_missing_returns_none(self, mem):
        assert mem.get(99999) is None

    def test_get_by_key(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="old", key="shared-key")
        mem.write(agent_id=agent_id, content="new", key="shared-key")
        entry = mem.get_by_key("shared-key")
        assert entry is not None
        assert entry.content == "new"  # most recent

    def test_get_by_key_with_agent_filter(self, afs, mem):
        agent_a = afs.spawn("agent-a")
        agent_b = afs.spawn("agent-b")
        mem.write(agent_id=agent_a, content="from-a", key="k1")
        mem.write(agent_id=agent_b, content="from-b", key="k1")
        entry = mem.get_by_key("k1", agent_id=agent_a)
        assert entry.content == "from-a"


class TestMemoryList:
    def test_list_all(self, mem, agent_id):
        for i in range(5):
            mem.write(agent_id=agent_id, content=f"entry {i}")
        entries = mem.list()
        assert len(entries) >= 5

    def test_list_most_recent_first(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="first")
        mem.write(agent_id=agent_id, content="second")
        entries = mem.list(agent_id=agent_id)
        assert entries[0].content == "second"

    def test_list_filter_by_agent(self, afs, mem):
        a1 = afs.spawn("agent-1")
        a2 = afs.spawn("agent-2")
        mem.write(agent_id=a1, content="from 1")
        mem.write(agent_id=a2, content="from 2")
        entries = mem.list(agent_id=a1)
        assert all(e.agent_id == a1 for e in entries)

    def test_list_filter_by_type(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="obs", type="observation")
        mem.write(agent_id=agent_id, content="res", type="result")
        entries = mem.list(type="result")
        assert all(e.type == "result" for e in entries)

    def test_list_limit(self, mem, agent_id):
        for i in range(10):
            mem.write(agent_id=agent_id, content=f"entry {i}")
        entries = mem.list(limit=3)
        assert len(entries) == 3

    def test_list_offset(self, mem, agent_id):
        for i in range(5):
            mem.write(agent_id=agent_id, content=f"entry {i}")
        all_entries = mem.list(agent_id=agent_id)
        paged = mem.list(agent_id=agent_id, offset=2, limit=2)
        assert paged[0].memory_id == all_entries[2].memory_id


class TestMemorySearch:
    def test_search_basic(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="ensemble voting improved accuracy")
        mem.write(agent_id=agent_id, content="chain of thought reasoning")
        hits = mem.search("ensemble accuracy")
        assert len(hits) > 0
        assert any("ensemble" in h.content for h in hits)

    def test_search_porter_stemming(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="accuracy improved significantly")
        # stemmed: "accur" matches "accuraci" etc.
        hits = mem.search("improving")
        assert len(hits) > 0

    def test_search_no_results(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="hello world")
        hits = mem.search("xyzzy12345nonexistent")
        assert hits == []

    def test_search_filter_by_type(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="error in ensemble", type="error")
        mem.write(agent_id=agent_id, content="ensemble result", type="result")
        hits = mem.search("ensemble", type="result")
        assert all(h.type == "result" for h in hits)

    def test_search_filter_by_agent(self, afs, mem):
        a1 = afs.spawn("search-agent-1")
        a2 = afs.spawn("search-agent-2")
        mem.write(agent_id=a1, content="found in agent one search")
        mem.write(agent_id=a2, content="found in agent two search")
        hits = mem.search("found", agent_id=a1)
        assert all(h.agent_id == a1 for h in hits)

    def test_search_relevance_order(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="accuracy accuracy accuracy", type="result")
        mem.write(agent_id=agent_id, content="accuracy", type="result")
        hits = mem.search("accuracy", limit=2)
        # BM25 should rank the triple-mention higher
        assert hits[0].content.count("accuracy") >= hits[1].content.count("accuracy")

    def test_search_limit(self, mem, agent_id):
        for i in range(10):
            mem.write(agent_id=agent_id, content=f"searchable content {i}")
        hits = mem.search("searchable", limit=3)
        assert len(hits) <= 3

    def test_search_key_indexed(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="content", key="my-ensemble-key")
        hits = mem.search("ensemble")
        assert len(hits) > 0


class TestMemoryDelete:
    def test_delete_existing(self, mem, agent_id):
        mid = mem.write(agent_id=agent_id, content="to delete")
        assert mem.delete(mid) is True
        assert mem.get(mid) is None

    def test_delete_removes_from_fts(self, mem, agent_id):
        mid = mem.write(agent_id=agent_id, content="unique phrase xyzzy delete")
        mem.delete(mid)
        hits = mem.search("xyzzy delete")
        assert all(h.memory_id != mid for h in hits)

    def test_delete_missing_returns_false(self, mem):
        assert mem.delete(99999) is False


class TestMemoryStats:
    def test_stats_empty(self, mem):
        stats = mem.stats()
        assert stats["total"] == 0
        assert stats["by_type"] == {}

    def test_stats_counts(self, mem, agent_id):
        mem.write(agent_id=agent_id, content="obs", type="observation")
        mem.write(agent_id=agent_id, content="obs2", type="observation")
        mem.write(agent_id=agent_id, content="res", type="result")
        stats = mem.stats()
        assert stats["total"] == 3
        assert stats["by_type"]["observation"] == 2
        assert stats["by_type"]["result"] == 1


class TestMemoryToDict:
    def test_to_dict_has_all_fields(self, mem, agent_id):
        mid = mem.write(agent_id=agent_id, content="test", key="k", type="skill",
                        metadata={"x": 1})
        entry = mem.get(mid)
        d = entry.to_dict()
        assert d["memory_id"] == mid
        assert d["agent_id"] == agent_id
        assert d["type"] == "skill"
        assert d["key"] == "k"
        assert d["content"] == "test"
        assert d["metadata"] == {"x": 1}
        assert "created_at" in d

    def test_fts_trigger_on_update(self, mem, agent_id):
        """FTS update trigger keeps index in sync."""
        mid = mem.write(agent_id=agent_id, content="initial phrase")
        mem._conn.execute(
            "UPDATE memory SET content = 'updated phrase' WHERE memory_id = ?", (mid,)
        )
        mem._conn.commit()
        hits = mem.search("updated")
        assert any(h.memory_id == mid for h in hits)
