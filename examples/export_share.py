"""
Export & Share Agent State
==========================

Demonstrates KAOS's single-file portability. Since everything lives in SQLite,
you can export individual agents, share databases with teammates, or inspect
any database with standard SQLite tools.

Usage:
    uv run python examples/export_share.py
"""

from __future__ import annotations

import shutil

from kaos import Kaos


def main():
    # Create a database with a couple of agents
    db = Kaos("team-project.db")

    alice = db.spawn("alice-researcher", config={"team": "security"})
    bob = db.spawn("bob-implementer", config={"team": "backend"})

    # Alice does research
    db.write(alice, "/findings.md", b"# Security Audit\n- SQL injection in auth.py\n- Missing CSRF tokens\n")
    db.set_state(alice, "severity", "critical")
    db.set_state(alice, "progress", 100)
    db.checkpoint(alice, label="audit-complete")

    # Bob starts implementation
    db.write(bob, "/fix.py", b"# Parameterized queries\ndef safe_query(user_id):\n    return db.execute('SELECT * FROM users WHERE id = ?', [user_id])\n")
    db.set_state(bob, "progress", 30)

    print("Created 2 agents in team-project.db")
    print(f"  Alice: {alice} (security researcher)")
    print(f"  Bob:   {bob} (implementer)")

    # --- EXPORT: Send Alice's work to a teammate ---
    # The CLI way: kaos export <agent-id> -o alice-audit.db
    # The Python way: just copy the whole db, or use the export command
    print("\n--- Exporting ---")
    print("CLI:    kaos export <agent-id> -o alice-audit.db")
    print("Shell:  cp team-project.db full-backup.db")

    # Simple backup — just copy the file
    shutil.copy2("team-project.db", "team-backup.db")
    print("\nBacked up to team-backup.db")

    # --- INSPECT: Use any SQLite client ---
    print("\n--- Inspect with SQLite ---")
    print("  sqlite3 team-project.db '.tables'")
    print("  sqlite3 team-project.db 'SELECT name, status FROM agents'")
    print("  sqlite3 team-project.db 'SELECT * FROM events ORDER BY timestamp'")

    # Or query directly from Python
    agents = db.query("SELECT name, status, config FROM agents")
    print(f"\nAgents in database:")
    for a in agents:
        print(f"  {a['name']} — {a['status']} — {a['config']}")

    events = db.query("SELECT COUNT(*) as count FROM events")
    print(f"Total events logged: {events[0]['count']}")

    # --- IMPORT: Teammate receives and continues ---
    # The CLI way: kaos import alice-audit.db
    print("\n--- Import on another machine ---")
    print("CLI:    kaos import alice-audit.db")
    print("Python: db = Kaos('alice-audit.db')  # just open it")

    db.close()
    print("\nDone. Files created: team-project.db, team-backup.db")


if __name__ == "__main__":
    main()
