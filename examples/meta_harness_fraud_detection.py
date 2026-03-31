"""
Meta-Harness: Optimize Fraud Detection Explanations
=====================================================

Your compliance team uses an LLM to review flagged transactions and
produce fraud/not-fraud decisions with explanations. The current prompt
catches ~65% of actual fraud, with 30% false positives. Meta-Harness
searches for a harness that improves both recall and precision.

Business impact: Fewer false positives = less manual review = lower ops cost.
Higher recall = fewer missed fraud cases = less financial loss.

Real-world harness improvements the search might discover:
- Transaction pattern framing (velocity, amount deviation, geography)
- Customer history context (how much past behavior to include)
- Red flag checklists vs. open-ended reasoning
- Contrastive examples (similar legitimate vs. fraudulent transactions)
- Two-stage: quick screen then deep review for borderline cases

Usage:
    uv run python examples/meta_harness_fraud_detection.py
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


def generate_transactions(n: int = 100, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    transactions = []
    merchants = ["Amazon", "Walmart", "Gas Station", "ATM Withdrawal",
                 "Wire Transfer", "Crypto Exchange", "Luxury Store",
                 "Restaurant", "Online Gaming", "Travel Agency"]

    for i in range(n):
        is_fraud = rng.random() < 0.25  # 25% fraud rate
        amount = rng.gauss(500 if is_fraud else 80, 300 if is_fraud else 50)
        amount = max(5, round(abs(amount), 2))

        txn = {
            "txn_id": f"txn_{i:04d}",
            "amount": amount,
            "merchant": rng.choice(merchants),
            "country": rng.choice(["US", "US", "US", "UK", "BR", "NG", "RU", "CN"]) if is_fraud
                       else rng.choice(["US", "US", "US", "US", "CA", "UK"]),
            "time_of_day": rng.choice(["morning", "afternoon", "evening", "night"]),
            "is_weekend": rng.choice([True, False]),
            "card_present": not is_fraud if rng.random() < 0.7 else is_fraud,
            "customer_avg_txn": round(rng.gauss(75, 30), 2),
            "txn_count_24h": rng.randint(1, 15) if is_fraud else rng.randint(1, 5),
            "days_since_last_txn": rng.randint(0, 3) if not is_fraud else rng.randint(0, 30),
            "account_age_months": rng.randint(1, 60),
            "is_fraud": is_fraud,
        }
        transactions.append(txn)
    return transactions


SEED_BASIC = '''\
"""Basic fraud check — list transaction details and ask."""

def run(problem):
    txn = problem["transaction"]
    features = "\\n".join(f"  {k}: {v}" for k, v in txn.items()
                          if k not in ("txn_id", "is_fraud"))

    prompt = (
        f"Analyze this transaction for fraud.\\n\\n"
        f"Transaction:\\n{features}\\n\\n"
        f"Is this transaction fraudulent? Answer: FRAUD or LEGITIMATE"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_RED_FLAGS = '''\
"""Red flag checklist — structured fraud indicators."""

RED_FLAGS = [
    "Amount > 3x customer average",
    "Transaction from unusual country",
    "Card not present for high-value purchase",
    "Multiple transactions in 24 hours",
    "New account (< 3 months)",
    "Night-time transaction",
    "Crypto or wire transfer",
]

def run(problem):
    txn = problem["transaction"]

    # Pre-compute red flags
    flags = []
    if txn["amount"] > txn["customer_avg_txn"] * 3:
        flags.append("Amount is 3x+ above customer average")
    if txn["country"] not in ("US", "CA", "UK"):
        flags.append(f"Unusual country: {txn['country']}")
    if not txn["card_present"] and txn["amount"] > 200:
        flags.append("Card not present for high-value transaction")
    if txn["txn_count_24h"] > 5:
        flags.append(f"High velocity: {txn['txn_count_24h']} transactions in 24h")
    if txn["account_age_months"] < 3:
        flags.append("New account")

    flag_block = "\\n".join(f"  - {f}" for f in flags) if flags else "  None detected"

    prompt = (
        f"Fraud analysis with red flag checklist.\\n\\n"
        f"Transaction: ${txn['amount']} at {txn['merchant']} ({txn['country']})\\n"
        f"Customer avg: ${txn['customer_avg_txn']}, account age: {txn['account_age_months']}mo\\n\\n"
        f"Red flags detected:\\n{flag_block}\\n\\n"
        f"Based on these indicators, classify: FRAUD or LEGITIMATE"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_CONTRASTIVE = '''\
"""Contrastive examples — show similar fraud and legitimate transactions."""

def run(problem):
    txn = problem["transaction"]
    history = problem.get("historical_transactions", [])

    # Find similar transactions by amount range
    similar_fraud = [t for t in history if t["is_fraud"]
                     and abs(t["amount"] - txn["amount"]) < 200][-2:]
    similar_legit = [t for t in history if not t["is_fraud"]
                     and abs(t["amount"] - txn["amount"]) < 200][-2:]

    examples = ""
    for t in similar_fraud:
        examples += f"  FRAUD: ${t['amount']} at {t['merchant']} ({t['country']}), card_present={t['card_present']}\\n"
    for t in similar_legit:
        examples += f"  LEGIT: ${t['amount']} at {t['merchant']} ({t['country']}), card_present={t['card_present']}\\n"

    features = (
        f"Amount: ${txn['amount']}\\n"
        f"Merchant: {txn['merchant']}\\n"
        f"Country: {txn['country']}\\n"
        f"Card present: {txn['card_present']}\\n"
        f"Transactions in 24h: {txn['txn_count_24h']}\\n"
        f"Customer average: ${txn['customer_avg_txn']}"
    )

    prompt = (
        f"Compare this transaction to known fraud and legitimate patterns.\\n\\n"
        f"Similar past transactions:\\n{examples}\\n"
        f"Current transaction:\\n{features}\\n\\n"
        f"Classify: FRAUD or LEGITIMATE"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''


class FraudDetectionBenchmark(Benchmark):
    """Fraud detection benchmark — classify transactions as fraud/legitimate."""

    def __init__(self, **kwargs):
        self._txns = generate_transactions(100)
        self._search = self._txns[:60]
        self._test = self._txns[60:]

    @property
    def name(self) -> str:
        return "fraud_detection"

    @property
    def objectives(self) -> list[str]:
        return ["+f1_score", "-context_cost"]

    def get_search_set(self) -> list[Problem]:
        return self._to_problems(self._search)

    def get_test_set(self) -> list[Problem]:
        return self._to_problems(self._test)

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        prediction = str(output.get("prediction", "")).upper().strip()
        is_fraud = problem.expected

        predicted_fraud = "FRAUD" in prediction and "LEGITIMATE" not in prediction
        actual_fraud = is_fraud

        # For F1, we track TP/FP/FN per problem (aggregate later)
        tp = 1.0 if predicted_fraud and actual_fraud else 0.0
        fp = 1.0 if predicted_fraud and not actual_fraud else 0.0
        fn = 1.0 if not predicted_fraud and actual_fraud else 0.0
        tn = 1.0 if not predicted_fraud and not actual_fraud else 0.0

        cost = output.get("context_tokens", 0)
        return {"tp": tp, "fp": fp, "fn": fn, "tn": tn, "context_cost": cost}

    def aggregate_scores(self, per_problem: list[dict[str, float]]) -> dict[str, float]:
        tp = sum(s["tp"] for s in per_problem)
        fp = sum(s["fp"] for s in per_problem)
        fn = sum(s["fn"] for s in per_problem)
        tn = sum(s["tn"] for s in per_problem)

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
        avg_cost = sum(s["context_cost"] for s in per_problem) / len(per_problem) if per_problem else 0

        return {"f1_score": f1, "precision": precision, "recall": recall, "context_cost": avg_cost}

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_BASIC, SEED_RED_FLAGS, SEED_CONTRASTIVE]

    def _to_problems(self, txns: list[dict]) -> list[Problem]:
        seen = []
        problems = []
        for i, txn in enumerate(txns):
            problems.append(Problem(
                problem_id=f"fraud_{txn['txn_id']}",
                input={
                    "transaction": {k: v for k, v in txn.items() if k != "is_fraud"},
                    "historical_transactions": list(seen),
                },
                expected=txn["is_fraud"],
                metadata={"is_fraud": txn["is_fraud"]},
            ))
            seen.append(txn)
        return problems


register_benchmark("fraud_detection", FraudDetectionBenchmark)


async def main():
    db = Kaos("fraud-search.db")
    router = GEPARouter.from_config("kaos.yaml")

    bench = FraudDetectionBenchmark()
    config = SearchConfig(
        benchmark="fraud_detection",
        max_iterations=8,
        candidates_per_iteration=2,
        objectives=["+f1_score", "-context_cost"],
        max_parallel_evals=2,
    )

    print("Meta-Harness: Fraud Detection Optimization")
    print(f"  Transactions: {len(bench.get_search_set())} search, {len(bench.get_test_set())} test")
    print(f"  Fraud rate: ~25%")
    print(f"  Seed harnesses: basic, red-flags, contrastive")
    print()

    search = MetaHarnessSearch(db, router, bench, config)
    result = await search.run()

    print("\n" + "=" * 60)
    print(result.summary())

    print("\n--- Compliance Insights ---")
    for point in result.frontier.points:
        f1 = point.scores.get("f1_score", 0)
        prec = point.scores.get("precision", 0)
        rec = point.scores.get("recall", 0)
        cost = point.scores.get("context_cost", 0)
        print(f"  Harness {point.harness_id[:12]}...")
        print(f"    F1: {f1:.2%}  Precision: {prec:.2%}  Recall: {rec:.2%}")
        print(f"    Tokens/review: {cost:.0f}")

    db.close()
    print(f"\nAll data in fraud-search.db")


if __name__ == "__main__":
    asyncio.run(main())
