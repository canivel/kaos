"""Example: Code review swarm — multiple agents review code from different angles."""

from __future__ import annotations

import asyncio

from kaos import Kaos
from kaos.ccr import ClaudeCodeRunner
from kaos.router import GEPARouter


async def main():
    afs = Kaos("code-review.db")
    router = GEPARouter.from_config("kaos.yaml")
    ccr = ClaudeCodeRunner(afs, router)

    # The code to review
    code = '''
    def process_payment(user_id, amount, card_token):
        conn = db.connect()
        user = conn.execute(f"SELECT * FROM users WHERE id = {user_id}").fetchone()
        if user:
            result = stripe.charge(amount=amount, token=card_token)
            conn.execute(f"INSERT INTO payments VALUES ({user_id}, {amount}, '{result.id}')")
            conn.commit()
            return {"status": "ok", "charge_id": result.id}
        return {"status": "error"}
    '''

    # Write the code to each agent's filesystem
    review_agents = [
        {
            "name": "security-reviewer",
            "prompt": f"Review this code for security vulnerabilities:\n```python\n{code}\n```",
            "config": {"force_model": "deepseek-r1-70b"},
        },
        {
            "name": "performance-reviewer",
            "prompt": f"Review this code for performance issues:\n```python\n{code}\n```",
        },
        {
            "name": "style-reviewer",
            "prompt": f"Review this code for style and best practices:\n```python\n{code}\n```",
        },
        {
            "name": "test-coverage-reviewer",
            "prompt": f"Suggest test cases needed for this code:\n```python\n{code}\n```",
        },
    ]

    results = await ccr.run_parallel(review_agents)

    # Combine reviews
    print("Code Review Summary")
    print("=" * 60)
    for i, (agent, result) in enumerate(zip(review_agents, results)):
        print(f"\n[{agent['name']}]")
        print("-" * 40)
        print(result[:500])

    afs.close()


if __name__ == "__main__":
    asyncio.run(main())
