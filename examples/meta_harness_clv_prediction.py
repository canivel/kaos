"""
Meta-Harness: Optimize Customer Lifetime Value (CLV/LTV) Predictions
=====================================================================

Your LLM predicts customer lifetime value from profile + behavior data.
The current prompt gets ~40% of predictions within 20% of actual CLV.
Meta-Harness finds the best harness for framing the prediction task:
which features to highlight, what few-shot examples to retrieve, how
to structure the reasoning chain.

Business impact: Better CLV predictions → smarter acquisition spend,
better retention targeting, more accurate revenue forecasting.

Real-world harness improvements the search might discover:
- Segment-aware prompting (high-value vs. churning customers need different framing)
- Recency-weighted examples (recent purchases matter more than old ones)
- Multi-step reasoning: predict churn probability first, then CLV conditional on retention
- Feature prioritization: which customer attributes to emphasize in the prompt

Usage:
    uv run python examples/meta_harness_clv_prediction.py
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

from kaos import Kaos
from kaos.metaharness.harness import SearchConfig
from kaos.metaharness.search import MetaHarnessSearch
from kaos.metaharness.benchmarks.base import Benchmark, Problem
from kaos.metaharness.benchmarks import register_benchmark
from kaos.router.gepa import GEPARouter


# ── Synthetic customer data ──────────────────────────────────────

def generate_customers(n: int = 100, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    customers = []
    segments = ["enterprise", "smb", "startup", "consumer"]
    industries = ["saas", "ecommerce", "fintech", "healthcare", "education"]

    for i in range(n):
        segment = rng.choice(segments)
        industry = rng.choice(industries)
        months_active = rng.randint(1, 48)
        monthly_spend = rng.gauss(
            {"enterprise": 5000, "smb": 800, "startup": 300, "consumer": 50}[segment],
            {"enterprise": 2000, "smb": 300, "startup": 150, "consumer": 30}[segment],
        )
        monthly_spend = max(10, monthly_spend)
        support_tickets = rng.randint(0, 20)
        feature_usage = rng.uniform(0.1, 1.0)
        nps_score = rng.randint(1, 10)

        # CLV model: spend * retention probability * projected months
        churn_risk = 0.3 - (feature_usage * 0.2) + (support_tickets * 0.01) - (nps_score * 0.02)
        churn_risk = max(0.05, min(0.8, churn_risk))
        projected_months = max(1, int((1 / churn_risk) * 6))
        actual_clv = round(monthly_spend * projected_months * (1 - churn_risk), 2)

        customers.append({
            "customer_id": f"cust_{i:04d}",
            "segment": segment,
            "industry": industry,
            "months_active": months_active,
            "monthly_spend": round(monthly_spend, 2),
            "support_tickets_last_90d": support_tickets,
            "feature_usage_pct": round(feature_usage * 100, 1),
            "nps_score": nps_score,
            "contract_type": rng.choice(["monthly", "annual"]),
            "last_login_days_ago": rng.randint(0, 60),
            "actual_clv": actual_clv,
        })
    return customers


# ── Seed harnesses ────────────────────────────────────────────────

SEED_BASIC = '''\
"""Basic CLV prediction — list all features and ask for a number."""

def run(problem):
    customer = problem["customer"]

    features = "\\n".join(f"  {k}: {v}" for k, v in customer.items()
                          if k not in ("customer_id", "actual_clv"))

    prompt = (
        f"Predict the Customer Lifetime Value (CLV) for this customer.\\n\\n"
        f"Customer profile:\\n{features}\\n\\n"
        f"Predict the CLV in dollars. Return just a number.\\n"
        f"CLV: $"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_SEGMENT_AWARE = '''\
"""Segment-aware CLV — frame the prediction differently per segment."""

SEGMENT_CONTEXT = {
    "enterprise": "Enterprise customers have long contracts and high spend but slow expansion.",
    "smb": "SMB customers have moderate spend with higher churn risk than enterprise.",
    "startup": "Startups have low initial spend but high growth potential if they succeed.",
    "consumer": "Consumer customers have low individual value but high volume.",
}

def run(problem):
    customer = problem["customer"]
    examples = problem.get("historical_customers", [])
    segment = customer.get("segment", "unknown")

    # Filter examples to same segment
    segment_examples = [e for e in examples if e.get("segment") == segment][-3:]

    example_block = ""
    for ex in segment_examples:
        example_block += (
            f"  Segment: {ex['segment']}, Monthly: ${ex['monthly_spend']}, "
            f"Active: {ex['months_active']}mo, NPS: {ex['nps_score']} "
            f"→ CLV: ${ex['actual_clv']}\\n"
        )

    context = SEGMENT_CONTEXT.get(segment, "")
    features = "\\n".join(f"  {k}: {v}" for k, v in customer.items()
                          if k not in ("customer_id", "actual_clv"))

    prompt = (
        f"Predict Customer Lifetime Value (CLV).\\n\\n"
        f"Segment context: {context}\\n\\n"
        f"Similar customers and their CLVs:\\n{example_block}\\n"
        f"Customer profile:\\n{features}\\n\\n"
        f"CLV: $"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_CHURN_FIRST = '''\
"""Two-step: predict churn risk first, then CLV conditional on retention."""

def run(problem):
    customer = problem["customer"]

    features = "\\n".join(f"  {k}: {v}" for k, v in customer.items()
                          if k not in ("customer_id", "actual_clv"))

    prompt = (
        f"Predict Customer Lifetime Value using a two-step approach.\\n\\n"
        f"Customer profile:\\n{features}\\n\\n"
        f"Step 1: Estimate the churn probability (0-100%) based on:\\n"
        f"  - Feature usage (higher = lower churn)\\n"
        f"  - NPS score (higher = lower churn)\\n"
        f"  - Support tickets (higher = higher churn)\\n"
        f"  - Last login recency (more recent = lower churn)\\n\\n"
        f"Step 2: Estimate projected months of retention.\\n\\n"
        f"Step 3: CLV = monthly_spend * projected_months * (1 - churn_probability)\\n\\n"
        f"Show your reasoning, then give the final CLV.\\n"
        f"CLV: $"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''


# ── Benchmark ─────────────────────────────────────────────────────

class CLVBenchmark(Benchmark):
    """Customer Lifetime Value prediction benchmark."""

    def __init__(self, **kwargs):
        self._customers = generate_customers(100)
        self._search = self._customers[:60]
        self._test = self._customers[60:]

    @property
    def name(self) -> str:
        return "clv_prediction"

    @property
    def objectives(self) -> list[str]:
        return ["+accuracy", "-context_cost"]

    def get_search_set(self) -> list[Problem]:
        return self._to_problems(self._search)

    def get_test_set(self) -> list[Problem]:
        return self._to_problems(self._test)

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        try:
            predicted = float(str(output.get("prediction", "0")).replace("$", "").replace(",", ""))
        except (ValueError, TypeError):
            predicted = 0.0
        actual = float(problem.expected)

        # Accuracy: within 20% of actual CLV
        if actual > 0:
            pct_error = abs(predicted - actual) / actual
            correct = 1.0 if pct_error <= 0.20 else 0.0
        else:
            correct = 1.0 if predicted < 100 else 0.0

        cost = output.get("context_tokens", 0)
        return {"accuracy": correct, "context_cost": cost}

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_BASIC, SEED_SEGMENT_AWARE, SEED_CHURN_FIRST]

    def _to_problems(self, customers: list[dict]) -> list[Problem]:
        seen = []
        problems = []
        for i, cust in enumerate(customers):
            problems.append(Problem(
                problem_id=f"clv_{cust['customer_id']}",
                input={
                    "customer": {k: v for k, v in cust.items() if k != "actual_clv"},
                    "historical_customers": list(seen),
                },
                expected=cust["actual_clv"],
                metadata={"segment": cust["segment"]},
            ))
            seen.append(cust)
        return problems


register_benchmark("clv_prediction", CLVBenchmark)


async def main():
    db = Kaos("clv-search.db")
    router = GEPARouter.from_config("kaos.yaml")

    bench = CLVBenchmark()
    config = SearchConfig(
        benchmark="clv_prediction",
        max_iterations=8,
        candidates_per_iteration=2,
        objectives=["+accuracy", "-context_cost"],
        max_parallel_evals=2,
    )

    print("Meta-Harness: CLV/LTV Prediction Optimization")
    print(f"  Customers: {len(bench.get_search_set())} search, {len(bench.get_test_set())} test")
    print(f"  Seed harnesses: basic, segment-aware, churn-first")
    print()

    search = MetaHarnessSearch(db, router, bench, config)
    result = await search.run()

    print("\n" + "=" * 60)
    print(result.summary())

    # Business insights from the search
    print("\n--- Business Insights ---")
    for point in result.frontier.points:
        acc = point.scores.get("accuracy", 0)
        cost = point.scores.get("context_cost", 0)
        print(f"  Harness {point.harness_id[:12]}...")
        print(f"    Accuracy: {acc:.0%} predictions within 20% of actual CLV")
        print(f"    Context cost: {cost:.0f} tokens/prediction")

    db.close()
    print(f"\nAll data in clv-search.db")


if __name__ == "__main__":
    asyncio.run(main())
