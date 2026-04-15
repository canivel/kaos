"""Tests for shared coordination log (SharedLog / LogAct)."""

from __future__ import annotations

import pytest

from kaos.core import Kaos
from kaos.shared_log import SharedLog, LogEntry, VoteSummary, LOG_TYPES


@pytest.fixture
def afs(tmp_path):
    db_path = str(tmp_path / "test.db")
    fs = Kaos(db_path=db_path)
    yield fs
    fs.close()


@pytest.fixture
def log(afs):
    return SharedLog(afs.conn)


@pytest.fixture
def agent_id(afs):
    return afs.spawn("test-agent")


class TestLogAppend:
    def test_append_returns_log_entry(self, log, agent_id):
        entry = log.append(agent_id=agent_id, type="commit", payload={"summary": "done"})
        assert isinstance(entry, LogEntry)
        assert entry.log_id > 0
        assert entry.position == 0
        assert entry.type == "commit"
        assert entry.payload["summary"] == "done"

    def test_positions_are_monotonic(self, log, agent_id):
        e1 = log.append(agent_id=agent_id, type="commit")
        e2 = log.append(agent_id=agent_id, type="result")
        e3 = log.append(agent_id=agent_id, type="policy")
        assert e1.position < e2.position < e3.position

    def test_append_invalid_type_raises(self, log, agent_id):
        with pytest.raises(ValueError, match="type must be one of"):
            log.append(agent_id=agent_id, type="unknown")

    def test_append_with_ref_id(self, log, agent_id):
        parent = log.append(agent_id=agent_id, type="commit")
        child = log.append(agent_id=agent_id, type="result", ref_id=parent.log_id)
        assert child.ref_id == parent.log_id

    def test_append_all_types(self, log, agent_id):
        for t in LOG_TYPES:
            entry = log.append(agent_id=agent_id, type=t)
            assert entry.type == t


class TestLogActProtocol:
    def test_intent_returns_log_id(self, log, agent_id):
        intent_id = log.intent(agent_id=agent_id, action="delete old checkpoints")
        assert isinstance(intent_id, int)
        assert intent_id > 0

    def test_intent_stored_correctly(self, log, agent_id):
        intent_id = log.intent(agent_id=agent_id, action="do something risky")
        entry = log.get(intent_id)
        assert entry is not None
        assert entry.type == "intent"
        assert entry.payload["action"] == "do something risky"

    def test_vote_approve(self, log, afs):
        a1 = afs.spawn("proposer")
        a2 = afs.spawn("voter")
        intent_id = log.intent(agent_id=a1, action="risky action")
        vote = log.vote(agent_id=a2, intent_id=intent_id, approve=True, reason="looks safe")
        assert vote.type == "vote"
        assert vote.payload["approve"] is True
        assert vote.payload["reason"] == "looks safe"
        assert vote.ref_id == intent_id

    def test_vote_reject(self, log, afs):
        a1 = afs.spawn("proposer-2")
        a2 = afs.spawn("voter-2")
        intent_id = log.intent(agent_id=a1, action="dangerous action")
        vote = log.vote(agent_id=a2, intent_id=intent_id, approve=False, reason="too risky")
        assert vote.payload["approve"] is False

    def test_tally_empty(self, log, agent_id):
        intent_id = log.intent(agent_id=agent_id, action="action")
        summary = log.tally(intent_id)
        assert isinstance(summary, VoteSummary)
        assert summary.approve == 0
        assert summary.reject == 0
        assert summary.abstain == 0
        assert summary.votes == []

    def test_tally_counts(self, log, afs):
        proposer = afs.spawn("proposer-3")
        voters = [afs.spawn(f"voter-{i}") for i in range(4)]
        intent_id = log.intent(agent_id=proposer, action="action")
        log.vote(agent_id=voters[0], intent_id=intent_id, approve=True)
        log.vote(agent_id=voters[1], intent_id=intent_id, approve=True)
        log.vote(agent_id=voters[2], intent_id=intent_id, approve=False)
        log.vote(agent_id=voters[3], intent_id=intent_id, approve=True)
        summary = log.tally(intent_id)
        assert summary.approve == 3
        assert summary.reject == 1
        assert summary.passed is True

    def test_decide_records_decision(self, log, afs):
        proposer = afs.spawn("decider-proposer")
        voter = afs.spawn("decider-voter")
        intent_id = log.intent(agent_id=proposer, action="action")
        log.vote(agent_id=voter, intent_id=intent_id, approve=True)
        decision = log.decide(intent_id=intent_id, agent_id=proposer)
        assert decision.type == "decision"
        assert decision.payload["passed"] is True
        assert decision.payload["approve"] == 1
        assert decision.ref_id == intent_id

    def test_decide_idempotent(self, log, afs):
        proposer = afs.spawn("idem-proposer")
        intent_id = log.intent(agent_id=proposer, action="action")
        d1 = log.decide(intent_id=intent_id, agent_id=proposer)
        d2 = log.decide(intent_id=intent_id, agent_id=proposer)
        assert d1.log_id == d2.log_id

    def test_decide_failed(self, log, afs):
        proposer = afs.spawn("fail-proposer")
        voter = afs.spawn("fail-voter")
        intent_id = log.intent(agent_id=proposer, action="risky")
        log.vote(agent_id=voter, intent_id=intent_id, approve=False)
        decision = log.decide(intent_id=intent_id, agent_id=proposer)
        assert decision.payload["passed"] is False

    def test_commit_references_intent(self, log, agent_id):
        intent_id = log.intent(agent_id=agent_id, action="clean up")
        commit = log.commit(agent_id=agent_id, intent_id=intent_id,
                            summary="Removed 42 old checkpoints")
        assert commit.type == "commit"
        assert commit.ref_id == intent_id
        assert commit.payload["summary"] == "Removed 42 old checkpoints"

    def test_abort(self, log, agent_id):
        intent_id = log.intent(agent_id=agent_id, action="action")
        abort = log.abort(agent_id=agent_id, ref_id=intent_id, reason="changed my mind")
        assert abort.type == "abort"
        assert abort.payload["reason"] == "changed my mind"

    def test_policy(self, log, agent_id):
        p = log.policy(agent_id=agent_id, rule="Never delete production data")
        assert p.type == "policy"
        assert p.payload["rule"] == "Never delete production data"

    def test_mail(self, log, afs):
        sender = afs.spawn("sender")
        receiver = afs.spawn("receiver")
        mail = log.mail(from_agent=sender, to_agent=receiver,
                        message="Hey, can you handle task X?")
        assert mail.type == "mail"
        assert mail.payload["to"] == receiver
        assert mail.payload["message"] == "Hey, can you handle task X?"
        assert mail.agent_id == sender


class TestLogRead:
    def test_read_all(self, log, agent_id):
        log.append(agent_id=agent_id, type="commit")
        log.append(agent_id=agent_id, type="result")
        entries = log.read()
        assert len(entries) >= 2

    def test_read_since_position(self, log, agent_id):
        e1 = log.append(agent_id=agent_id, type="commit")
        e2 = log.append(agent_id=agent_id, type="result")
        e3 = log.append(agent_id=agent_id, type="policy")
        entries = log.read(since_position=e2.position)
        positions = [e.position for e in entries]
        assert e1.position not in positions
        assert e2.position in positions
        assert e3.position in positions

    def test_read_filter_type(self, log, agent_id):
        log.append(agent_id=agent_id, type="commit")
        log.append(agent_id=agent_id, type="result")
        log.append(agent_id=agent_id, type="commit")
        entries = log.read(type="commit")
        assert all(e.type == "commit" for e in entries)

    def test_read_filter_agent(self, log, afs):
        a1 = afs.spawn("filter-a1")
        a2 = afs.spawn("filter-a2")
        log.append(agent_id=a1, type="commit")
        log.append(agent_id=a2, type="commit")
        entries = log.read(agent_id=a1)
        assert all(e.agent_id == a1 for e in entries)

    def test_read_limit(self, log, agent_id):
        for _ in range(10):
            log.append(agent_id=agent_id, type="commit")
        entries = log.read(limit=3)
        assert len(entries) == 3

    def test_read_in_position_order(self, log, agent_id):
        for _ in range(5):
            log.append(agent_id=agent_id, type="commit")
        entries = log.read()
        for i in range(1, len(entries)):
            assert entries[i].position > entries[i - 1].position


class TestLogTail:
    def test_tail_returns_last_n(self, log, agent_id):
        for i in range(10):
            log.append(agent_id=agent_id, type="commit", payload={"i": i})
        entries = log.tail(3)
        assert len(entries) == 3
        # Should be the last 3 in chronological order
        assert entries[-1].payload["i"] == 9
        assert entries[-2].payload["i"] == 8

    def test_tail_fewer_than_n(self, log, agent_id):
        log.append(agent_id=agent_id, type="commit")
        entries = log.tail(100)
        assert len(entries) == 1

    def test_tail_empty(self, log):
        entries = log.tail(10)
        assert entries == []


class TestLogThread:
    def test_thread_returns_root_and_children(self, log, afs):
        proposer = afs.spawn("thread-proposer")
        voter = afs.spawn("thread-voter")
        intent_id = log.intent(agent_id=proposer, action="action")
        log.vote(agent_id=voter, intent_id=intent_id, approve=True)
        log.decide(intent_id=intent_id, agent_id=proposer)
        thread = log.thread(intent_id)
        types = {e.type for e in thread}
        assert "intent" in types
        assert "vote" in types
        assert "decision" in types


class TestLogStats:
    def test_stats_empty(self, log):
        stats = log.stats()
        assert stats["total"] == 0
        assert stats["by_type"] == {}

    def test_stats_counts(self, log, agent_id):
        log.append(agent_id=agent_id, type="commit")
        log.append(agent_id=agent_id, type="commit")
        log.append(agent_id=agent_id, type="policy")
        stats = log.stats()
        assert stats["total"] == 3
        assert stats["by_type"]["commit"] == 2
        assert stats["by_type"]["policy"] == 1


class TestLogEntryToDict:
    def test_to_dict_has_all_fields(self, log, agent_id):
        entry = log.append(agent_id=agent_id, type="result", payload={"x": 1})
        d = entry.to_dict()
        assert d["log_id"] == entry.log_id
        assert d["position"] == entry.position
        assert d["type"] == "result"
        assert d["agent_id"] == agent_id
        assert d["payload"] == {"x": 1}
        assert "created_at" in d
