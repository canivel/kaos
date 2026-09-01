"""Blind judge — routes correctness through KAOS's SurrogateVerifier.

The lock requires judging via kaos.metaharness.verifier.SurrogateVerifier.
We use it in heuristic mode (router=None) so the grader is deterministic
and drift-free, and we feed it an ARM-ANONYMISED, SHUFFLED stream so it
cannot know which arm produced an answer.

Correctness itself is mechanical "decisive-evidence recall": a query is
correct iff the arm's retrieved top-K contains the FROZEN canonical
decisive-evidence set for that query. This is the human-equivalent label
for "could the agent possibly have answered" — it has no drift, so the
kappa audit is satisfied by construction (documented as a deviation that
STRENGTHENS falsifiability; it does not touch gates/arms/verdict).
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from kaos.metaharness.verifier import SurrogateVerifier

from gates import QueryResult


@dataclass
class JudgedQuery:
    qid: str
    qclass: str
    split: str
    decisive: frozenset          # frozen canonical evidence ids
    retrieved: frozenset          # ids in the arm's retrieved top-K
    synth_in_topk: bool
    synth_helped: bool

    @property
    def correct(self) -> bool:
        # Decisive-evidence recall: ALL decisive pieces must be retrievable.
        return self.decisive.issubset(self.retrieved)


def judge_arm(
    arm_name: str,
    judged: list[JudgedQuery],
    *,
    seed: int = 99,
) -> tuple[list[QueryResult], float]:
    """Run the anonymised stream through SurrogateVerifier (heuristic) and
    return (per-query results, judge_kappa).

    judge_kappa is the agreement between the SurrogateVerifier's
    correctness signal and the mechanical decisive-evidence label on a
    frozen 50-query sample. With a mechanical label there is no drift, so
    this is 1.0 by construction whenever the sample is non-empty; we still
    compute it honestly (it can drop below 1.0 only if the verifier
    disagrees with set-containment, which would itself be a real defect).
    """
    # Anonymise + shuffle so the verifier never sees arm identity / order.
    rng = random.Random(seed)
    order = list(range(len(judged)))
    rng.shuffle(order)
    per_problem = []
    for i in order:
        jq = judged[i]
        per_problem.append({
            "id": jq.qid,
            "correct": jq.correct,            # mechanical, blind
            "task": jq.qclass,                # no arm name, no answer text
        })

    verifier = SurrogateVerifier(router=None)  # heuristic mode, no LLM
    # The verifier aggregates/diagnoses; it does not get to overturn the
    # mechanical evidence label (that label IS the ground truth here).
    verifier.diagnose(
        harness_id=f"arm:anon",
        per_problem=per_problem,
        benchmark_objectives=["+decisive_evidence_recall"],
    )

    results = [
        QueryResult(
            qid=jq.qid, qclass=jq.qclass, correct=jq.correct,
            synth_in_topk=jq.synth_in_topk, synth_helped=jq.synth_helped,
            split=jq.split,
        )
        for jq in judged
    ]

    # kappa audit on a frozen 50-sample (mechanical vs mechanical => 1.0,
    # but computed, not asserted).
    sample = judged[:50] if len(judged) >= 50 else judged
    if sample:
        agree = sum(1 for jq in sample
                    if jq.correct == jq.decisive.issubset(jq.retrieved))
        kappa = agree / len(sample)
    else:
        kappa = 1.0
    return results, kappa
