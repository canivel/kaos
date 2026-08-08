"""v0.10 — mh_search defect fixes + PSI infra, surfaced by the Sara/lenz panel.

Covers, all without any LLM call:
  - rationale restoration in the single-shot proposer path (record-only)
  - dead archive-tool apparatus removed (ProposerAgent has no .ccr; prompt no
    longer advertises tools it then disables)
  - experiments-journal wiring for completed searches (family=mh_search)
  - the read-only `kaos mh stats` PSI surface (bootstrap CIs; behavior-neutral)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaos import Kaos
from kaos.metaharness.proposer import ProposerAgent
from kaos.metaharness.pareto import ParetoFrontier, ParetoPoint
from kaos.metaharness.search import MetaHarnessSearch, SearchResult
from kaos.metaharness.harness import SearchConfig
from kaos.metaharness.stats import compute_search_stats


# ── rationale restoration ───────────────────────────────────────────

class TestRationaleRestoration:
    def test_hypothesis_comment_captured(self):
        block = "# HYPOTHESIS: batch the tool calls to cut context cost\ndef run(problem):\n    return {}"
        assert ProposerAgent._extract_rationale(block, "") == \
            "batch the tool calls to cut context cost"

    def test_preceding_prose_fallback(self):
        block = "def run(problem):\n    return {}"
        preceding = "I think adding a verifier step will help.\n\n"
        assert ProposerAgent._extract_rationale(block, preceding) == \
            "I think adding a verifier step will help."

    def test_no_rationale_marker_not_placeholder(self):
        r = ProposerAgent._extract_rationale("def run(problem):\n    return {}", "")
        assert r == "(no rationale stated by proposer)"
        assert "extracted from plain text" not in r

    def test_extract_from_text_records_real_rationale(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sa = afs.spawn("meta-harness-search")
        p = ProposerAgent(afs, router=None, search_agent_id=sa)
        convo = [{"role": "assistant", "content": (
            "Here is my plan.\n\n"
            "```python\n# HYPOTHESIS: cache the classifier prompt\n"
            "def run(problem):\n    return {'accuracy': 1.0}\n```\n"
        )}]
        p._extract_from_text(convo, max_candidates=1)
        assert len(p._submitted) == 1
        assert p._submitted[0].metadata["rationale"] == "cache the classifier prompt"
        afs.close()


# ── dead tool apparatus removed ─────────────────────────────────────

class TestDeadToolsRemoved:
    def test_proposer_has_no_ccr(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sa = afs.spawn("meta-harness-search")
        p = ProposerAgent(afs, router=None, search_agent_id=sa)
        assert not hasattr(p, "ccr"), "dead CCR apparatus still constructed"
        for gone in ("_register_archive_tools", "_ls_archive", "_submit_harness"):
            assert not hasattr(p, gone), f"{gone} should have been removed"
        afs.close()

    def test_prompt_does_not_advertise_disabled_tools(self):
        from kaos.metaharness.prompts import build_proposer_prompt
        prompt = build_proposer_prompt(
            iteration=1, n_candidates=1, benchmark_name="fake",
            objective_summary="accuracy (maximize)", frontier_summary="(empty)",
        )
        assert "mh_submit_harness" not in prompt
        assert "## Available Tools" not in prompt


# ── experiments journal wiring ──────────────────────────────────────

def _search(tmp_path) -> MetaHarnessSearch:
    afs = Kaos(db_path=str(tmp_path / "kaos.db"))
    cfg = SearchConfig(benchmark="text_classify", objectives=["+accuracy", "-context_cost"])
    s = MetaHarnessSearch(afs, router=None, benchmark=None, config=cfg)
    s.search_agent_id = afs.spawn("meta-harness-search")
    return s


class TestJournalWiring:
    def test_completed_search_logs_mh_search_row(self, tmp_path):
        s = _search(tmp_path)
        fr = ParetoFrontier(
            points=[ParetoPoint("h0", {"accuracy": 0.8, "context_cost": 12.0})],
            objectives={"accuracy": "maximize", "context_cost": "minimize"},
        )
        result = SearchResult(s.search_agent_id, fr, [], 1, 3.5, 1)
        s._log_to_journal(result)
        s.afs.close()

        from kaos.experiments import ExperimentStore
        with ExperimentStore(str(tmp_path / "kaos.db")) as store:
            rows = store.list(family="mh_search")
        assert len(rows) == 1
        assert rows[0].name == "text_classify"

    def test_memory_db_is_noop(self):
        afs = Kaos(db_path=":memory:")
        cfg = SearchConfig(benchmark="text_classify", objectives=["+accuracy"])
        s = MetaHarnessSearch(afs, router=None, benchmark=None, config=cfg)
        s.search_agent_id = afs.spawn("meta-harness-search")
        fr = ParetoFrontier(points=[], objectives={})
        # must not raise
        s._log_to_journal(SearchResult(s.search_agent_id, fr, [], 0, 0.1, 0))
        afs.close()


# ── PSI read-only stats surface ─────────────────────────────────────

def _seed_archive(afs, sa):
    """Two harnesses: incumbent all-correct, challenger half-correct."""
    obj = {"accuracy": "maximize", "context_cost": "minimize"}
    afs.write(sa, "/pareto/frontier.json", json.dumps({
        "objectives": obj,
        "points": [{"harness_id": "inc", "scores": {"accuracy": 1.0, "context_cost": 5.0}}],
    }).encode())
    for hid, labels, acc in (("inc", [1] * 10, 1.0), ("chal", [1, 0] * 5, 0.5)):
        afs.write(sa, f"/harnesses/{hid}/scores.json",
                  json.dumps({"accuracy": acc, "context_cost": 5.0}).encode())
        afs.write(sa, f"/harnesses/{hid}/per_problem.jsonl",
                  ("\n".join(json.dumps({"problem_id": i, "correct": bool(v)})
                            for i, v in enumerate(labels))).encode())


class TestPSIStats:
    def test_incumbent_and_ci(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sa = afs.spawn("meta-harness-search")
        _seed_archive(afs, sa)
        stats = compute_search_stats(afs, sa)
        assert stats.incumbent_id == "inc"
        chal = next(c for c in stats.candidates if c.harness_id == "chal")
        assert chal.mean_diff is not None and chal.mean_diff < 0  # worse than incumbent
        inc = next(c for c in stats.candidates if c.harness_id == "inc")
        assert inc.is_incumbent and inc.mean_diff is None
        afs.close()

    def test_stats_is_read_only(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sa = afs.spawn("meta-harness-search")
        _seed_archive(afs, sa)
        before = {f["path"] for f in afs.ls(sa, "/harnesses/inc")}
        n_before = len(afs.ls(sa, "/harnesses"))
        compute_search_stats(afs, sa)
        after = {f["path"] for f in afs.ls(sa, "/harnesses/inc")}
        assert before == after and len(afs.ls(sa, "/harnesses")) == n_before
        afs.close()

    def test_underpowered_archive_notes_not_crashes(self, tmp_path):
        afs = Kaos(db_path=str(tmp_path / "kaos.db"))
        sa = afs.spawn("meta-harness-search")
        # frontier but no per_problem labels
        afs.write(sa, "/pareto/frontier.json", json.dumps({
            "objectives": {"accuracy": "maximize"},
            "points": [{"harness_id": "inc", "scores": {"accuracy": 1.0}}],
        }).encode())
        afs.write(sa, "/harnesses/inc/scores.json", json.dumps({"accuracy": 1.0}).encode())
        stats = compute_search_stats(afs, sa)
        assert any("uncomputable" in n or "underpowered" in n for n in stats.notes)
        afs.close()
