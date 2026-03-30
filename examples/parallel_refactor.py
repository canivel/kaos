"""Example: Parallel refactoring with 3 agents working on the same codebase."""

from __future__ import annotations

import asyncio

from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter


async def main():
    # Initialize
    afs = Kaos("refactor-project.db")
    router = GEPARouter.from_config("kaos.yaml")
    ccr = ClaudeCodeRunner(afs, router)

    # Spawn 3 agents working on different aspects of a refactor
    results = await ccr.run_parallel([
        {
            "name": "test-writer",
            "prompt": "Write comprehensive unit tests for the payments module",
            "config": {"force_model": "qwen2.5-coder-32b"},
        },
        {
            "name": "refactorer",
            "prompt": "Refactor the payments module to use Stripe SDK v3",
            "config": {"force_model": "deepseek-r1-70b"},
        },
        {
            "name": "doc-writer",
            "prompt": "Update API documentation for payment endpoints",
            "config": {"force_model": "qwen2.5-coder-7b"},
        },
    ])

    # Print results
    for i, result in enumerate(results):
        print(f"\n{'='*60}")
        print(f"Agent {i}: {result[:200]}")

    # Query aggregate stats
    stats = afs.query("""
        SELECT
            a.name,
            COUNT(tc.call_id) as tool_calls,
            SUM(tc.token_count) as total_tokens,
            SUM(tc.duration_ms) as total_ms
        FROM agents a
        LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
        GROUP BY a.agent_id
    """)

    print("\n\nAgent Statistics:")
    for row in stats:
        print(f"  {row['name']}: {row['tool_calls']} calls, "
              f"{row['total_tokens'] or 0} tokens, "
              f"{row['total_ms'] or 0}ms")

    afs.close()


if __name__ == "__main__":
    asyncio.run(main())
