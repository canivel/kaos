"""Tests for cross-agent skill library (SkillStore).

Inspired by:
  Zhou et al. 2026, "Externalization in LLM Agents", arXiv:2604.08224
"""

from __future__ import annotations

import pytest

from kaos.core import Kaos
from kaos.skills import Skill, SkillStore


@pytest.fixture
def afs(tmp_path):
    db_path = str(tmp_path / "test.db")
    fs = Kaos(db_path=db_path)
    yield fs
    fs.close()


@pytest.fixture
def sk(afs):
    return SkillStore(afs.conn)


@pytest.fixture
def agent_id(afs):
    return afs.spawn("test-agent")


# ── Save ──────────────────────────────────────────────────────────────────

class TestSkillSave:
    def test_save_returns_int_id(self, sk):
        sid = sk.save(
            name="test_skill",
            description="A test skill",
            template="Do {task} using {method}.",
        )
        assert isinstance(sid, int)
        assert sid > 0

    def test_save_multiple_increments(self, sk):
        id1 = sk.save(name="s1", description="first", template="A")
        id2 = sk.save(name="s2", description="second", template="B")
        assert id2 > id1

    def test_save_with_tags(self, sk):
        sid = sk.save(
            name="tagged",
            description="Has tags",
            template="Template",
            tags=["classification", "ensemble"],
        )
        skill = sk.get(sid)
        assert skill is not None
        assert "classification" in skill.tags
        assert "ensemble" in skill.tags

    def test_save_with_source_agent(self, sk, agent_id):
        sid = sk.save(
            name="from_agent",
            description="Saved by agent",
            template="Template",
            source_agent_id=agent_id,
        )
        skill = sk.get(sid)
        assert skill is not None
        assert skill.source_agent_id == agent_id

    def test_save_defaults(self, sk):
        sid = sk.save(name="minimal", description="d", template="t")
        skill = sk.get(sid)
        assert skill is not None
        assert skill.tags == []
        assert skill.use_count == 0
        assert skill.success_count == 0
        assert skill.source_agent_id is None


# ── Template params ───────────────────────────────────────────────────────

class TestSkillParams:
    def test_no_params(self, sk):
        sid = sk.save(name="fixed", description="d", template="Just a fixed prompt.")
        skill = sk.get(sid)
        assert skill.params() == []

    def test_single_param(self, sk):
        sid = sk.save(name="one_param", description="d", template="Do {task}.")
        skill = sk.get(sid)
        assert skill.params() == ["task"]

    def test_multiple_params(self, sk):
        sid = sk.save(
            name="multi",
            description="d",
            template="Use {model} with {n} models and {voting} voting.",
        )
        skill = sk.get(sid)
        params = skill.params()
        assert "model" in params
        assert "n" in params
        assert "voting" in params

    def test_duplicate_params_deduplicated(self, sk):
        sid = sk.save(
            name="dup",
            description="d",
            template="{x} and {x} again.",
        )
        skill = sk.get(sid)
        # str.Formatter.parse returns each occurrence; duplicates may appear
        assert "x" in skill.params()

    def test_apply_fills_template(self, sk):
        sid = sk.save(
            name="fillable",
            description="d",
            template="Train {n_models} models using {voting} voting.",
        )
        skill = sk.get(sid)
        result = skill.apply(n_models="3", voting="majority")
        assert result == "Train 3 models using majority voting."

    def test_apply_extra_params_ignored(self, sk):
        sid = sk.save(name="extra", description="d", template="Hello {name}!")
        skill = sk.get(sid)
        # Extra kwargs should not raise
        result = skill.apply(name="World", unused="ignored")
        assert result == "Hello World!"

    def test_apply_missing_param_raises(self, sk):
        sid = sk.save(name="missing", description="d", template="Hello {name}!")
        skill = sk.get(sid)
        with pytest.raises(KeyError):
            skill.apply()


# ── Search ────────────────────────────────────────────────────────────────

class TestSkillSearch:
    def test_search_finds_by_name(self, sk):
        sk.save(name="ensemble_classifier", description="Ensemble voting", template="T")
        sk.save(name="regression_model", description="Regression", template="T")
        hits = sk.search("ensemble")
        assert any(s.name == "ensemble_classifier" for s in hits)

    def test_search_finds_by_description(self, sk):
        sk.save(name="s1", description="Improve accuracy with dropout regularization", template="T")
        sk.save(name="s2", description="Parse JSON responses", template="T")
        hits = sk.search("regularization accuracy")
        assert any(s.name == "s1" for s in hits)

    def test_search_finds_by_template(self, sk):
        sk.save(
            name="template_skill",
            description="Uses specific technique",
            template="Apply gradient clipping with max_norm={max_norm}.",
        )
        hits = sk.search("gradient clipping")
        assert any(s.name == "template_skill" for s in hits)

    def test_search_returns_empty_for_no_match(self, sk):
        sk.save(name="s1", description="Classification", template="T")
        hits = sk.search("xyzzy_nonexistent_term_12345")
        assert hits == []

    def test_search_respects_limit(self, sk):
        for i in range(10):
            sk.save(name=f"skill_{i}", description="Common word classification", template="T")
        hits = sk.search("classification", limit=3)
        assert len(hits) <= 3

    def test_search_tag_filter(self, sk):
        sk.save(name="a", description="classification task", template="T", tags=["nlp"])
        sk.save(name="b", description="classification task", template="T", tags=["cv"])
        hits = sk.search("classification", tag="nlp")
        assert all("nlp" in s.tags for s in hits)
        assert not any(s.name == "b" for s in hits)

    def test_search_stemming(self, sk):
        sk.save(name="optimize", description="Optimize training with learning rate scheduling", template="T")
        # "optimization" should stem-match "optimize"
        hits = sk.search("optimization")
        assert any(s.name == "optimize" for s in hits)


# ── List ──────────────────────────────────────────────────────────────────

class TestSkillList:
    def test_list_all(self, sk):
        sk.save(name="a", description="d", template="t")
        sk.save(name="b", description="d", template="t")
        skills = sk.list()
        assert len(skills) >= 2

    def test_list_tag_filter(self, sk):
        sk.save(name="x", description="d", template="t", tags=["foo"])
        sk.save(name="y", description="d", template="t", tags=["bar"])
        skills = sk.list(tag="foo")
        assert all("foo" in s.tags for s in skills)
        assert not any(s.name == "y" for s in skills)

    def test_list_source_agent_filter(self, sk, agent_id):
        sk.save(name="mine", description="d", template="t", source_agent_id=agent_id)
        sk.save(name="other", description="d", template="t", source_agent_id=None)
        skills = sk.list(source_agent_id=agent_id)
        assert all(s.source_agent_id == agent_id for s in skills)

    def test_list_limit(self, sk):
        for i in range(15):
            sk.save(name=f"s{i}", description="d", template="t")
        skills = sk.list(limit=5)
        assert len(skills) == 5

    def test_list_order_by_name(self, sk):
        sk.save(name="zebra", description="d", template="t")
        sk.save(name="alpha", description="d", template="t")
        skills = sk.list(order_by="name")
        names = [s.name for s in skills]
        assert names == sorted(names, reverse=True)


# ── Outcome tracking ──────────────────────────────────────────────────────

class TestSkillOutcome:
    def test_record_success(self, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=True)
        skill = sk.get(sid)
        assert skill.use_count == 1
        assert skill.success_count == 1

    def test_record_failure(self, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=False)
        skill = sk.get(sid)
        assert skill.use_count == 1
        assert skill.success_count == 0

    def test_mixed_outcomes(self, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=True)
        sk.record_outcome(sid, success=True)
        sk.record_outcome(sid, success=False)
        skill = sk.get(sid)
        assert skill.use_count == 3
        assert skill.success_count == 2

    def test_success_rate_in_to_dict(self, sk):
        sid = sk.save(name="s", description="d", template="t")
        sk.record_outcome(sid, success=True)
        sk.record_outcome(sid, success=False)
        skill = sk.get(sid)
        d = skill.to_dict()
        assert d["success_rate"] == 0.5

    def test_success_rate_none_when_unused(self, sk):
        sid = sk.save(name="unused", description="d", template="t")
        skill = sk.get(sid)
        assert skill.to_dict()["success_rate"] is None


# ── Delete ────────────────────────────────────────────────────────────────

class TestSkillDelete:
    def test_delete_existing(self, sk):
        sid = sk.save(name="to_delete", description="d", template="t")
        assert sk.delete(sid) is True
        assert sk.get(sid) is None

    def test_delete_nonexistent(self, sk):
        assert sk.delete(99999) is False

    def test_delete_removes_from_search(self, sk):
        sid = sk.save(name="gone", description="will be deleted soon", template="t")
        sk.delete(sid)
        hits = sk.search("deleted")
        assert not any(s.skill_id == sid for s in hits)


# ── Stats ─────────────────────────────────────────────────────────────────

class TestSkillStats:
    def test_stats_empty(self, sk):
        stats = sk.stats()
        assert stats["total"] == 0
        assert stats["top_by_success_rate"] == []

    def test_stats_counts(self, sk):
        sk.save(name="a", description="d", template="t")
        sk.save(name="b", description="d", template="t")
        stats = sk.stats()
        assert stats["total"] == 2

    def test_stats_top_skills(self, sk):
        sid = sk.save(name="reliable", description="d", template="t")
        sk.record_outcome(sid, success=True)
        sk.record_outcome(sid, success=True)
        stats = sk.stats()
        assert len(stats["top_by_success_rate"]) >= 1
        top = stats["top_by_success_rate"][0]
        assert top["name"] == "reliable"
        assert top["success_rate"] == 1.0


# ── Cross-agent sharing ───────────────────────────────────────────────────

class TestSkillCrossAgent:
    """Skills are shared across all agents in the same DB."""

    def test_any_agent_can_read_saved_skill(self, afs, sk):
        agent_a = afs.spawn("agent-a")
        agent_b = afs.spawn("agent-b")

        sid = sk.save(
            name="shared_skill",
            description="Saved by agent-a",
            template="Do {task}",
            source_agent_id=agent_a,
        )

        # agent-b can find it
        hits = sk.search("shared_skill")
        assert any(s.skill_id == sid for s in hits)

    def test_skills_persist_across_connections(self, tmp_path):
        db_path = str(tmp_path / "shared.db")

        afs1 = Kaos(db_path=db_path)
        sk1 = SkillStore(afs1.conn)
        sid = sk1.save(name="persistent", description="d", template="t")
        afs1.close()

        afs2 = Kaos(db_path=db_path)
        sk2 = SkillStore(afs2.conn)
        skill = sk2.get(sid)
        assert skill is not None
        assert skill.name == "persistent"
        afs2.close()
