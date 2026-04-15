"""Cross-agent memory search example.

Demonstrates KAOS's cross-agent memory store, inspired by claude-mem
(Alex Newman / @thedotmack, github.com/thedotmack/claude-mem).

Shows how multiple agents can write to a shared memory store and how
any agent can search across all entries using FTS5 full-text search
with porter stemming.

Run:
    uv run python examples/memory_search.py
"""

from __future__ import annotations

import os
import tempfile

from kaos import Kaos
from kaos.memory import MemoryStore


def main():
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "demo.db")
        kaos = Kaos(db_path)
        mem = MemoryStore(kaos.conn)

        # ── Spawn 3 agents with different roles ─────────────────────────
        research_agent = kaos.spawn("research-agent-1")
        proposer_agent = kaos.spawn("proposer-iter-3")
        eval_agent = kaos.spawn("eval-worker-7")

        print("=== Cross-Agent Memory Demo ===\n")
        print(f"Agents: research={research_agent[:12]}, proposer={proposer_agent[:12]}, eval={eval_agent[:12]}")

        # ── Research agent writes findings ───────────────────────────────
        print("\n[research-agent] Writing findings to memory...")
        mem.write(
            agent_id=research_agent,
            content="Ensemble voting with 5 models improves accuracy by 12% on math reasoning tasks. "
                    "Works best when models have diverse architectures (Opus, Sonnet, Gemini).",
            type="insight",
            key="ensemble-voting-math",
        )
        mem.write(
            agent_id=research_agent,
            content="Chain-of-thought prompting with explicit step numbers reduces errors by 23% "
                    "on multi-step arithmetic. Use 'Step 1:', 'Step 2:' format.",
            type="skill",
            key="cot-numbered-steps",
        )
        mem.write(
            agent_id=research_agent,
            content="Temperature 0.7 caused unstable outputs on deterministic tasks. "
                    "Use temperature=0 for math, temperature=0.4 for creative tasks.",
            type="observation",
            key="temperature-tuning",
        )

        # ── Proposer agent writes what it tried ─────────────────────────
        print("[proposer-agent] Writing iteration results...")
        mem.write(
            agent_id=proposer_agent,
            content="Harness v3 achieved accuracy=0.847 using majority-vote ensemble with 3 Sonnet calls. "
                    "Scores: accuracy=0.847, context_cost=18.2. Best result so far.",
            type="result",
            key="iter3-best-harness",
            metadata={"iteration": 3, "accuracy": 0.847, "cost": 18.2},
        )
        mem.write(
            agent_id=proposer_agent,
            content="Using raw LLM output without parsing caused JSON decode errors in 40% of cases. "
                    "Always wrap output parsing in try/except with fallback to regex.",
            type="error",
            key="json-parse-failure",
        )

        # ── Eval agent writes benchmark context ─────────────────────────
        print("[eval-agent] Writing evaluation context...")
        mem.write(
            agent_id=eval_agent,
            content="ARC-AGI problems require multi-step spatial reasoning. "
                    "Simple pattern matching fails on 70% of hard problems. "
                    "Need explicit grid transformation logic.",
            type="observation",
            key="arc-agi-analysis",
        )

        # ── Any agent can search across ALL memory ───────────────────────
        print("\n=== Searching memory from a NEW proposer agent ===")
        new_proposer = kaos.spawn("proposer-iter-4")

        # Search for ensemble-related knowledge
        print("\n> Searching: 'ensemble accuracy'")
        hits = mem.search("ensemble accuracy", limit=3)
        for h in hits:
            print(f"  [{h.type}] agent={h.agent_id[:12]}  key={h.key}")
            print(f"    {h.content[:120]}...")

        # Search for error patterns to avoid
        print("\n> Searching: 'error failure'")
        hits = mem.search("error failure", type="error", limit=3)
        for h in hits:
            print(f"  [{h.type}] {h.content[:120]}")

        # Search for skills
        print("\n> Searching: 'chain thought step'")
        hits = mem.search("chain thought step", type="skill")
        for h in hits:
            print(f"  [{h.type}] key={h.key}")
            print(f"    {h.content[:120]}")

        # Get the best result by key
        print("\n> Get best result by key 'iter3-best-harness':")
        best = mem.get_by_key("iter3-best-harness")
        if best:
            print(f"  accuracy={best.metadata.get('accuracy')}  cost={best.metadata.get('cost')}")
            print(f"  {best.content[:120]}")

        # Stats
        print("\n=== Memory Stats ===")
        stats = mem.stats()
        print(f"Total entries: {stats['total']}")
        for t, n in stats["by_type"].items():
            print(f"  {t:12s}: {n}")

        kaos.close()
        print("\nDone.")


if __name__ == "__main__":
    main()
