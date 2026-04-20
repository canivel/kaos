"""Tests for the Obsidian vault exporter."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kaos.core import Kaos
from kaos.memory import MemoryStore
from kaos.obsidian import VaultExporter
from kaos.obsidian.renderer import (
    bullet_list,
    code_block,
    frontmatter,
    safe_filename,
    short_id,
    tag_list,
    wikilink,
)
from kaos.obsidian.templates import (
    render_agent,
    render_checkpoint,
    render_index,
    render_log_entry,
    render_memory,
    render_skill,
)
from kaos.skills import SkillStore


# ── Renderer helpers ────────────────────────────────────────────────


class TestSafeFilename:
    def test_passthrough_for_normal_name(self):
        assert safe_filename("fraud-agent") == "fraud-agent"

    @pytest.mark.parametrize("bad,good", [
        ("a/b", "a-b"),
        ("a:b", "a-b"),
        ("a?b", "a-b"),
        ("a|b|c", "a-b-c"),
        ("a[b]", "a-b"),
        ("a#b", "a-b"),
        ("name with spaces", "name with spaces"),  # spaces OK in Obsidian
    ])
    def test_unsafe_chars_replaced(self, bad, good):
        assert safe_filename(bad) == good

    def test_empty_returns_placeholder(self):
        assert safe_filename("") == "unnamed"
        assert safe_filename("  ") == "unnamed"

    def test_collapses_multiple_dashes(self):
        assert safe_filename("a//b//c") == "a-b-c"


class TestWikilink:
    def test_plain_link(self):
        assert wikilink("fraud-agent") == "[[fraud-agent]]"

    def test_aliased_link(self):
        assert wikilink("fraud-agent", alias="Fraud Agent") == "[[fraud-agent|Fraud Agent]]"

    def test_same_alias_omitted(self):
        assert wikilink("fraud-agent", alias="fraud-agent") == "[[fraud-agent]]"

    def test_unsafe_target_sanitized(self):
        assert wikilink("path/to/thing") == "[[path-to-thing]]"


class TestFrontmatter:
    def test_basic_scalars(self):
        out = frontmatter({"name": "x", "age": 10, "active": True, "id": None})
        assert out.startswith("---\n")
        assert "name: x" in out
        assert "age: 10" in out
        assert "active: true" in out
        assert "id: null" in out
        assert out.rstrip().endswith("---")

    def test_list(self):
        out = frontmatter({"tags": ["a", "b", "c"]})
        assert "tags: [a, b, c]" in out

    def test_special_chars_quoted(self):
        out = frontmatter({"status": "running: paused"})
        assert '"running: paused"' in out

    def test_reserved_words_quoted(self):
        out = frontmatter({"flag": "yes"})
        assert '"yes"' in out

    def test_newlines_block_scalar(self):
        out = frontmatter({"desc": "line 1\nline 2"})
        assert "|-" in out
        assert "line 1" in out


class TestTagList:
    def test_strips_hashes_and_spaces(self):
        assert tag_list(["#foo", " bar ", "Baz Qux"]) == ["foo", "bar", "baz-qux"]

    def test_removes_empty(self):
        assert tag_list(["", "  ", None]) == []


class TestBulletList:
    def test_empty_uses_placeholder(self):
        assert bullet_list([]) == "_(none)_"

    def test_custom_empty(self):
        assert bullet_list([], empty="_nada_") == "_nada_"

    def test_items_bulleted(self):
        assert bullet_list(["one", "two"]) == "- one\n- two"


class TestCodeBlock:
    def test_normal_fence(self):
        out = code_block("x = 1", "python")
        assert out.startswith("```python\n")
        assert "x = 1" in out
        assert out.endswith("```")

    def test_inner_fence_escapes(self):
        out = code_block("print('```')", "python")
        assert out.startswith("````python\n")
        assert out.endswith("````")


class TestShortId:
    def test_last_n_chars(self):
        assert short_id("01KP922FCMMEWYJ6NASEPZ4E69", n=6) == "PZ4E69"

    def test_short_input_unchanged(self):
        assert short_id("abc") == "abc"


# ── Template rendering (pure functions, no DB) ──────────────────────


class TestRenderAgent:
    def test_basic(self):
        agent = {
            "agent_id": "01KTEST",
            "name": "fraud-agent",
            "status": "completed",
            "wave": 2,
            "created_at": "2026-04-20T10:00:00",
            "parent_id": None,
            "config_pretty": "{}",
        }
        links = {"skills": ["[[fraud-gbm]]"], "memories": ["[[fix-1]]"], "checkpoints": []}
        out = render_agent(agent, links)
        assert "# fraud-agent" in out
        assert "agent_id: 01KTEST" in out
        assert "wave-2" in out
        assert "[[fraud-gbm]]" in out
        assert "[[fix-1]]" in out
        assert "Wave 2" in out

    def test_no_wave(self):
        agent = {
            "agent_id": "01KTEST",
            "name": "x",
            "status": "running",
            "wave": None,
            "created_at": "2026-04-20T10:00:00",
            "parent_id": "",
            "config_pretty": "{}",
        }
        out = render_agent(agent, {"skills": [], "memories": [], "checkpoints": []})
        assert "Wave ?" in out
        assert "wave-" not in out.split("tags:")[1].split("---")[0]  # no wave tag in frontmatter


class TestRenderSkill:
    def test_basic_with_success_rate(self):
        skill = {
            "skill_id": 1,
            "name": "fastapi-gateway",
            "description": "A gateway skill",
            "template": "Build {project}",
            "tags_list": ["fastapi", "payments"],
            "source_agent_id": "01KTEST",
            "use_count": 4,
            "success_count": 3,
            "created_at": "2026-04-20T10:00:00",
            "updated_at": "2026-04-20T10:00:00",
        }
        links = {"source_agent": "[[fraud-agent]]", "applied_by": []}
        out = render_skill(skill, links)
        assert "# fastapi-gateway" in out
        assert "success rate: 75%" in out
        assert "[[fraud-agent]]" in out
        assert "Build {project}" in out

    def test_zero_uses_no_rate_shown(self):
        skill = {
            "skill_id": 1, "name": "x", "description": "d", "template": "t",
            "tags_list": [], "source_agent_id": None,
            "use_count": 0, "success_count": 0,
            "created_at": "2026-04-20T10:00:00",
            "updated_at": "2026-04-20T10:00:00",
        }
        out = render_skill(skill, {"source_agent": "", "applied_by": []})
        assert "success rate" not in out


class TestRenderMemory:
    def test_basic(self):
        entry = {
            "memory_id": 42,
            "type": "result",
            "key": "feast-cold-start-fix",
            "content": "Inject p50 risk as prior",
            "created_at": "2026-04-20T10:00:00",
            "metadata_pretty": "{}",
        }
        out = render_memory(entry, {"source_agent": "[[fraud-agent]]"})
        assert "# feast-cold-start-fix" in out
        assert "memory_id: 42" in out
        assert "Inject p50 risk as prior" in out
        assert "[[fraud-agent]]" in out

    def test_no_key_falls_back_to_id(self):
        entry = {
            "memory_id": 7, "type": "observation", "key": None,
            "content": "x", "created_at": "2026-04-20T10:00:00",
            "metadata_pretty": "{}",
        }
        out = render_memory(entry, {"source_agent": ""})
        assert "# memory-7" in out


class TestRenderLogEntry:
    def test_intent_formatting(self):
        entry = {
            "position": 3,
            "type": "intent",
            "agent_id": "01KSOMEAGENT",
            "created_at": "2026-04-20T10:00:00",
            "payload_pretty": '{"action":"refactor"}',
        }
        out = render_log_entry(entry, {"source_agent": "[[architect-agent]]", "ref": ""})
        assert "🎯" in out
        assert "**intent**" in out
        assert "`#3`" in out
        assert "[[architect-agent]]" in out


class TestRenderCheckpoint:
    def test_basic(self):
        cp = {
            "checkpoint_id": "cp_123",
            "label": "payment-engine-stable",
            "created_at": "2026-04-20T10:00:00",
            "file_manifest_pretty": "[]",
            "state_snapshot_pretty": "{}",
        }
        out = render_checkpoint(cp, {"source_agent": "[[payment-engine-agent]]"})
        assert "# payment-engine-stable" in out
        assert "Checkpoint `cp_123`" in out
        assert "[[payment-engine-agent]]" in out


class TestRenderIndex:
    def test_counts_and_waves(self):
        stats = {
            "generated_at": "2026-04-20T10:00:00Z",
            "kaos_version": "0.7.0",
            "db_path": "demo.db",
            "agents": 13, "skills": 6, "memories": 5,
            "checkpoints": 0, "log_entries": 0,
            "waves_markdown": ["**Wave 1**: [[a]], [[b]]"],
        }
        out = render_index(stats)
        assert "# KAOS engagement" in out
        assert "**13** agents" in out
        assert "**6** skills" in out
        assert "Wave 1" in out


# ── End-to-end exporter against a seeded DB ─────────────────────────


@pytest.fixture
def seeded_db(tmp_path):
    """Create a small KAOS database with agents + skills + memory + checkpoint."""
    db_path = tmp_path / "test.db"
    afs = Kaos(db_path=str(db_path))

    a1 = afs.spawn("architect-agent")
    a2 = afs.spawn("fraud-agent")

    afs.write(a1, "/notes.md", b"# notes")
    cp = afs.checkpoint(a1, label="after-notes")

    sk = SkillStore(afs.conn)
    sk.save(
        name="fraud-gbm",
        description="GBM fraud classifier",
        template="Build GBM for {project}",
        source_agent_id=a2,
        tags=["fraud", "ml"],
    )

    mem = MemoryStore(afs.conn)
    mem.write(
        agent_id=a2,
        content="Inject p50 risk as prior when Feast has no features",
        type="result",
        key="feast-cold-start-fix",
    )

    afs.close()
    yield str(db_path)


class TestVaultExporterEndToEnd:
    def test_full_export_creates_expected_structure(self, seeded_db, tmp_path):
        vault = tmp_path / "vault"
        exporter = VaultExporter(db_path=seeded_db, vault_path=vault)
        stats = exporter.export_all()

        # Directories
        assert (vault / "Agents").is_dir()
        assert (vault / "Skills").is_dir()
        assert (vault / "Memory" / "result").is_dir()
        assert (vault / "Checkpoints").is_dir()
        assert (vault / ".obsidian").is_dir()
        assert (vault / ".obsidian" / "snippets" / "kaos.css").is_file()

        # Agent notes
        assert (vault / "Agents" / "architect-agent.md").is_file()
        assert (vault / "Agents" / "fraud-agent.md").is_file()
        fraud_note = (vault / "Agents" / "fraud-agent.md").read_text(encoding="utf-8")
        assert "# fraud-agent" in fraud_note
        assert "[[fraud-gbm]]" in fraud_note           # skill backlink
        assert "[[feast-cold-start-fix]]" in fraud_note  # memory backlink

        # Skill note includes template + source
        skill_note = (vault / "Skills" / "fraud-gbm.md").read_text(encoding="utf-8")
        assert "# fraud-gbm" in skill_note
        assert "Build GBM for {project}" in skill_note
        assert "[[fraud-agent]]" in skill_note

        # Memory note
        mem_note = (vault / "Memory" / "result" / "feast-cold-start-fix.md").read_text(
            encoding="utf-8"
        )
        assert "Inject p50 risk" in mem_note
        assert "[[fraud-agent]]" in mem_note

        # Checkpoint note
        cp_dir = vault / "Checkpoints" / "architect-agent"
        assert cp_dir.is_dir()
        cp_files = list(cp_dir.glob("*.md"))
        assert len(cp_files) == 1

        # Root index
        root = (vault / "KAOS.md").read_text(encoding="utf-8")
        assert "**2** agents" in root
        assert "**1** skills" in root
        assert "**1** memory" in root.lower() or "1 memory" in root.lower()

        # Stats returned
        assert stats.agents == 2
        assert stats.skills == 1
        assert stats.memories == 1
        assert stats.checkpoints == 1

    def test_reexport_idempotent(self, seeded_db, tmp_path):
        vault = tmp_path / "vault"
        exporter = VaultExporter(db_path=seeded_db, vault_path=vault)
        s1 = exporter.export_all()

        # User adds a personal note in an un-owned location — must survive
        (vault / "my-notes.md").write_text("personal stuff")

        s2 = exporter.export_all()
        assert s1.agents == s2.agents
        assert (vault / "my-notes.md").read_text() == "personal stuff"

    def test_clean_flag_wipes_owned_dirs_only(self, seeded_db, tmp_path):
        vault = tmp_path / "vault"
        exporter = VaultExporter(db_path=seeded_db, vault_path=vault)
        exporter.export_all()

        # Add a personal note + drop a garbage file inside an owned dir
        (vault / "my-notes.md").write_text("personal")
        (vault / "Agents" / "stale.md").write_text("stale export")

        exporter.export_all(clean=True)
        # Personal note preserved
        assert (vault / "my-notes.md").read_text() == "personal"
        # Stale file removed
        assert not (vault / "Agents" / "stale.md").exists()
        # Agents still exported
        assert (vault / "Agents" / "fraud-agent.md").exists()

    def test_wave_map_applied(self, seeded_db, tmp_path):
        vault = tmp_path / "vault"
        exporter = VaultExporter(
            db_path=seeded_db,
            vault_path=vault,
            wave_map={"architect-agent": 1, "fraud-agent": 2},
        )
        exporter.export_all()

        architect = (vault / "Agents" / "architect-agent.md").read_text(encoding="utf-8")
        fraud = (vault / "Agents" / "fraud-agent.md").read_text(encoding="utf-8")
        assert "wave: 1" in architect
        assert "wave: 2" in fraud

    def test_empty_db_produces_valid_vault(self, tmp_path):
        db_path = tmp_path / "empty.db"
        Kaos(db_path=str(db_path)).close()

        vault = tmp_path / "vault"
        stats = VaultExporter(db_path=str(db_path), vault_path=vault).export_all()
        assert stats.agents == 0
        assert (vault / "KAOS.md").is_file()
        assert (vault / "Log.md").is_file()
        assert "(no entries)" in (vault / "Log.md").read_text(encoding="utf-8")

    def test_readonly_access_does_not_mutate_db(self, seeded_db, tmp_path):
        """Exporter must never write to the .db — verify via file mtime."""
        vault = tmp_path / "vault"
        mtime_before = Path(seeded_db).stat().st_mtime
        VaultExporter(db_path=seeded_db, vault_path=vault).export_all()
        mtime_after = Path(seeded_db).stat().st_mtime
        assert mtime_before == mtime_after

    def test_json_content_pretty_printed_in_checkpoint(self, seeded_db, tmp_path):
        vault = tmp_path / "vault"
        VaultExporter(db_path=seeded_db, vault_path=vault).export_all()
        cp_file = next((vault / "Checkpoints" / "architect-agent").glob("*.md"))
        text = cp_file.read_text(encoding="utf-8")
        # File manifest section should be present as JSON
        assert "## File manifest" in text
        assert "```json" in text
