"""Tests for Kaos core VFS engine."""

from __future__ import annotations

import os
import tempfile

import pytest

from kaos.core import Kaos


@pytest.fixture
def afs(tmp_path):
    """Create a temporary Kaos instance."""
    db_path = str(tmp_path / "test_agents.db")
    fs = Kaos(db_path=db_path)
    yield fs
    fs.close()


class TestAgentLifecycle:
    def test_spawn_agent(self, afs: Kaos):
        agent_id = afs.spawn("test-agent", config={"model": "test"})
        assert agent_id is not None
        status = afs.status(agent_id)
        assert status["name"] == "test-agent"
        assert status["status"] == "initialized"
        assert status["config"] == {"model": "test"}

    def test_spawn_with_parent(self, afs: Kaos):
        parent_id = afs.spawn("parent-agent")
        child_id = afs.spawn("child-agent", parent_id=parent_id)
        child_status = afs.status(child_id)
        assert child_status["parent_id"] == parent_id

    def test_agent_status_transitions(self, afs: Kaos):
        agent_id = afs.spawn("lifecycle-test")

        afs.set_status(agent_id, "running")
        assert afs.status(agent_id)["status"] == "running"

        afs.pause(agent_id)
        assert afs.status(agent_id)["status"] == "paused"

        afs.resume(agent_id)
        assert afs.status(agent_id)["status"] == "running"

        afs.complete(agent_id)
        assert afs.status(agent_id)["status"] == "completed"

    def test_kill_agent(self, afs: Kaos):
        agent_id = afs.spawn("kill-test")
        afs.set_status(agent_id, "running")
        afs.kill(agent_id)
        assert afs.status(agent_id)["status"] == "killed"

    def test_fail_agent(self, afs: Kaos):
        agent_id = afs.spawn("fail-test")
        afs.fail(agent_id, error="something went wrong")
        assert afs.status(agent_id)["status"] == "failed"

    def test_list_agents(self, afs: Kaos):
        afs.spawn("agent-1")
        afs.spawn("agent-2")
        agent_id_3 = afs.spawn("agent-3")
        afs.set_status(agent_id_3, "running")

        all_agents = afs.list_agents()
        assert len(all_agents) == 3

        running = afs.list_agents(status_filter="running")
        assert len(running) == 1
        assert running[0]["name"] == "agent-3"

    def test_nonexistent_agent_raises(self, afs: Kaos):
        with pytest.raises(ValueError, match="Agent not found"):
            afs.status("nonexistent-id")

    def test_heartbeat(self, afs: Kaos):
        agent_id = afs.spawn("heartbeat-test")
        afs.set_status(agent_id, "running")
        afs.heartbeat(agent_id)
        status = afs.status(agent_id)
        assert status["last_heartbeat"] is not None


class TestVirtualFilesystem:
    def test_write_and_read(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        content = b"hello world"
        afs.write(agent_id, "/test.txt", content)
        assert afs.read(agent_id, "/test.txt") == content

    def test_write_creates_parent_dirs(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        afs.write(agent_id, "/src/main/app.py", b"print('hello')")
        assert afs.exists(agent_id, "/src")
        assert afs.exists(agent_id, "/src/main")
        assert afs.read(agent_id, "/src/main/app.py") == b"print('hello')"

    def test_overwrite_creates_new_version(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        afs.write(agent_id, "/file.txt", b"version 1")
        afs.write(agent_id, "/file.txt", b"version 2")
        assert afs.read(agent_id, "/file.txt") == b"version 2"

        history = afs.file_history(agent_id, "/file.txt")
        assert len(history) == 2
        assert history[0]["version"] == 1
        assert history[1]["version"] == 2

    def test_delete_file(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        afs.write(agent_id, "/delete-me.txt", b"temporary")
        assert afs.exists(agent_id, "/delete-me.txt")

        afs.delete(agent_id, "/delete-me.txt")
        assert not afs.exists(agent_id, "/delete-me.txt")

    def test_delete_nonexistent_raises(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        with pytest.raises(FileNotFoundError):
            afs.delete(agent_id, "/nonexistent.txt")

    def test_read_nonexistent_raises(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        with pytest.raises(FileNotFoundError):
            afs.read(agent_id, "/nonexistent.txt")

    def test_ls(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        afs.write(agent_id, "/src/a.py", b"a")
        afs.write(agent_id, "/src/b.py", b"b")
        afs.mkdir(agent_id, "/src/sub")

        entries = afs.ls(agent_id, "/src")
        names = {e["name"] for e in entries}
        assert "a.py" in names
        assert "b.py" in names
        assert "sub" in names

    def test_stat(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        afs.write(agent_id, "/info.txt", b"some content")

        st = afs.stat(agent_id, "/info.txt")
        assert st["size"] == 12
        assert st["is_dir"] is False
        assert st["version"] == 1
        assert st["content_hash"] is not None

    def test_mkdir(self, afs: Kaos):
        agent_id = afs.spawn("fs-test")
        afs.mkdir(agent_id, "/my-dir")
        assert afs.exists(agent_id, "/my-dir")

        st = afs.stat(agent_id, "/my-dir")
        assert st["is_dir"] is True

    def test_isolation_between_agents(self, afs: Kaos):
        """Agents cannot see each other's files."""
        agent_a = afs.spawn("agent-a")
        agent_b = afs.spawn("agent-b")

        afs.write(agent_a, "/secret.txt", b"agent a secret")
        afs.write(agent_b, "/secret.txt", b"agent b secret")

        assert afs.read(agent_a, "/secret.txt") == b"agent a secret"
        assert afs.read(agent_b, "/secret.txt") == b"agent b secret"

    def test_blob_deduplication(self, afs: Kaos):
        """Identical content across agents shares the same blob."""
        agent_a = afs.spawn("agent-a")
        agent_b = afs.spawn("agent-b")

        content = b"shared content across agents"
        afs.write(agent_a, "/shared.txt", content)
        afs.write(agent_b, "/shared.txt", content)

        stats = afs.blobs.stats()
        # Both files should reference the same blob
        assert stats["total_references"] >= 2


class TestStateManagement:
    def test_set_and_get_state(self, afs: Kaos):
        agent_id = afs.spawn("state-test")
        afs.set_state(agent_id, "counter", 42)
        assert afs.get_state(agent_id, "counter") == 42

    def test_state_upsert(self, afs: Kaos):
        agent_id = afs.spawn("state-test")
        afs.set_state(agent_id, "key", "value1")
        afs.set_state(agent_id, "key", "value2")
        assert afs.get_state(agent_id, "key") == "value2"

    def test_get_state_missing_raises(self, afs: Kaos):
        agent_id = afs.spawn("state-test")
        with pytest.raises(KeyError):
            afs.get_state(agent_id, "missing")

    def test_get_state_or_default(self, afs: Kaos):
        agent_id = afs.spawn("state-test")
        assert afs.get_state_or(agent_id, "missing", "default") == "default"

    def test_get_all_state(self, afs: Kaos):
        agent_id = afs.spawn("state-test")
        afs.set_state(agent_id, "a", 1)
        afs.set_state(agent_id, "b", "two")
        afs.set_state(agent_id, "c", [3, 4, 5])

        all_state = afs.get_all_state(agent_id)
        assert all_state == {"a": 1, "b": "two", "c": [3, 4, 5]}

    def test_delete_state(self, afs: Kaos):
        agent_id = afs.spawn("state-test")
        afs.set_state(agent_id, "temp", "value")
        afs.delete_state(agent_id, "temp")
        assert afs.get_state_or(agent_id, "temp") is None

    def test_state_isolation(self, afs: Kaos):
        agent_a = afs.spawn("agent-a")
        agent_b = afs.spawn("agent-b")

        afs.set_state(agent_a, "key", "a-value")
        afs.set_state(agent_b, "key", "b-value")

        assert afs.get_state(agent_a, "key") == "a-value"
        assert afs.get_state(agent_b, "key") == "b-value"


class TestToolCalls:
    def test_log_and_complete_tool_call(self, afs: Kaos):
        agent_id = afs.spawn("tool-test")
        call_id = afs.log_tool_call(agent_id, "fs_read", {"path": "/test.txt"})
        assert call_id is not None

        afs.start_tool_call(call_id)
        afs.complete_tool_call(
            call_id,
            output={"content": "hello"},
            status="success",
            token_count=100,
        )

        calls = afs.get_tool_calls(agent_id)
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "fs_read"
        assert calls[0]["status"] == "success"
        assert calls[0]["token_count"] == 100

    def test_tool_call_error(self, afs: Kaos):
        agent_id = afs.spawn("tool-test")
        call_id = afs.log_tool_call(agent_id, "shell_exec", {"command": "fail"})
        afs.complete_tool_call(
            call_id,
            output={"error": "command not found"},
            status="error",
            error_message="command not found",
        )

        calls = afs.get_tool_calls(agent_id, status="error")
        assert len(calls) == 1
        assert calls[0]["error_message"] == "command not found"

    def test_filter_tool_calls(self, afs: Kaos):
        agent_id = afs.spawn("tool-test")
        afs.log_tool_call(agent_id, "fs_read", {"path": "/a"})
        afs.log_tool_call(agent_id, "fs_write", {"path": "/b"})
        afs.log_tool_call(agent_id, "fs_read", {"path": "/c"})

        reads = afs.get_tool_calls(agent_id, tool_name="fs_read")
        assert len(reads) == 2


class TestCheckpoints:
    def test_create_and_list_checkpoint(self, afs: Kaos):
        agent_id = afs.spawn("cp-test")
        afs.write(agent_id, "/file.txt", b"content")
        afs.set_state(agent_id, "progress", 50)

        cp_id = afs.checkpoint(agent_id, label="mid-point")
        checkpoints = afs.list_checkpoints(agent_id)
        assert len(checkpoints) == 1
        assert checkpoints[0]["label"] == "mid-point"

    def test_restore_checkpoint(self, afs: Kaos):
        agent_id = afs.spawn("cp-test")

        # Initial state
        afs.write(agent_id, "/file.txt", b"version 1")
        afs.set_state(agent_id, "step", 1)
        cp_id = afs.checkpoint(agent_id, label="step-1")

        # Modify
        afs.write(agent_id, "/file.txt", b"version 2")
        afs.write(agent_id, "/new-file.txt", b"new content")
        afs.set_state(agent_id, "step", 2)

        # Verify current state
        assert afs.read(agent_id, "/file.txt") == b"version 2"
        assert afs.get_state(agent_id, "step") == 2

        # Restore
        afs.restore(agent_id, cp_id)

        # Verify restored state
        assert afs.get_state(agent_id, "step") == 1
        assert not afs.exists(agent_id, "/new-file.txt")

    def test_diff_checkpoints(self, afs: Kaos):
        agent_id = afs.spawn("cp-test")

        afs.write(agent_id, "/a.txt", b"content-a")
        afs.set_state(agent_id, "x", 1)
        cp1 = afs.checkpoint(agent_id, label="cp1")

        afs.write(agent_id, "/b.txt", b"content-b")
        afs.write(agent_id, "/a.txt", b"modified-a")
        afs.set_state(agent_id, "x", 2)
        afs.set_state(agent_id, "y", "new")
        cp2 = afs.checkpoint(agent_id, label="cp2")

        diff = afs.diff_checkpoints(agent_id, cp1, cp2)
        assert "/b.txt" in diff["files"]["added"]
        assert "/a.txt" in diff["files"]["modified"]
        assert diff["state"]["modified"]["x"]["from"] == 1
        assert diff["state"]["modified"]["x"]["to"] == 2
        assert "y" in diff["state"]["added"]


class TestQuerying:
    def test_select_query(self, afs: Kaos):
        afs.spawn("query-test-1")
        afs.spawn("query-test-2")

        results = afs.query("SELECT name FROM agents ORDER BY name")
        names = [r["name"] for r in results]
        assert "query-test-1" in names
        assert "query-test-2" in names

    def test_write_query_rejected(self, afs: Kaos):
        with pytest.raises(PermissionError):
            afs.query("DELETE FROM agents")

    def test_insert_query_rejected(self, afs: Kaos):
        with pytest.raises(PermissionError):
            afs.query("INSERT INTO agents (agent_id, name) VALUES ('x', 'y')")


class TestEventJournal:
    def test_events_logged_on_spawn(self, afs: Kaos):
        agent_id = afs.spawn("event-test")
        events = afs.events.get_events(agent_id)
        assert any(e["event_type"] == "agent_spawn" for e in events)

    def test_events_logged_on_file_ops(self, afs: Kaos):
        agent_id = afs.spawn("event-test")
        afs.write(agent_id, "/test.txt", b"content")
        afs.read(agent_id, "/test.txt")

        events = afs.events.get_events(agent_id)
        types = [e["event_type"] for e in events]
        assert "file_write" in types
        assert "file_read" in types

    def test_event_count(self, afs: Kaos):
        agent_id = afs.spawn("event-test")
        afs.write(agent_id, "/a.txt", b"a")
        afs.write(agent_id, "/b.txt", b"b")

        count = afs.events.count(agent_id)
        assert count >= 3  # spawn + 2 writes
