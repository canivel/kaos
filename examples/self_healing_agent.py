"""Example: Self-healing agent — checkpoints before risky operations, restores on failure."""

from __future__ import annotations

import asyncio

from kaos import AgentFS
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter


async def main():
    afs = AgentFS("self-healing.db")
    router = GEPARouter.from_config("kaos.yaml")
    ccr = ClaudeCodeRunner(afs, router, checkpoint_interval=5)

    # Spawn the agent
    agent_id = afs.spawn(
        "self-healer",
        config={"force_model": "deepseek-r1-70b", "checkpoint_interval": 3},
    )

    # Write initial code to the agent's filesystem
    afs.write(agent_id, "/src/app.py", b"def main():\n    print('hello')\n")
    afs.write(agent_id, "/tests/test_app.py", b"def test_main():\n    pass\n")

    # Create a pre-refactor checkpoint
    cp_before = afs.checkpoint(agent_id, label="pre-refactor")
    print(f"Checkpoint before refactor: {cp_before}")

    # Run the agent to refactor
    try:
        result = await ccr.run_agent(
            agent_id,
            "Refactor /src/app.py to add error handling and logging. "
            "Update tests accordingly.",
        )
        print(f"Refactor result: {result[:200]}")
    except Exception as e:
        print(f"Agent failed: {e}")
        # Restore to pre-refactor state
        afs.restore(agent_id, cp_before)
        print("Restored to pre-refactor state")

        # Check what we have
        content = afs.read(agent_id, "/src/app.py")
        print(f"Restored app.py: {content.decode()}")

    # Debug: see what happened
    events = afs.events.get_events(agent_id, limit=20)
    print("\nEvent timeline:")
    for event in reversed(events):
        print(f"  {event['timestamp'][:19]} | {event['event_type']} | {str(event['payload'])[:60]}")

    afs.close()


if __name__ == "__main__":
    asyncio.run(main())
