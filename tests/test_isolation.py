"""Tests for the isolation module."""

from __future__ import annotations

import pytest

from kaos.core import Kaos
from kaos.isolation import (
    IsolationConfig,
    LogicalIsolation,
    IsolatedAgentProcess,
    create_isolation,
)


@pytest.fixture
def afs(tmp_path):
    db_path = str(tmp_path / "test_isolation.db")
    fs = Kaos(db_path=db_path)
    yield fs
    fs.close()


class TestLogicalIsolation:
    def test_scoped_read_write(self, afs: Kaos):
        agent_id = afs.spawn("isolated-agent")
        iso = LogicalIsolation(afs, agent_id)

        iso.write("/test.txt", b"isolated content")
        assert iso.read("/test.txt") == b"isolated content"

    def test_scoped_ls(self, afs: Kaos):
        agent_id = afs.spawn("isolated-agent")
        iso = LogicalIsolation(afs, agent_id)

        iso.write("/a.txt", b"a")
        iso.write("/b.txt", b"b")

        entries = iso.ls("/")
        names = {e["name"] for e in entries}
        assert "a.txt" in names
        assert "b.txt" in names

    def test_scoped_state(self, afs: Kaos):
        agent_id = afs.spawn("isolated-agent")
        iso = LogicalIsolation(afs, agent_id)

        iso.set_state("key", "value")
        assert iso.get_state("key") == "value"

    def test_cross_agent_isolation(self, afs: Kaos):
        id_a = afs.spawn("agent-a")
        id_b = afs.spawn("agent-b")
        iso_a = LogicalIsolation(afs, id_a)
        iso_b = LogicalIsolation(afs, id_b)

        iso_a.write("/secret.txt", b"a-secret")
        iso_b.write("/secret.txt", b"b-secret")

        assert iso_a.read("/secret.txt") == b"a-secret"
        assert iso_b.read("/secret.txt") == b"b-secret"

    def test_exists_and_mkdir(self, afs: Kaos):
        agent_id = afs.spawn("isolated-agent")
        iso = LogicalIsolation(afs, agent_id)

        assert not iso.exists("/new-dir")
        iso.mkdir("/new-dir")
        assert iso.exists("/new-dir")

    def test_delete(self, afs: Kaos):
        agent_id = afs.spawn("isolated-agent")
        iso = LogicalIsolation(afs, agent_id)

        iso.write("/temp.txt", b"temp")
        assert iso.exists("/temp.txt")
        iso.delete("/temp.txt")
        assert not iso.exists("/temp.txt")


class TestIsolationFactory:
    def test_create_logical(self, afs: Kaos):
        agent_id = afs.spawn("factory-test")
        config = IsolationConfig(mode="logical")
        iso = create_isolation(afs, agent_id, config)
        assert isinstance(iso, LogicalIsolation)

    def test_create_fuse(self, afs: Kaos):
        agent_id = afs.spawn("factory-test")
        config = IsolationConfig(mode="fuse")
        iso = create_isolation(afs, agent_id, config)
        assert isinstance(iso, IsolatedAgentProcess)

    def test_unknown_mode_raises(self, afs: Kaos):
        agent_id = afs.spawn("factory-test")
        config = IsolationConfig(mode="invalid")
        with pytest.raises(ValueError, match="Unknown isolation mode"):
            create_isolation(afs, agent_id, config)
