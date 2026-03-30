"""
Library Basics
==============

KAOS as a pure Python library — no LLMs, no infrastructure, no config files.
Just isolated, auditable agent runtimes backed by SQLite.

This example walks through every core feature:
  - Spawn agents with isolated virtual filesystems
  - Read/write/delete files in each agent's VFS
  - KV state store per agent
  - Checkpoint, restore, and diff
  - SQL queries across the entire database
  - Event journal inspection

Perfect starting point if you want to integrate KAOS into your own
agent framework or orchestration system.

Usage:
    uv run python examples/library_basics.py
"""

from __future__ import annotations

from kaos import Kaos


def main():
    # Everything lives in one .db file.
    # Copy it to back up. Send it to a colleague. Query with any SQLite client.
    db = Kaos("basics-demo.db")

    print("=== 1. SPAWN AGENTS ===")
    alice = db.spawn("alice", config={"role": "researcher"})
    bob = db.spawn("bob", config={"role": "implementer"})
    print(f"  Alice: {alice}")
    print(f"  Bob:   {bob}")

    print("\n=== 2. ISOLATED FILESYSTEMS ===")
    # Each agent has its own virtual filesystem.
    db.write(alice, "/notes.md", b"# Alice's Research\n- Found bug in auth.py\n")
    db.write(alice, "/data/results.json", b'{"bugs_found": 3}')
    db.write(bob, "/notes.md", b"# Bob's Implementation Plan\n- Fix auth.py\n")

    # Same path, different contents — no conflict.
    alice_notes = db.read(alice, "/notes.md")
    bob_notes = db.read(bob, "/notes.md")
    print(f"  Alice's /notes.md: {alice_notes[:40]}...")
    print(f"  Bob's   /notes.md: {bob_notes[:40]}...")

    # Isolation is enforced. Bob can't see Alice's files.
    try:
        db.read(bob, "/data/results.json")
    except FileNotFoundError:
        print("  Bob can't see Alice's /data/results.json — isolation works!")

    # List files in each agent's VFS
    print(f"  Alice's files: {db.ls(alice, '/')}")
    print(f"  Bob's files:   {db.ls(bob, '/')}")

    print("\n=== 3. KV STATE STORE ===")
    # Each agent gets its own key-value store. Values are JSON-serializable.
    db.set_state(alice, "progress", 42)
    db.set_state(alice, "findings", ["SQL injection", "missing rate limit", "no CSRF"])
    db.set_state(bob, "progress", 10)

    print(f"  Alice progress: {db.get_state(alice, 'progress')}")
    print(f"  Alice findings: {db.get_state(alice, 'findings')}")
    print(f"  Bob progress:   {db.get_state(bob, 'progress')}")

    print("\n=== 4. CHECKPOINT / RESTORE / DIFF ===")
    # Snapshot Alice's complete state (files + KV store)
    cp1 = db.checkpoint(alice, label="initial-research")
    print(f"  Checkpoint 1: {cp1}")

    # Alice does more work
    db.write(alice, "/notes.md", b"# Alice's Research\n- Found 5 bugs total\n")
    db.set_state(alice, "progress", 85)
    db.set_state(alice, "findings", ["SQL injection", "missing rate limit", "no CSRF", "XSS", "open redirect"])

    cp2 = db.checkpoint(alice, label="deep-research")
    print(f"  Checkpoint 2: {cp2}")

    # Diff the two checkpoints — see exactly what changed
    diff = db.diff_checkpoints(alice, cp1, cp2)
    print(f"  Diff: {diff}")

    # Restore to checkpoint 1 — Alice's VFS and state roll back
    db.restore(alice, cp1)
    restored_notes = db.read(alice, "/notes.md")
    restored_progress = db.get_state(alice, "progress")
    print(f"  After restore — notes: {restored_notes[:40]}...")
    print(f"  After restore — progress: {restored_progress}")

    print("\n=== 5. SQL QUERIES ===")
    # Query anything. This is just SQLite.
    agents = db.query("SELECT agent_id, name, status, config FROM agents")
    print(f"  All agents: {agents}")

    # Count events per agent
    event_counts = db.query("""
        SELECT agent_id, event_type, COUNT(*) as count
        FROM events
        GROUP BY agent_id, event_type
        ORDER BY agent_id, count DESC
    """)
    print(f"  Events by type:")
    for row in event_counts:
        print(f"    {row['agent_id'][:12]}... | {row['event_type']:20s} | {row['count']}x")

    print("\n=== 6. EVENT JOURNAL ===")
    # Every operation is recorded — full audit trail.
    events = db.events.get_events(alice, limit=10)
    print(f"  Alice's last 10 events:")
    for event in reversed(events):
        ts = event["timestamp"][:19]
        print(f"    {ts} | {event['event_type']:20s} | {str(event['payload'])[:50]}")

    db.close()
    print(f"\nDone. Everything saved to basics-demo.db")
    print("  Inspect with: sqlite3 basics-demo.db '.tables'")
    print("  Or:           sqlite3 basics-demo.db 'SELECT * FROM events LIMIT 20'")


if __name__ == "__main__":
    main()
