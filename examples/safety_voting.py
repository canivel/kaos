"""Safety voting example — human-in-the-loop + multi-agent consensus.

Demonstrates how the shared log can implement a policy-enforced safety gate
where high-risk actions require consensus before execution.

This pattern is directly from LogAct (Balakrishnan et al. 2026, arXiv:2604.07988):
agents broadcast intent, peers vote, a decision is recorded, then the action
either proceeds (commit) or is blocked (abort).

Run:
    uv run python examples/safety_voting.py
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass

from kaos import Kaos
from kaos.shared_log import SharedLog


@dataclass
class SafetyGate:
    """A configurable safety gate backed by the shared log.

    Requires `required_approvals` approvals from registered voter agents
    before allowing an action to proceed.
    """

    log: SharedLog
    voter_agents: list[str]
    required_approvals: int = 1

    def request(self, agent_id: str, action: str, metadata: dict | None = None) -> int:
        """Declare intent. Returns intent_id for subsequent voting."""
        intent_id = self.log.intent(agent_id=agent_id, action=action, metadata=metadata)
        print(f"  [gate] Intent #{intent_id} declared: '{action[:60]}'")
        return intent_id

    def approve(self, voter_agent: str, intent_id: int, reason: str = "") -> None:
        """Approve an intent."""
        self.log.vote(agent_id=voter_agent, intent_id=intent_id,
                      approve=True, reason=reason)
        print(f"  [gate] {voter_agent[:16]} APPROVED intent #{intent_id}: {reason}")

    def reject(self, voter_agent: str, intent_id: int, reason: str = "") -> None:
        """Reject an intent."""
        self.log.vote(agent_id=voter_agent, intent_id=intent_id,
                      approve=False, reason=reason)
        print(f"  [gate] {voter_agent[:16]} REJECTED intent #{intent_id}: {reason}")

    def execute(self, agent_id: str, intent_id: int) -> bool:
        """Check votes and execute if approved. Returns True if action proceeds."""
        summary = self.log.tally(intent_id)
        decision = self.log.decide(intent_id=intent_id, agent_id=agent_id)

        if summary.approve >= self.required_approvals and decision.payload["passed"]:
            print(f"  [gate] [OK] Intent #{intent_id} APPROVED ({summary.approve}/{self.required_approvals} needed)")
            self.log.commit(
                agent_id=agent_id,
                intent_id=intent_id,
                summary=f"Approved by {summary.approve} agents. Executing.",
            )
            return True
        else:
            print(f"  [gate] [BLOCKED] Intent #{intent_id} BLOCKED ({summary.approve}/{self.required_approvals} needed, {summary.reject} rejections)")
            self.log.abort(
                agent_id=agent_id,
                ref_id=intent_id,
                reason=f"Insufficient approvals: {summary.approve}/{self.required_approvals}",
            )
            return False


def main():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "demo.db")
        kaos = Kaos(db_path)
        log = SharedLog(kaos.conn)

        # ── Spawn agents ─────────────────────────────────────────────────
        human_supervisor = kaos.spawn("human-supervisor")
        safety_monitor = kaos.spawn("safety-monitor")
        worker_agent = kaos.spawn("worker-agent")
        data_agent = kaos.spawn("data-agent")

        print("=== Safety Voting Gate Demo ===\n")

        # ── Set up a strict safety gate (needs 2 out of 2 approvals) ─────
        gate = SafetyGate(
            log=log,
            voter_agents=[human_supervisor, safety_monitor],
            required_approvals=2,
        )

        # ── Policy: inject standing rules ───────────────────────────────
        log.policy(
            agent_id=human_supervisor,
            rule="Any operation touching production data requires 2 approvals.",
        )
        log.policy(
            agent_id=safety_monitor,
            rule="Data deletion is irreversible. Always vote reject unless confirmed safe.",
        )

        # ─────────────────────────────────────────────────────────────────
        # Scenario 1: Safe action — approved by all voters
        # ─────────────────────────────────────────────────────────────────
        print("--- Scenario 1: Safe Action (approved) ---")
        intent_id = gate.request(
            agent_id=worker_agent,
            action="Export analytics_report_2026.csv to /outputs/",
            metadata={"file": "analytics_report_2026.csv", "risk": "low"},
        )
        gate.approve(human_supervisor, intent_id, reason="Read-only export, safe.")
        gate.approve(safety_monitor, intent_id, reason="No production data written.")
        proceeded = gate.execute(worker_agent, intent_id)
        print(f"  Action proceeded: {proceeded}\n")

        # ─────────────────────────────────────────────────────────────────
        # Scenario 2: Risky action — only partially approved
        # ─────────────────────────────────────────────────────────────────
        print("--- Scenario 2: Risky Action (blocked) ---")
        intent_id2 = gate.request(
            agent_id=data_agent,
            action="Permanently delete user_data table from production database.",
            metadata={"table": "user_data", "risk": "critical"},
        )
        gate.approve(data_agent, intent_id2, reason="Need to clear space.")  # self-vote
        gate.reject(human_supervisor, intent_id2, reason="Not authorized — requires DBA approval.")
        gate.reject(safety_monitor, intent_id2, reason="Irreversible. Violates retention policy.")
        proceeded2 = gate.execute(data_agent, intent_id2)
        print(f"  Action proceeded: {proceeded2}\n")

        # ─────────────────────────────────────────────────────────────────
        # Scenario 3: Lenient gate (1 approval sufficient)
        # ─────────────────────────────────────────────────────────────────
        print("--- Scenario 3: Low-risk action (1 approval gate) ---")
        lenient_gate = SafetyGate(
            log=log,
            voter_agents=[human_supervisor],
            required_approvals=1,
        )
        intent_id3 = lenient_gate.request(
            agent_id=worker_agent,
            action="Restart the analysis pipeline.",
            metadata={"risk": "low"},
        )
        lenient_gate.approve(human_supervisor, intent_id3, reason="Routine restart.")
        proceeded3 = lenient_gate.execute(worker_agent, intent_id3)
        print(f"  Action proceeded: {proceeded3}\n")

        # ── Review the full log ─────────────────────────────────────────
        print("=== Shared Log Tail ===")
        entries = log.tail(20)
        for e in entries:
            ref_str = f" ->{e.ref_id}" if e.ref_id else ""
            print(f"  {e.position:2d} [{e.type:8s}] {e.agent_id[:14]}{ref_str}")

        print(f"\nTotal log entries: {log.stats()['total']}")
        kaos.close()
        print("\nDone.")


if __name__ == "__main__":
    main()
