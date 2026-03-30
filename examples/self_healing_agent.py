"""
Self-Healing Agent
==================

Demonstrates KAOS checkpoint/restore for safe, rollback-able agent execution.

The pattern:
  1. Write initial code to the agent's VFS
  2. Checkpoint the known-good state
  3. Let the agent attempt a risky refactor
  4. If it fails → restore to the checkpoint (other agents unaffected)
  5. Inspect the full event timeline to understand what happened

This is impossible with shared-filesystem agents — you can't roll back one
agent without affecting others.

Usage:
    uv run python examples/self_healing_agent.py
"""

from __future__ import annotations

import asyncio

from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter


async def main():
    afs = Kaos("self-healing.db")
    router = GEPARouter.from_config("kaos.yaml")
    ccr = ClaudeCodeRunner(afs, router, checkpoint_interval=5)

    # Spawn an agent with its own isolated filesystem
    agent_id = afs.spawn(
        "self-healer",
        config={"force_model": "deepseek-r1-70b"},
    )
    print(f"Spawned agent: {agent_id}")

    # Seed the agent's VFS with initial code
    afs.write(agent_id, "/src/app.py", b"""\
import logging

logger = logging.getLogger(__name__)

def main():
    logger.info("Starting application")
    print("hello")

if __name__ == "__main__":
    main()
""")
    afs.write(agent_id, "/tests/test_app.py", b"""\
from src.app import main

def test_main(capsys):
    main()
    assert capsys.readouterr().out == "hello\\n"
""")
    print("Wrote initial files to agent VFS")

    # --- KEY PATTERN: Checkpoint before risky work ---
    cp_before = afs.checkpoint(agent_id, label="pre-refactor")
    print(f"Created checkpoint: {cp_before} (label: pre-refactor)")

    # Let the agent attempt a risky refactor
    try:
        result = await ccr.run_agent(
            agent_id,
            "Refactor /src/app.py to add proper error handling, configuration "
            "management, and structured logging. Update /tests/test_app.py to "
            "cover the new error paths. Make sure all tests would pass.",
        )
        print(f"\nRefactor succeeded:")
        print(result[:300])

        # Create a post-refactor checkpoint
        cp_after = afs.checkpoint(agent_id, label="post-refactor")

        # Diff the two checkpoints to see exactly what changed
        diff = afs.diff_checkpoints(agent_id, cp_before, cp_after)
        print("\nCheckpoint diff:")
        print(f"  Files modified: {len(diff.get('files', {}).get('modified', []))}")
        print(f"  Files added:    {len(diff.get('files', {}).get('added', []))}")
        print(f"  State changes:  {len(diff.get('state', {}).get('modified', []))}")

    except Exception as e:
        print(f"\nAgent failed: {e}")
        print("Restoring to pre-refactor checkpoint...")

        # --- KEY PATTERN: Roll back just this agent ---
        afs.restore(agent_id, cp_before)

        # Verify the restore worked
        content = afs.read(agent_id, "/src/app.py")
        print(f"Restored /src/app.py ({len(content)} bytes) — original code intact")

    # --- KEY PATTERN: Full event timeline for debugging ---
    print("\n" + "=" * 60)
    print("EVENT TIMELINE")
    print("=" * 60)

    events = afs.events.get_events(agent_id, limit=30)
    for event in reversed(events):
        ts = event["timestamp"][:19]
        etype = event["event_type"]
        payload = str(event["payload"])[:70]
        print(f"  {ts} | {etype:20s} | {payload}")

    # Query tool call stats
    stats = afs.query("""
        SELECT
            tool_name,
            status,
            COUNT(*) as count,
            SUM(duration_ms) as total_ms
        FROM tool_calls
        WHERE agent_id = ?
        GROUP BY tool_name, status
    """, [agent_id])

    if stats:
        print(f"\nTool call breakdown:")
        for row in stats:
            print(f"  {row['tool_name']:15s} | {row['status']:8s} | "
                  f"{row['count']}x | {row['total_ms'] or 0}ms")

    afs.close()
    print("\nDone. Inspect with: sqlite3 self-healing.db")


if __name__ == "__main__":
    asyncio.run(main())
