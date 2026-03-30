"""
Parallel Refactor
=================

Three agents work on the same codebase simultaneously — tests, implementation,
and documentation — each fully isolated in their own VFS.

Demonstrates:
  - Parallel agent execution with GEPA model routing
  - Querying aggregate stats across all agents (token usage, timing, errors)
  - How isolation prevents agents from stepping on each other

Usage:
    uv run python examples/parallel_refactor.py
"""

from __future__ import annotations

import asyncio

from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter


async def main():
    afs = Kaos("refactor-project.db")
    router = GEPARouter.from_config("kaos.yaml")
    ccr = ClaudeCodeRunner(afs, router)

    # Three agents, three concerns, three isolated filesystems.
    # GEPA routes each to the right model based on complexity:
    #   - test-writer: moderate task → 32B model
    #   - refactorer:  complex task  → 70B model
    #   - doc-writer:  trivial task  → 7B model
    print("Spawning 3 agents in parallel...\n")

    results = await ccr.run_parallel([
        {
            "name": "test-writer",
            "prompt": (
                "Write comprehensive unit tests for a payments module that "
                "handles Stripe charges, refunds, and webhook events. "
                "Cover happy path, error cases, and edge cases."
            ),
            "config": {"force_model": "qwen2.5-coder-32b"},
        },
        {
            "name": "refactorer",
            "prompt": (
                "Refactor the payments module to use the Stripe SDK v3 API. "
                "Replace direct HTTP calls with SDK methods. Handle idempotency "
                "keys, retry logic, and proper error types."
            ),
            "config": {"force_model": "deepseek-r1-70b"},
        },
        {
            "name": "doc-writer",
            "prompt": (
                "Write API documentation for payment endpoints: "
                "POST /payments, POST /refunds, POST /webhooks. "
                "Include request/response schemas, error codes, and examples."
            ),
            "config": {"force_model": "qwen2.5-coder-7b"},
        },
    ])

    # Print results summary
    for i, result in enumerate(results):
        print(f"{'=' * 60}")
        print(f"Agent {i}: {result[:250]}")
        print()

    # --- The payoff: query aggregate stats across all agents ---
    print("=" * 60)
    print("AGGREGATE STATISTICS")
    print("=" * 60)

    stats = afs.query("""
        SELECT
            a.name,
            a.status,
            COUNT(tc.call_id) as tool_calls,
            SUM(tc.token_count) as total_tokens,
            SUM(tc.duration_ms) as total_ms,
            SUM(CASE WHEN tc.status = 'error' THEN 1 ELSE 0 END) as errors
        FROM agents a
        LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
        GROUP BY a.agent_id
        ORDER BY total_tokens DESC
    """)

    for row in stats:
        tokens = row["total_tokens"] or 0
        duration = (row["total_duration_ms"] or 0) / 1000
        errors = row["errors"] or 0
        error_flag = " ⚠" if errors > 0 else ""
        print(f"  {row['name']:20s} | {tokens:>8,} tokens | "
              f"{row['tool_calls']:>3} calls | {duration:>6.1f}s | "
              f"{row['status']}{error_flag}")

    # What files did each agent create?
    files = afs.query("""
        SELECT a.name, f.path, LENGTH(b.data) as size_bytes
        FROM files f
        JOIN agents a ON f.agent_id = a.agent_id
        JOIN blobs b ON f.content_hash = b.content_hash
        WHERE f.deleted = 0
        ORDER BY a.name, f.path
    """)

    if files:
        print(f"\nFiles created:")
        for row in files:
            print(f"  [{row['name']}] {row['path']} ({row['size_bytes']} bytes)")

    afs.close()
    print("\nDone. Full data in refactor-project.db")


if __name__ == "__main__":
    asyncio.run(main())
