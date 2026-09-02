"""Deterministic synthetic agent sessions for the Agent Forensics Bench.

A session is a list of tool-call steps for one agent. Its shape is fixed so
the ground truth is known: some read-only steps, ONE decisive write (the
planted culprit), more reads, then a visible error. Everything is derived
from the seed — same seed, same sessions, byte for byte.
"""
from __future__ import annotations

import json
import random
from dataclasses import asdict, dataclass, field


@dataclass
class Step:
    tool: str                 # fs_write | fs_read | state_update
    path: str = ""
    content: str = ""
    key: str = ""
    value: str = ""
    expect_error: bool = False


@dataclass
class Session:
    name: str
    steps: list[Step] = field(default_factory=list)
    culprit_index: int = -1   # the planted decisive step
    error_index: int = -1     # the visible failure

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


_WORDS = ["ledger", "invoice", "webhook", "retry", "cache", "schema",
          "migration", "token", "quota", "index", "payload", "cursor"]


def generate_sessions(seed: int, n_agents: int, k_steps: int) -> list[Session]:
    rng = random.Random(seed)
    sessions: list[Session] = []
    for a in range(n_agents):
        name = f"afb-agent-{a:02d}"
        # Seed files the agent can read: a handful of paths with content.
        files = {f"/src/{rng.choice(_WORDS)}_{i}.py": f"# {name} v0 {rng.random():.6f}\n"
                 for i in range(4)}
        steps: list[Step] = []
        for p, c in files.items():
            steps.append(Step(tool="fs_write", path=p, content=c))
        # Everything after the seeding writes counts toward the shape:
        # reads, ONE decisive write, reads, visible error, reads.
        body_len = k_steps - len(steps)
        culprit_at = len(steps) + rng.randint(2, max(2, body_len // 3))
        error_at = culprit_at + rng.randint(3, max(3, body_len // 3))
        paths = list(files)
        while len(steps) < k_steps:
            i = len(steps)
            if i == culprit_at:
                p = rng.choice(paths)
                steps.append(Step(tool="fs_write", path=p,
                                  content=f"# {name} DECISIVE {rng.random():.6f}\n"))
            elif i == error_at:
                steps.append(Step(tool="fs_read", path=f"/missing/{rng.choice(_WORDS)}.py",
                                  expect_error=True))
            elif rng.random() < 0.25:
                steps.append(Step(tool="state_update", key=rng.choice(_WORDS),
                                  value=f"{rng.random():.4f}"))
            else:
                steps.append(Step(tool="fs_read", path=rng.choice(paths)))
        sessions.append(Session(name=name, steps=steps,
                                culprit_index=culprit_at, error_index=error_at))
    return sessions


def fingerprint(sessions: list[Session]) -> str:
    import hashlib
    return hashlib.sha256("\n".join(s.to_json() for s in sessions).encode()).hexdigest()


if __name__ == "__main__":
    import sys
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20260902
    ss = generate_sessions(seed, 12, 24)
    print(f"{len(ss)} sessions, fingerprint {fingerprint(ss)}")
    for s in ss[:2]:
        print(s.name, "culprit", s.culprit_index, "error", s.error_index)
