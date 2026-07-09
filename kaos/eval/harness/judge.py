"""Blind judge — routes correctness through SurrogateVerifier.

The harness contract: the grader never sees arm identity or any field
that would let it infer which arm produced an answer. We accomplish
this by anonymising + shuffling the per-query records BEFORE handing
them to SurrogateVerifier in heuristic mode (router=None) — that mode
is deterministic and drift-free, so the kappa audit is mechanical.

Correctness itself is set by the probe (e.g. decisive-evidence recall,
tool-call canonical match). The judge does not overturn it; it
aggregates/diagnoses on the anonymised stream and returns the same
per-query labels back, plus a kappa value the verdict gate consumes.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from kaos.eval.harness.types import QueryResult
from kaos.metaharness.verifier import SurrogateVerifier


@dataclass
class JudgedQuery:
    """A probe-built record fed to the blind judge.

    correct must already be the mechanical/blind label (set-membership,
    canonical equality, etc.). qclass and split are passed through as
    QueryResult fields; extras is opaque domain metadata that is NEVER
    shown to the verifier (so arm leakage is impossible by construction).

    ``independent`` is an OPTIONAL second correctness label from a labeler
    that is genuinely independent of the mechanical one (e.g. a human spot
    check or a distinct grader). When present on any item, judge_arm
    computes a REAL kappa = agreement(correct, independent). When absent
    everywhere, the probe is a mechanical-ground-truth probe with no second
    labeler, and kappa is returned as ``None`` (kappa-exempt) rather than a
    tautological 1.0.
    """
    qid: str
    qclass: str
    split: str
    correct: bool
    independent: bool | None = None
    extras: dict = None  # type: ignore[assignment]


def judge_arm(
    arm_name: str,
    judged: list[JudgedQuery],
    *,
    seed: int = 99,
    benchmark_objectives: list[str] | None = None,
) -> tuple[list[QueryResult], float | None]:
    """Run the anonymised stream through SurrogateVerifier and return
    ``(per_query_results, judge_kappa)``.

    judge_kappa is agreement between an INDEPENDENT second label and the
    mechanical label over the items that carry one. If no item carries an
    independent label, the probe has no second labeler and kappa is
    ``None`` (the kappa audit is not applicable and is skipped downstream —
    it is NOT silently reported as 1.0, which was the old tautology
    ``jq.correct == jq.correct``).
    """
    rng = random.Random(seed)
    order = list(range(len(judged)))
    rng.shuffle(order)

    per_problem: list[dict[str, Any]] = []
    for i in order:
        jq = judged[i]
        per_problem.append({
            "id": jq.qid,
            "correct": jq.correct,
            "task": jq.qclass,
        })

    verifier = SurrogateVerifier(router=None)
    verifier.diagnose(
        harness_id="arm:anon",
        per_problem=per_problem,
        benchmark_objectives=benchmark_objectives
        or ["+decisive_evidence_recall"],
    )

    results = [
        QueryResult(
            qid=jq.qid,
            qclass=jq.qclass,
            correct=jq.correct,
            split=jq.split,
            extras=jq.extras or {},
        )
        for jq in judged
    ]

    # Real kappa over items that carry an independent second label (either the
    # `independent` field or extras["independent"]). If none do, the probe is a
    # mechanical-ground-truth probe with no second labeler -> kappa-exempt.
    def _independent(jq: JudgedQuery):
        if jq.independent is not None:
            return jq.independent
        return (jq.extras or {}).get("independent")

    labeled = [jq for jq in judged if _independent(jq) is not None]
    if not labeled:
        kappa: float | None = None
    else:
        sample = labeled[:50]
        agree = sum(1 for jq in sample if bool(jq.correct) == bool(_independent(jq)))
        kappa = agree / len(sample)
    return results, kappa
