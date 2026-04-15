# Shared Log (LogAct Protocol)

The shared log is a monotonically-growing, append-only sequence that gives every agent in a KAOS project a consistent view of collective intent, votes, and decisions — enabling safe multi-agent coordination without a central coordinator process.

> Inspired by **LogAct: Enabling Agentic Reliability via Shared Logs**
> Balakrishnan, Shi, et al. (2026), arXiv:2604.07988, Meta.
> Adapted for KAOS's local-first, SQLite-backed architecture.

---

## The LogAct Protocol

LogAct defines a 4-stage loop for safe agentic action:

```
Stage 1: Intent  — agent broadcasts what it plans to do
Stage 2: Vote    — peers approve or reject within a time window
Stage 3: Decision— outcome recorded after vote tally
Stage 4: Commit / Abort — action taken or cancelled
```

Every step is appended to the shared log with a monotonic `position`, making the full history auditable.

---

## Quick Start

```python
from kaos import Kaos
from kaos.shared_log import SharedLog

kaos = Kaos("project.db")
log  = SharedLog(kaos.conn)

# Stage 1: Agent A declares intent
intent_id = log.intent(
    agent_id="agent-A",
    action="Delete all checkpoints older than 7 days",
)

# Stage 2: Peers vote
log.vote("agent-B", intent_id, approve=True,  reason="Matches retention policy.")
log.vote("agent-C", intent_id, approve=False, reason="Need to verify first.")

# Stage 3: Tally and decide
summary  = log.tally(intent_id)   # VoteSummary(approve=1, reject=1, passed=False)
decision = log.decide(intent_id, agent_id="agent-A")

# Stage 4: Commit or abort
if decision.payload["passed"]:
    log.commit("agent-A", intent_id, summary="Removed 47 checkpoints.")
else:
    log.abort("agent-A", ref_id=intent_id, reason="Rejected by peers.")
```

---

## Entry Types

| Type | Purpose |
|------|---------|
| `intent` | Declare a planned action (LogAct Stage 1) |
| `vote` | Approve or reject an intent (Stage 2) |
| `decision` | Outcome after vote tally (Stage 3) |
| `commit` | Successful action taken (Stage 4) |
| `result` | Final output or artifact |
| `abort` | Intent or action cancelled |
| `policy` | Standing rule injected by supervisor or human |
| `mail` | Direct async message agent-to-agent |

---

## API Reference

### Intent / Vote / Decision (LogAct helpers)

```python
# Stage 1
intent_id = log.intent(agent_id, action, metadata=None)

# Stage 2
entry = log.vote(agent_id, intent_id, approve=True, reason="")

# Check tally without committing
summary = log.tally(intent_id)
# summary.approve, summary.reject, summary.passed

# Stage 3 (idempotent)
decision = log.decide(intent_id, agent_id)
# decision.payload == {"passed": True, "approve": 2, "reject": 0, "abstain": 0}
```

### Commit / Abort / Result

```python
commit = log.commit(agent_id, intent_id, summary="Done.", metadata={})
abort  = log.abort(agent_id, ref_id=intent_id, reason="Vetoed.")
result = log.result(agent_id, ref_id=None, payload={"accuracy": 0.87})
```

### Policy / Mail

```python
# Standing rule (supervisor can inject these)
log.policy(agent_id, rule="Never delete production data without 2 approvals.")

# Async agent-to-agent message
log.mail(from_agent, to_agent, message="Hey, can you handle task X?", ref_id=None)
```

### Read / Tail

```python
# All entries from a position
entries = log.read(since_position=0, limit=100)

# Filter
entries = log.read(type="intent", agent_id="agent-A")

# Last N entries in chronological order
entries = log.tail(n=20)

# Thread: root entry + all entries referencing it
entries = log.thread(root_id=intent_id)
```

### Low-level append

```python
entry = log.append(agent_id, type="result", payload={"key": "value"}, ref_id=None)
```

---

## CLI

```bash
# Show last 20 entries
uv run kaos log tail

# Filter by type
uv run kaos log tail --type intent --n 10

# Filter by agent
uv run kaos log tail --agent <agent_id>

# Log statistics
uv run kaos log ls

# JSON output
uv run kaos --json log tail | jq '.[] | select(.type == "decision")'
```

---

## MCP Tools

When using KAOS via Claude Code or MCP:

```
shared_log_intent  — broadcast intent (Stage 1)
shared_log_vote    — cast a vote (Stage 2)
shared_log_decide  — record decision (Stage 3)
shared_log_append  — append commit/result/abort/policy/mail
shared_log_read    — read entries from the log
```

---

## Safety Gate Pattern

A common pattern: wrap high-risk actions in a safety gate that requires consensus.

```python
from kaos.shared_log import SharedLog

class SafetyGate:
    def __init__(self, log, voter_agents, required_approvals=1):
        self.log = log
        self.voter_agents = voter_agents
        self.required_approvals = required_approvals

    def request(self, agent_id, action, metadata=None):
        return self.log.intent(agent_id=agent_id, action=action, metadata=metadata)

    def execute(self, agent_id, intent_id):
        summary = self.log.tally(intent_id)
        decision = self.log.decide(intent_id=intent_id, agent_id=agent_id)
        if summary.approve >= self.required_approvals and decision.payload["passed"]:
            self.log.commit(agent_id, intent_id, summary="Approved. Executing.")
            return True
        self.log.abort(agent_id, ref_id=intent_id, reason="Insufficient approvals.")
        return False
```

See [examples/safety_voting.py](../examples/safety_voting.py) for a full demo.

---

## Schema

```sql
CREATE TABLE shared_log (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    position    INTEGER UNIQUE NOT NULL,   -- monotonic, gapless
    type        TEXT NOT NULL,
    agent_id    TEXT NOT NULL,
    ref_id      INTEGER REFERENCES shared_log(log_id),
    payload     TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%f','now'))
);
```

---

## Example

See [examples/shared_log_coordination.py](../examples/shared_log_coordination.py) for a full LogAct walkthrough.

---

## Credits

Inspired by **LogAct: Enabling Agentic Reliability via Shared Logs**
by Balakrishnan, Shi, Lu, Goel, Baral, Lyu, and Dredze (2026), Meta.
Paper: [arXiv:2604.07988](https://arxiv.org/abs/2604.07988)

Key ideas taken from LogAct:
- Append-only log as the single source of truth for multi-agent coordination
- Intent/vote/decision 3-stage safety protocol
- Position-ordered entries for consistent ordering across concurrent agents
- Policy entries for human-in-the-loop and standing rules

KAOS adaptations:
- SQLite WAL mode instead of a networked log service
- Typed entries (policy, mail) beyond the core 5 LogAct types
- `thread()` helper for intent-centric audit views
- Integrated with KAOS agent lifecycle (agent_id as first-class citizen)
