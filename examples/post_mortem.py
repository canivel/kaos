"""
Post-Mortem Debugging
=====================

An agent broke something. This example shows how to use KAOS's SQL-queryable
audit trail to figure out exactly what happened — without digging through logs.

Every file read, write, delete, tool call, and state change is recorded in the
events table. Tool calls include timing, token counts, and error messages.

This is the kind of debugging that's impossible with shared-filesystem agents.

Usage:
    # First run one of the other examples to populate a database, then:
    uv run python examples/post_mortem.py <database.db> <agent-id>

    # Or with the CLI:
    kaos query "SELECT * FROM events WHERE agent_id = 'xxx'" -d database.db
"""

from __future__ import annotations

import sys

from kaos import Kaos


def investigate(db_path: str, agent_id: str):
    afs = Kaos(db_path)

    print(f"Post-mortem for agent: {agent_id}")
    print("=" * 70)

    # 1. Agent status and metadata
    agents = afs.query(
        "SELECT name, status, config, created_at FROM agents WHERE agent_id = ?",
        [agent_id],
    )
    if not agents:
        print(f"Agent '{agent_id}' not found.")
        afs.close()
        return

    agent = agents[0]
    print(f"Name:    {agent['name']}")
    print(f"Status:  {agent['status']}")
    print(f"Created: {agent['created_at']}")
    print()

    # 2. What files did it touch?
    print("FILES TOUCHED")
    print("-" * 50)
    files = afs.query("""
        SELECT path, version, modified_at, deleted
        FROM files
        WHERE agent_id = ?
        ORDER BY modified_at
    """, [agent_id])

    for f in files:
        status = "DELETED" if f["deleted"] else f"v{f['version']}"
        print(f"  {f['modified_at'][:19]} | {status:8s} | {f['path']}")
    print()

    # 3. Tool call breakdown
    print("TOOL CALLS")
    print("-" * 50)
    tools = afs.query("""
        SELECT
            tool_name,
            status,
            COUNT(*) as count,
            SUM(token_count) as tokens,
            SUM(duration_ms) as total_ms,
            AVG(duration_ms) as avg_ms
        FROM tool_calls
        WHERE agent_id = ?
        GROUP BY tool_name, status
        ORDER BY total_ms DESC
    """, [agent_id])

    for t in tools:
        tokens = t["tokens"] or 0
        avg = t["avg_ms"] or 0
        print(f"  {t['tool_name']:20s} | {t['status']:8s} | "
              f"{t['count']:>3}x | {tokens:>8,} tokens | avg {avg:.0f}ms")
    print()

    # 4. Failed tool calls (the interesting part)
    print("FAILED TOOL CALLS")
    print("-" * 50)
    errors = afs.query("""
        SELECT tool_name, error, timestamp, duration_ms
        FROM tool_calls
        WHERE agent_id = ? AND status = 'error'
        ORDER BY timestamp
    """, [agent_id])

    if errors:
        for err in errors:
            print(f"  {err['timestamp'][:19]} | {err['tool_name']}")
            print(f"    Error: {err['error'][:100]}")
            print()
    else:
        print("  No failed tool calls.")
    print()

    # 5. Token usage summary
    print("TOKEN USAGE")
    print("-" * 50)
    usage = afs.query("""
        SELECT
            SUM(token_count) as total_tokens,
            COUNT(*) as total_calls,
            SUM(duration_ms) / 1000.0 as total_seconds
        FROM tool_calls
        WHERE agent_id = ?
    """, [agent_id])

    if usage and usage[0]["total_tokens"]:
        u = usage[0]
        print(f"  Total tokens:   {u['total_tokens']:,}")
        print(f"  Total calls:    {u['total_calls']}")
        print(f"  Total duration: {u['total_seconds']:.1f}s")
    print()

    # 6. Full event timeline (last 25 events)
    print("EVENT TIMELINE (last 25)")
    print("-" * 50)
    events = afs.events.get_events(agent_id, limit=25)

    for event in reversed(events):
        ts = event["timestamp"][:19]
        etype = event["event_type"]
        payload = str(event["payload"])[:60]
        print(f"  {ts} | {etype:20s} | {payload}")

    # 7. Checkpoints available for restore
    print()
    print("AVAILABLE CHECKPOINTS")
    print("-" * 50)
    checkpoints = afs.query("""
        SELECT checkpoint_id, label, created_at
        FROM checkpoints
        WHERE agent_id = ?
        ORDER BY created_at
    """, [agent_id])

    if checkpoints:
        for cp in checkpoints:
            label = cp["label"] or "(unlabeled)"
            print(f"  {cp['created_at'][:19]} | {cp['checkpoint_id']} | {label}")
        print(f"\n  Restore with: kaos restore {agent_id} --checkpoint <id>")
    else:
        print("  No checkpoints available.")

    afs.close()


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python examples/post_mortem.py <database.db> <agent-id>")
        print()
        print("Example:")
        print("  python examples/post_mortem.py code-review.db security-reviewer")
        sys.exit(1)

    investigate(sys.argv[1], sys.argv[2])
