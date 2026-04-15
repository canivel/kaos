"""Shared log coordination example — LogAct 4-stage protocol.

Demonstrates KAOS's shared append-only coordination log, inspired by LogAct:
Enabling Agentic Reliability via Shared Logs (Balakrishnan et al., 2026,
arXiv:2604.07988, Meta).

The shared log gives every agent a consistent view of collective intent,
votes, and decisions — enabling safe multi-agent coordination without a
central coordinator process.

Run:
    uv run python examples/shared_log_coordination.py
"""

from __future__ import annotations

import os
import tempfile

from kaos import Kaos
from kaos.shared_log import SharedLog


def main():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        db_path = os.path.join(tmp, "demo.db")
        kaos = Kaos(db_path)
        log = SharedLog(kaos.conn)

        # ── Spawn agents with different roles ───────────────────────────
        supervisor = kaos.spawn("supervisor")
        agent_a = kaos.spawn("research-agent-A")
        agent_b = kaos.spawn("research-agent-B")
        agent_c = kaos.spawn("safety-monitor")

        print("=== LogAct Shared Log Demo ===\n")

        # ── Policy: supervisor injects a standing rule ───────────────────
        print("[supervisor] Injecting safety policy...")
        log.policy(
            agent_id=supervisor,
            rule="No agent may delete files from /production without a 2/3 vote.",
            metadata={"severity": "critical"},
        )

        # ── Stage 1: Agent A declares intent ────────────────────────────
        print("\n[Stage 1] agent-A declares intent to clean up old checkpoints...")
        intent_id = log.intent(
            agent_id=agent_a,
            action="Delete all checkpoints older than 7 days from /checkpoints/old/",
            metadata={"estimated_freed_gb": 12.4, "path": "/checkpoints/old/"},
        )
        print(f"  -> intent_id={intent_id}")

        # ── Stage 2: Other agents vote ───────────────────────────────────
        print("\n[Stage 2] Peers casting votes...")
        v1 = log.vote(agent_id=agent_b, intent_id=intent_id,
                      approve=True, reason="Matches 7-day retention policy.")
        v2 = log.vote(agent_id=agent_c, intent_id=intent_id,
                      approve=True, reason="Safety check passed — no production data affected.")
        print(f"  -> agent-B vote: approve={v1.payload['approve']}  reason='{v1.payload['reason']}'")
        print(f"  -> agent-C vote: approve={v2.payload['approve']}  reason='{v2.payload['reason']}'")

        # Check tally before deciding
        summary = log.tally(intent_id)
        print(f"\n  Vote tally: approve={summary.approve}, reject={summary.reject}  -> passed={summary.passed}")

        # ── Stage 3: Record decision ─────────────────────────────────────
        print("\n[Stage 3] Recording decision...")
        decision = log.decide(intent_id=intent_id, agent_id=agent_a)
        print(f"  -> decision: passed={decision.payload['passed']}  ({decision.payload['approve']} approve, {decision.payload['reject']} reject)")

        # ── Stage 4: Commit the action ───────────────────────────────────
        if decision.payload["passed"]:
            print("\n[Stage 4] agent-A executing and committing...")
            # ... actual cleanup would happen here ...
            commit = log.commit(
                agent_id=agent_a,
                intent_id=intent_id,
                summary="Deleted 47 checkpoint files, freed 12.4 GB.",
                metadata={"files_deleted": 47, "gb_freed": 12.4},
            )
            print(f"  -> commit: '{commit.payload['summary']}'")

        # ── Mail: async message to another agent ────────────────────────
        print("\n[agent-A -> supervisor] Sending mail notification...")
        log.mail(
            from_agent=agent_a,
            to_agent=supervisor,
            message="Checkpoint cleanup complete. 47 files removed, 12.4 GB freed.",
            ref_id=intent_id,
        )

        # ── Another scenario: rejected intent ───────────────────────────
        print("\n--- Scenario: Rejected Intent ---")
        print("[agent-B] Declaring intent to drop the events table...")
        risky_intent = log.intent(
            agent_id=agent_b,
            action="DROP TABLE events — this is for performance testing",
        )
        log.vote(agent_id=agent_a, intent_id=risky_intent, approve=False,
                 reason="Events table is required for audit trail.")
        log.vote(agent_id=agent_c, intent_id=risky_intent, approve=False,
                 reason="Violates data retention policy.")
        rejected = log.decide(intent_id=risky_intent, agent_id=agent_b)
        abort_entry = log.abort(agent_id=agent_b, ref_id=risky_intent,
                                reason="Rejected by peers (0 approve, 2 reject).")
        print(f"  -> Rejected.  abort reason: '{abort_entry.payload['reason']}'")

        # ── Read the full log ────────────────────────────────────────────
        print("\n=== Full Shared Log ===")
        TYPE_TAGS = {
            "intent": "[INTENT  ]", "vote": "[VOTE    ]", "decision": "[DECIDE  ]",
            "commit": "[COMMIT  ]", "result": "[RESULT  ]", "abort": "[ABORT   ]",
            "policy": "[POLICY  ]", "mail": "[MAIL    ]",
        }
        entries = log.read()
        for e in entries:
            tag = TYPE_TAGS.get(e.type, "[?       ]")
            ref_str = f" ref={e.ref_id}" if e.ref_id else ""
            payload_preview = str(e.payload)[:60]
            print(f"  {e.position:2d} {tag} agent={e.agent_id[:14]}{ref_str}")
            print(f"       {payload_preview}...")

        # Stats
        stats = log.stats()
        print(f"\nLog stats: total={stats['total']}  by_type={stats['by_type']}")

        # Thread view: see all entries for the first intent
        print(f"\n=== Thread for intent_id={intent_id} ===")
        thread = log.thread(intent_id)
        for e in thread:
            print(f"  [{e.type:8s}] {e.payload}")

        kaos.close()
        print("\nDone.")


if __name__ == "__main__":
    main()
