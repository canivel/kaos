"""
Meta-Harness: Optimize CRM Campaign Message Generation
========================================================

Your marketing team uses an LLM to generate personalized campaign messages
(email subjects, push notifications, SMS). Current messages get ~12% open rate.
Meta-Harness searches for the best harness: which customer data to include,
what tone to use per segment, how to frame the CTA, what past campaigns
to reference.

Business impact: +3% open rate = thousands more engaged customers per campaign.
Better targeting = lower unsubscribe rates.

Real-world harness improvements the search might discover:
- Segment-specific tone (enterprise wants ROI language, consumers want urgency)
- Time-aware messaging (morning vs. evening, day of week)
- Past behavior framing (reference what the customer actually uses)
- A/B test winner patterns (what subject line structures win)
- Anti-patterns (what causes unsubscribes → avoid in prompts)

Usage:
    uv run python examples/meta_harness_crm_campaigns.py
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


# ── Synthetic campaign data ──────────────────────────────────────

CAMPAIGN_TYPES = ["renewal_reminder", "upsell", "feature_announcement", "win_back", "onboarding"]

def generate_campaigns(n: int = 80, seed: int = 42) -> list[dict]:
    rng = random.Random(seed)
    segments = ["enterprise", "smb", "startup", "consumer"]
    campaigns = []

    winning_patterns = {
        "enterprise": {"tone": "professional", "cta": "roi", "length": "short"},
        "smb": {"tone": "friendly", "cta": "savings", "length": "medium"},
        "startup": {"tone": "energetic", "cta": "growth", "length": "short"},
        "consumer": {"tone": "casual", "cta": "urgency", "length": "short"},
    }

    for i in range(n):
        segment = rng.choice(segments)
        campaign_type = rng.choice(CAMPAIGN_TYPES)
        pattern = winning_patterns[segment]

        customer = {
            "name": f"Customer {i}",
            "segment": segment,
            "plan": rng.choice(["basic", "pro", "enterprise"]),
            "months_active": rng.randint(1, 36),
            "last_purchase_days_ago": rng.randint(0, 90),
            "top_feature": rng.choice(["analytics", "integrations", "reporting", "api", "automation"]),
            "open_rate_history": round(rng.uniform(0.05, 0.35), 2),
        }

        # Simulate whether the message was opened (ground truth)
        # Higher open rate if tone matches segment preference
        base_rate = customer["open_rate_history"]
        opened = rng.random() < base_rate

        campaigns.append({
            "customer": customer,
            "campaign_type": campaign_type,
            "winning_tone": pattern["tone"],
            "winning_cta": pattern["cta"],
            "opened": opened,
            "best_subject_line": f"[{pattern['tone'].upper()}] {campaign_type.replace('_', ' ').title()}",
        })

    return campaigns


# ── Seed harnesses ────────────────────────────────────────────────

SEED_GENERIC = '''\
"""Generic message generator — same template for everyone."""

def run(problem):
    customer = problem["customer"]
    campaign_type = problem["campaign_type"]

    prompt = (
        f"Write a short email subject line for a {campaign_type.replace('_', ' ')} campaign.\\n\\n"
        f"Customer: {customer['name']}, {customer['segment']} segment, "
        f"{customer['plan']} plan, {customer['months_active']} months active.\\n\\n"
        f"Subject line:"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_SEGMENT_TONE = '''\
"""Segment-aware tone — match language to customer type."""

TONE_GUIDE = {
    "enterprise": "Professional, ROI-focused. Mention business impact and efficiency.",
    "smb": "Friendly and practical. Mention cost savings and time saved.",
    "startup": "Energetic, growth-focused. Mention scale and competitive advantage.",
    "consumer": "Casual, urgent. Use time pressure and personal benefit.",
}

def run(problem):
    customer = problem["customer"]
    campaign_type = problem["campaign_type"]
    segment = customer["segment"]

    tone = TONE_GUIDE.get(segment, "Professional")

    prompt = (
        f"Write an email subject line for a {campaign_type.replace('_', ' ')} campaign.\\n\\n"
        f"Tone: {tone}\\n\\n"
        f"Customer: {customer['name']}, {customer['segment']}, "
        f"{customer['plan']} plan, uses {customer['top_feature']} most.\\n\\n"
        f"Subject line:"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''

SEED_BEHAVIOR_AWARE = '''\
"""Behavior-aware — reference what the customer actually does."""

def run(problem):
    customer = problem["customer"]
    campaign_type = problem["campaign_type"]
    past_campaigns = problem.get("past_campaigns", [])

    # Find what worked for similar customers
    similar = [c for c in past_campaigns
               if c["customer"]["segment"] == customer["segment"]
               and c["opened"]][-3:]

    examples_block = ""
    for ex in similar:
        examples_block += f"  Opened: \\"{ex['best_subject_line']}\\"\\n"

    prompt = (
        f"Write an email subject line for a {campaign_type.replace('_', ' ')} campaign.\\n\\n"
        f"Customer profile:\\n"
        f"  Name: {customer['name']}\\n"
        f"  Segment: {customer['segment']}\\n"
        f"  Most used feature: {customer['top_feature']}\\n"
        f"  Last purchase: {customer['last_purchase_days_ago']} days ago\\n"
        f"  Historical open rate: {customer['open_rate_history']:.0%}\\n\\n"
        f"Subject lines that worked for similar customers:\\n{examples_block}\\n"
        f"Subject line:"
    )

    return {"prompt": prompt, "context_tokens": len(prompt.split())}
'''


# ── Benchmark ─────────────────────────────────────────────────────

class CRMCampaignBenchmark(Benchmark):
    """CRM campaign message optimization benchmark.

    Score: does the generated message match the winning tone/CTA pattern
    for the customer's segment? (Proxy for open rate optimization.)
    """

    def __init__(self, **kwargs):
        self._campaigns = generate_campaigns(80)
        self._search = self._campaigns[:50]
        self._test = self._campaigns[50:]

    @property
    def name(self) -> str:
        return "crm_campaigns"

    @property
    def objectives(self) -> list[str]:
        return ["+relevance", "-context_cost"]

    def get_search_set(self) -> list[Problem]:
        return self._to_problems(self._search)

    def get_test_set(self) -> list[Problem]:
        return self._to_problems(self._test)

    def score(self, problem: Problem, output: dict[str, Any]) -> dict[str, float]:
        prediction = str(output.get("prediction", "")).lower()
        expected_tone = str(problem.metadata.get("winning_tone", "")).lower()
        expected_cta = str(problem.metadata.get("winning_cta", "")).lower()

        # Score: does the message align with the winning pattern?
        tone_match = 1.0 if expected_tone in prediction else 0.0
        cta_match = 1.0 if expected_cta in prediction else 0.0
        not_empty = 1.0 if len(prediction) > 10 else 0.0

        relevance = (tone_match * 0.4 + cta_match * 0.4 + not_empty * 0.2)
        cost = output.get("context_tokens", 0)
        return {"relevance": relevance, "context_cost": cost}

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_GENERIC, SEED_SEGMENT_TONE, SEED_BEHAVIOR_AWARE]

    def _to_problems(self, campaigns: list[dict]) -> list[Problem]:
        seen = []
        problems = []
        for i, camp in enumerate(campaigns):
            problems.append(Problem(
                problem_id=f"campaign_{i}",
                input={
                    "customer": camp["customer"],
                    "campaign_type": camp["campaign_type"],
                    "past_campaigns": list(seen),
                },
                expected=camp["best_subject_line"],
                metadata={
                    "winning_tone": camp["winning_tone"],
                    "winning_cta": camp["winning_cta"],
                    "opened": camp["opened"],
                },
            ))
            seen.append(camp)
        return problems


register_benchmark("crm_campaigns", CRMCampaignBenchmark)


async def main():
    db = Kaos("crm-search.db")
    router = GEPARouter.from_config("kaos.yaml")

    bench = CRMCampaignBenchmark()
    config = SearchConfig(
        benchmark="crm_campaigns",
        max_iterations=8,
        candidates_per_iteration=2,
        objectives=["+relevance", "-context_cost"],
        max_parallel_evals=2,
    )

    print("Meta-Harness: CRM Campaign Optimization")
    print(f"  Campaigns: {len(bench.get_search_set())} search, {len(bench.get_test_set())} test")
    print(f"  Seed harnesses: generic, segment-tone, behavior-aware")
    print()

    search = MetaHarnessSearch(db, router, bench, config)
    result = await search.run()

    print("\n" + "=" * 60)
    print(result.summary())

    print("\n--- Marketing Insights ---")
    for point in result.frontier.points:
        rel = point.scores.get("relevance", 0)
        cost = point.scores.get("context_cost", 0)
        print(f"  Harness {point.harness_id[:12]}...")
        print(f"    Relevance score: {rel:.0%}")
        print(f"    Tokens/message: {cost:.0f}")

    db.close()
    print(f"\nAll data in crm-search.db")


if __name__ == "__main__":
    asyncio.run(main())
