"""Adapter interface so AFB can run against any agent framework.

Implement ``ForensicsAdapter`` for your framework and pass it to
``run_afb.run(adapter=...)``. Methods that a framework cannot provide should
raise ``NotImplementedError``; the corresponding test is reported as
``unsupported`` rather than passed.
"""
from __future__ import annotations

import hashlib
from typing import Protocol

from generate_session import Step


class ForensicsAdapter(Protocol):
    def spawn(self, name: str) -> str: ...
    def execute(self, agent_id: str, step: Step) -> None:
        """Run one tool call for the agent, recording it however the
        framework records tool calls. Must raise nothing on expect_error
        steps — record the failure and continue."""
    def vfs_hash(self, agent_id: str) -> str:
        """sha256 over the agent's complete file tree (path + content)."""
    def checkpoint(self, agent_id: str) -> str: ...
    def restore(self, agent_id: str, checkpoint_id: str) -> None: ...
    def list_tool_calls(self, agent_id: str) -> list[dict]:
        """Every recorded tool call for the agent, in execution order, each
        with at least ``tool`` and ``input`` so the session can be replayed."""
    def read_other(self, reader_id: str, owner_id: str, path: str) -> bool:
        """True if ``reader_id`` can read ``owner_id``'s file (a leak)."""


class KaosAdapter:
    """Reference implementation over the public ``Kaos`` API."""

    def __init__(self, db_path: str):
        from kaos import Kaos
        self.db = Kaos(db_path)

    def spawn(self, name: str) -> str:
        return self.db.spawn(name, config={"bench": "afb"})

    def execute(self, agent_id: str, step: Step) -> None:
        import time
        inp = {k: v for k, v in step.__dict__.items() if v not in ("", False)}
        call_id = self.db.log_tool_call(agent_id, step.tool, inp)
        self.db.start_tool_call(call_id)
        try:
            if step.tool == "fs_write":
                self.db.write(agent_id, step.path, step.content.encode())
                out = {"bytes": len(step.content)}
            elif step.tool == "fs_read":
                out = {"bytes": len(self.db.read(agent_id, step.path))}
            elif step.tool == "state_update":
                self.db.set_state(agent_id, step.key, step.value)
                out = {"ok": True}
            else:
                raise ValueError(step.tool)
            self.db.complete_tool_call(call_id, out)
        except FileNotFoundError as exc:
            self.db.complete_tool_call(call_id, {}, status="error", error_message=str(exc))
        time.sleep(0.002)  # tool_calls.started_at has ms resolution; keep order unambiguous

    def vfs_hash(self, agent_id: str) -> str:
        h = hashlib.sha256()
        stack = ["/"]
        entries: list[tuple[str, str]] = []
        while stack:
            d = stack.pop()
            for e in self.db.ls(agent_id, d):
                if e["is_dir"]:
                    stack.append(e["path"])
                else:
                    entries.append((e["path"], hashlib.sha256(self.db.read(agent_id, e["path"])).hexdigest()))
        for p, c in sorted(entries):
            h.update(f"{p}\0{c}\n".encode())
        return h.hexdigest()

    def checkpoint(self, agent_id: str) -> str:
        return self.db.checkpoint(agent_id, label="afb")

    def restore(self, agent_id: str, checkpoint_id: str) -> None:
        self.db.restore(agent_id, checkpoint_id)

    def list_tool_calls(self, agent_id: str) -> list[dict]:
        import json
        rows = self.db.get_tool_calls(agent_id, limit=10_000)
        rows.sort(key=lambda r: r["started_at"])
        return [{"tool": r["tool_name"],
                 "input": json.loads(r["input"]) if isinstance(r["input"], str) else dict(r["input"]),
                 "status": r["status"], "call_id": r["call_id"]} for r in rows]

    def read_other(self, reader_id: str, owner_id: str, path: str) -> bool:
        try:
            self.db.read(reader_id, path)
            return True
        except FileNotFoundError:
            return False

    # KAOS-only surfaces used by the memory-isolation and localizer tests.
    @property
    def conn(self):
        return self.db.conn

    def close(self) -> None:
        self.db.close()
