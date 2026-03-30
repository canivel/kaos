"""
Code Review Swarm
=================

Four agents review the same code from different angles — security, performance,
style, and test coverage — all running in parallel with full isolation.

Each reviewer writes its findings to its own VFS. At the end, we query the
aggregate stats to see which reviewer used the most tokens and which tool calls
failed (if any).

Usage:
    uv run python examples/code_review_swarm.py
"""

from __future__ import annotations

import asyncio

from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter


# The code under review — intentionally buggy for demonstration.
CODE_UNDER_REVIEW = '''
def process_payment(user_id, amount, card_token):
    """Process a payment for a user."""
    conn = db.connect()
    user = conn.execute(f"SELECT * FROM users WHERE id = {user_id}").fetchone()
    if user:
        result = stripe.charge(amount=amount, token=card_token)
        conn.execute(
            f"INSERT INTO payments VALUES ({user_id}, {amount}, '{result.id}')"
        )
        conn.commit()
        return {"status": "ok", "charge_id": result.id}
    return {"status": "error"}
'''


async def main():
    # One .db file holds everything — files, state, events, tool calls.
    afs = Kaos("code-review.db")
    router = GEPARouter.from_config("kaos.yaml")
    ccr = ClaudeCodeRunner(afs, router)

    # Define four reviewers, each with a different focus.
    # The security reviewer gets the big model; others use auto-routing.
    reviewers = [
        {
            "name": "security-reviewer",
            "prompt": (
                "You are a security auditor. Review this Python code for "
                "security vulnerabilities (SQL injection, input validation, "
                "error handling, secrets exposure). Be specific — cite the "
                "exact line and explain the attack vector.\n\n"
                f"```python\n{CODE_UNDER_REVIEW}\n```"
            ),
            "config": {"force_model": "deepseek-r1-70b"},
        },
        {
            "name": "performance-reviewer",
            "prompt": (
                "You are a performance engineer. Review this Python code for "
                "performance issues — connection pooling, N+1 queries, missing "
                "indexes, unnecessary allocations, blocking I/O.\n\n"
                f"```python\n{CODE_UNDER_REVIEW}\n```"
            ),
        },
        {
            "name": "style-reviewer",
            "prompt": (
                "You are a senior Python developer. Review this code for style, "
                "best practices, and maintainability — type hints, error handling, "
                "naming, separation of concerns, PEP 8.\n\n"
                f"```python\n{CODE_UNDER_REVIEW}\n```"
            ),
        },
        {
            "name": "test-reviewer",
            "prompt": (
                "You are a QA engineer. What test cases does this code need? "
                "Cover happy path, edge cases, error cases, and integration "
                "scenarios. Write the test plan, not the tests.\n\n"
                f"```python\n{CODE_UNDER_REVIEW}\n```"
            ),
        },
    ]

    # All four run in parallel, each in its own isolated VFS.
    # No agent can see or modify another's files.
    print(f"Spawning {len(reviewers)} reviewers in parallel...\n")
    results = await ccr.run_parallel(reviewers)

    # Print each reviewer's findings
    print("=" * 70)
    print("CODE REVIEW SUMMARY")
    print("=" * 70)
    for reviewer, result in zip(reviewers, results):
        print(f"\n[{reviewer['name']}]")
        print("-" * 50)
        # Show first 600 chars of each review
        print(result[:600])
        if len(result) > 600:
            print(f"  ... ({len(result) - 600} more characters)")

    # Query aggregate stats — this is what you can't do with other frameworks
    print("\n" + "=" * 70)
    print("AGENT STATISTICS (from SQL)")
    print("=" * 70)

    stats = afs.query("""
        SELECT
            a.name,
            a.status,
            COUNT(tc.call_id) as tool_calls,
            SUM(tc.token_count) as total_tokens,
            SUM(tc.duration_ms) as total_duration_ms
        FROM agents a
        LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
        GROUP BY a.agent_id
        ORDER BY total_tokens DESC
    """)

    for row in stats:
        tokens = row["total_tokens"] or 0
        duration = (row["total_duration_ms"] or 0) / 1000
        print(f"  {row['name']:25s} | {row['status']:10s} | "
              f"{row['tool_calls']} calls | {tokens:,} tokens | {duration:.1f}s")

    # Check for any errors
    errors = afs.query("""
        SELECT agent_id, tool_name, error
        FROM tool_calls WHERE status = 'error'
    """)
    if errors:
        print(f"\n  ⚠ {len(errors)} tool call(s) failed:")
        for err in errors:
            print(f"    {err['agent_id']}: {err['tool_name']} — {err['error'][:80]}")

    afs.close()
    print("\nDone. Review data saved to code-review.db")
    print("  Inspect with: sqlite3 code-review.db 'SELECT * FROM events'")


if __name__ == "__main__":
    asyncio.run(main())
