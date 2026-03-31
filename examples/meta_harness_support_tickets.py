"""
Real-World Example: Optimize a Support Ticket Classifier
=========================================================

You have a customer support system. Tickets come in and need to be routed
to the right team: billing, technical, account, or general. You're using
an LLM to classify them, but your current prompt only gets ~60% accuracy.

Meta-Harness will automatically search for a better harness — the code that
wraps your LLM (prompt template, example selection, retrieval strategy) —
by trying different approaches, measuring results, and learning from full
execution traces.

What happens under the hood:
  1. KAOS creates a "search agent" that owns the archive of all tried harnesses
  2. Three seed harnesses are evaluated (zero-shot, few-shot, retrieval-based)
  3. For each iteration:
     - A proposer agent reads ALL prior harnesses, their scores, and traces
     - It identifies what worked, what failed, and WHY (from the traces)
     - It proposes new harness variants targeting specific failure modes
     - Each variant is evaluated and stored with full traces
  4. The Pareto frontier tracks the best accuracy vs. context cost tradeoffs

Every harness, every score, every trace, every proposer conversation is stored
in the KAOS database — queryable with SQL, checkpointed, restorable.

Usage:
    # With local vLLM running:
    uv run python examples/meta_harness_support_tickets.py

    # Or see what the search produced:
    kaos mh frontier <search-agent-id> --db support-tickets.db
    kaos mh inspect <search-agent-id> <best-harness-id> --db support-tickets.db
"""

from __future__ import annotations

import asyncio
import json

from kaos import Kaos
from kaos.metaharness.harness import SearchConfig
from kaos.metaharness.search import MetaHarnessSearch
from kaos.metaharness.benchmarks.base import Benchmark, Problem
from kaos.metaharness.benchmarks import register_benchmark
from kaos.router.gepa import GEPARouter


# ── Step 1: Define your dataset ──────────────────────────────────
#
# In production you'd load this from a CSV/JSON file. Here we inline
# realistic support ticket examples.

SUPPORT_TICKETS = [
    # Billing
    {"text": "I was charged twice for my subscription this month", "label": "billing"},
    {"text": "Can I get a refund for the unused portion of my plan?", "label": "billing"},
    {"text": "My credit card was declined but I have sufficient funds", "label": "billing"},
    {"text": "I need to update my payment method to a different card", "label": "billing"},
    {"text": "The invoice amount doesn't match the agreed price", "label": "billing"},
    {"text": "Why was I charged after I cancelled my subscription?", "label": "billing"},
    {"text": "I need a copy of my receipt from last month", "label": "billing"},
    {"text": "How do I switch from monthly to annual billing?", "label": "billing"},
    {"text": "There's a mysterious charge from your company on my statement", "label": "billing"},
    {"text": "Can I get an enterprise discount for 50+ seats?", "label": "billing"},

    # Technical
    {"text": "The API returns 500 errors intermittently on POST requests", "label": "technical"},
    {"text": "My integration with Salesforce stopped syncing data yesterday", "label": "technical"},
    {"text": "The dashboard takes 30 seconds to load, it used to be instant", "label": "technical"},
    {"text": "I'm getting CORS errors when calling the API from localhost", "label": "technical"},
    {"text": "The webhook payload format changed and broke our parser", "label": "technical"},
    {"text": "How do I configure SSO with our Azure AD tenant?", "label": "technical"},
    {"text": "Export to CSV is generating corrupted files with special characters", "label": "technical"},
    {"text": "The search function returns no results even for exact matches", "label": "technical"},
    {"text": "Our custom integration can't authenticate after the API update", "label": "technical"},
    {"text": "Is there a rate limit on the batch processing endpoint?", "label": "technical"},

    # Account
    {"text": "I need to add 3 new team members to our organization", "label": "account"},
    {"text": "How do I transfer ownership of the account to my colleague?", "label": "account"},
    {"text": "I forgot my password and the reset email isn't arriving", "label": "account"},
    {"text": "Can I merge two accounts that were created by mistake?", "label": "account"},
    {"text": "I need to change the email address associated with my account", "label": "account"},
    {"text": "How do I enable two-factor authentication for all users?", "label": "account"},
    {"text": "One of our team members left, how do I revoke their access?", "label": "account"},
    {"text": "I want to downgrade from the pro plan to the basic plan", "label": "account"},
    {"text": "Our company name changed, can you update it on the account?", "label": "account"},
    {"text": "I need an audit log of who accessed what in the last 30 days", "label": "account"},

    # General
    {"text": "What are your support hours on weekends?", "label": "general"},
    {"text": "Do you have a status page for service outages?", "label": "general"},
    {"text": "I'd like to schedule a demo for our team", "label": "general"},
    {"text": "Where can I find the documentation for the new features?", "label": "general"},
    {"text": "Is there a community forum or Slack channel for users?", "label": "general"},
    {"text": "What's on the product roadmap for next quarter?", "label": "general"},
    {"text": "Can you send me your security compliance certifications?", "label": "general"},
    {"text": "I have feedback about the new UI redesign", "label": "general"},
    {"text": "Do you offer training or onboarding sessions?", "label": "general"},
    {"text": "What's the difference between the pro and enterprise plans?", "label": "general"},
]


# ── Step 2: Define the benchmark ─────────────────────────────────
#
# This wraps your dataset into the Meta-Harness benchmark interface.

class SupportTicketBenchmark(Benchmark):
    """Custom benchmark for support ticket classification."""

    def __init__(self, **kwargs):
        self._data = SUPPORT_TICKETS
        self._labels = sorted(set(t["label"] for t in self._data))
        # First 30 for search, last 10 for held-out test
        self._search = self._data[:30]
        self._test = self._data[30:]

    @property
    def name(self) -> str:
        return "support_tickets"

    @property
    def objectives(self) -> list[str]:
        return ["+accuracy", "-context_cost"]

    def get_search_set(self) -> list[Problem]:
        return self._to_problems(self._search)

    def get_test_set(self) -> list[Problem]:
        return self._to_problems(self._test)

    def score(self, problem, output):
        predicted = str(output.get("prediction", "")).strip().lower()
        expected = str(problem.expected).strip().lower()
        correct = 1.0 if predicted == expected else 0.0
        cost = output.get("context_tokens", 0)
        return {"accuracy": correct, "context_cost": cost}

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_ZERO_SHOT, SEED_FEW_SHOT, SEED_SIMILARITY]

    def _to_problems(self, data):
        seen = []
        problems = []
        for i, item in enumerate(data):
            problems.append(Problem(
                problem_id=f"ticket_{i}",
                input={
                    "text": item["text"],
                    "labels": self._labels,
                    "labeled_examples": list(seen),
                },
                expected=item["label"],
            ))
            seen.append({"text": item["text"], "label": item["label"]})
        return problems


# ── Seed harnesses ────────────────────────────────────────────────

SEED_ZERO_SHOT = '''\
"""Zero-shot: just the labels and the ticket text."""

def run(problem):
    text = problem["text"]
    labels = problem.get("labels", [])
    label_str = ", ".join(labels)

    prompt = (
        f"Classify this support ticket into exactly one category: {label_str}\\n\\n"
        f"Ticket: {text}\\n\\n"
        f"Category:"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_FEW_SHOT = '''\
"""Few-shot: include the 4 most recent labeled tickets."""

def run(problem):
    text = problem["text"]
    labels = problem.get("labels", [])
    examples = problem.get("labeled_examples", [])[-4:]

    example_block = ""
    for ex in examples:
        example_block += f"Ticket: {ex['text']}\\nCategory: {ex['label']}\\n\\n"

    label_str = ", ".join(labels)
    prompt = (
        f"Classify this support ticket into exactly one category: {label_str}\\n\\n"
        f"{example_block}"
        f"Ticket: {text}\\n\\n"
        f"Category:"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_SIMILARITY = '''\
"""Similarity retrieval: find the most similar labeled tickets by word overlap."""

def run(problem):
    text = problem["text"]
    labels = problem.get("labels", [])
    examples = problem.get("labeled_examples", [])

    # Score by word overlap
    query_words = set(text.lower().split())
    scored = []
    for ex in examples:
        ex_words = set(ex["text"].lower().split())
        overlap = len(query_words & ex_words)
        scored.append((overlap, ex))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = [ex for _, ex in scored[:5]]

    example_block = ""
    for ex in top:
        example_block += f"Ticket: {ex['text']}\\nCategory: {ex['label']}\\n\\n"

    label_str = ", ".join(labels)
    prompt = (
        f"Classify this support ticket. Categories: {label_str}\\n\\n"
        f"Similar tickets for reference:\\n{example_block}"
        f"Ticket: {text}\\n\\n"
        f"Category:"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''


# Register so the CLI can find it
register_benchmark("support_tickets", SupportTicketBenchmark)


# ── Step 3: Run the search ────────────────────────────────────────

async def main():
    # One .db file holds the entire search — every harness, every trace, every score
    db = Kaos("support-tickets.db")
    router = GEPARouter.from_config("kaos.yaml")

    config = SearchConfig(
        benchmark="support_tickets",
        max_iterations=5,          # 5 iterations for this demo (paper uses 20)
        candidates_per_iteration=2, # 2 candidates per iteration (paper uses 2-3)
        objectives=["+accuracy", "-context_cost"],
        max_parallel_evals=2,
    )

    bench = SupportTicketBenchmark()
    search = MetaHarnessSearch(db, router, bench, config)

    print("Starting Meta-Harness search...")
    print(f"  Benchmark: support ticket classification")
    print(f"  Iterations: {config.max_iterations}")
    print(f"  Candidates/iter: {config.candidates_per_iteration}")
    print(f"  Seed harnesses: {len(bench.get_seed_harnesses())}")
    print(f"  Search set: {len(bench.get_search_set())} problems")
    print()

    result = await search.run()

    # ── Step 4: Inspect what happened ──────────────────────────────

    print("\n" + "=" * 60)
    print(result.summary())
    print("=" * 60)

    # Show the Pareto frontier
    print("\nPareto Frontier:")
    for point in result.frontier.points:
        scores = ", ".join(f"{k}={v:.4f}" for k, v in point.scores.items())
        print(f"  Harness {point.harness_id[:12]}... (iter {point.iteration}): {scores}")

    # Query the database directly — this is what makes KAOS different
    print("\n--- SQL Queries on the Search ---")

    # How many harnesses were evaluated?
    print(f"\nHarnesses evaluated: {result.total_harnesses_evaluated}")

    # Which harnesses failed?
    failed = [r for r in result.all_results if not r.is_success]
    if failed:
        print(f"Failed harnesses: {len(failed)}")
        for f in failed:
            print(f"  {f.harness_id[:12]}... — {f.error}")

    # Token usage across all evaluations
    agents = db.query("""
        SELECT a.name, COUNT(tc.call_id) as calls, COALESCE(SUM(tc.token_count), 0) as tokens
        FROM agents a
        LEFT JOIN tool_calls tc ON a.agent_id = tc.agent_id
        WHERE a.name LIKE 'harness-%' OR a.name LIKE 'proposer-%'
        GROUP BY a.agent_id
        ORDER BY tokens DESC
    """)
    print(f"\nAgent token usage:")
    for a in agents[:10]:
        print(f"  {a['name']:30s} {a['calls']:>4} calls  {a['tokens']:>8,} tokens")

    # Events timeline
    event_counts = db.query("""
        SELECT event_type, COUNT(*) as count
        FROM events
        GROUP BY event_type
        ORDER BY count DESC
    """)
    print(f"\nEvent breakdown:")
    for e in event_counts:
        print(f"  {e['event_type']:25s} {e['count']:>6}")

    db.close()

    print(f"\n--- All data saved to support-tickets.db ---")
    print(f"Inspect with:")
    print(f"  kaos mh frontier {result.search_agent_id} --db support-tickets.db")
    print(f"  kaos mh inspect {result.search_agent_id} <harness-id> --db support-tickets.db")
    print(f"  sqlite3 support-tickets.db 'SELECT * FROM events LIMIT 20'")


if __name__ == "__main__":
    asyncio.run(main())
