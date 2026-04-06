"""Comprehensive quality eval for smart context compaction.

Tests whether compacted digests preserve the information a proposer needs
to make correct decisions. Uses 24 diagnostic questions across 4 tiers:

Tier 1 — Direct facts (can you read a specific value?)
Tier 2 — Comparison (can you compare two harnesses?)
Tier 3 — Causal reasoning (can you explain WHY something failed?)
Tier 4 — Synthesis (can you combine evidence to form a strategy?)

Each question has search terms that must appear in the digest.
A question is "answerable" if ALL its required terms are present.
"""

import json
import sys

from kaos.metaharness.compactor import Compactor


# ── Realistic archive data ──────────────────────────────────────

REALISTIC_HARNESSES = [
    {
        "harness_id": "seed_zero_shot",
        "iteration": 0,
        "scores": {"accuracy": 0.0, "context_cost": 22.75},
        "source": (
            '"""Zero-shot text classification."""\n'
            'def run(problem):\n'
            '    text = problem["text"]\n'
            '    labels = problem.get("labels", [])\n'
            '    label_str = ", ".join(labels)\n'
            '    prompt = f"Classify: {label_str}\\nText: {text}\\nCategory:"\n'
            '    try:\n'
            '        response = llm(prompt, max_tokens=32)\n'
            '        return {"prediction": response.strip(), "context_tokens": len(prompt.split())}\n'
            '    except NameError:\n'
            '        return {"prompt": prompt, "context_tokens": len(prompt.split())}\n'
        ),
        "per_problem": [
            {"problem_id": f"custom_{i}", "correct": False,
             "scores": {"accuracy": 0.0, "context_cost": 22},
             "output": {"prediction": ""}} for i in range(8)
        ],
        "error": None,
    },
    {
        "harness_id": "seed_few_shot",
        "iteration": 0,
        "scores": {"accuracy": 0.0, "context_cost": 70.6},
        "source": (
            '"""Few-shot classification with labeled examples."""\n'
            'def run(problem):\n'
            '    text = problem["text"]\n'
            '    examples = problem.get("labeled_examples", [])[-8:]\n'
            '    prompt = "Examples:\\n"\n'
            '    for ex in examples:\n'
            '        prompt += f"Text: {ex[\'text\']}\\nCategory: {ex[\'label\']}\\n"\n'
            '    prompt += f"\\nText: {text}\\nCategory:"\n'
            '    try:\n'
            '        return {"prediction": llm(prompt, max_tokens=32).strip(),\n'
            '                "context_tokens": len(prompt.split())}\n'
            '    except NameError:\n'
            '        return {"prompt": prompt, "context_tokens": len(prompt.split())}\n'
        ),
        "per_problem": [
            {"problem_id": f"custom_{i}", "correct": False,
             "scores": {"accuracy": 0.0, "context_cost": 70},
             "output": {"prediction": ""}} for i in range(8)
        ],
        "error": None,
    },
    {
        "harness_id": "seed_retrieval",
        "iteration": 0,
        "scores": {"accuracy": 0.0, "context_cost": 97.0},
        "source": (
            '"""Retrieval-based classification with word overlap."""\n'
            'def run(problem):\n'
            '    text = problem["text"]\n'
            '    labels = problem.get("labels", [])\n'
            '    labeled = problem.get("labeled_examples", [])\n'
            '    query = set(text.lower().split())\n'
            '    scored = []\n'
            '    for ex in labeled:\n'
            '        overlap = len(query & set(ex["text"].lower().split()))\n'
            '        scored.append((overlap, ex))\n'
            '    scored.sort(key=lambda x: x[0], reverse=True)\n'
            '    top = [ex for _, ex in scored[:5]]\n'
            '    block = "".join(f"Text: {ex[\'text\']}\\nCat: {ex[\'label\']}\\n" for ex in top)\n'
            '    prompt = f"Examples:\\n{block}\\nText: {text}\\nCategory:"\n'
            '    try:\n'
            '        return {"prediction": llm(prompt, max_tokens=32).strip(),\n'
            '                "context_tokens": len(prompt.split())}\n'
            '    except NameError:\n'
            '        return {"prompt": prompt, "context_tokens": len(prompt.split())}\n'
        ),
        "per_problem": [
            {"problem_id": f"custom_{i}", "correct": False,
             "scores": {"accuracy": 0.0, "context_cost": 97},
             "output": {"prediction": ""}} for i in range(8)
        ],
        "error": None,
    },
    {
        "harness_id": "proposed_keyword_classifier",
        "iteration": 2,
        "scores": {"accuracy": 1.0, "context_cost": 8.0},
        "source": (
            '"""Domain keyword classifier --- zero LLM calls."""\n'
            'DOMAIN_KEYWORDS = {\n'
            '    "technology": ["gpu", "cpu", "cloud", "compiler", "llm", "distributed",\n'
            '                   "container", "webassembly", "edge", "latency"],\n'
            '    "science": ["protein", "quantum", "telescope", "climate", "coral",\n'
            '                "gene", "entanglement", "neural", "plasticity"],\n'
            '    "business": ["revenue", "merger", "startup", "funding", "mortgage",\n'
            '                 "supply", "chain", "consumer", "trade"],\n'
            '    "sports": ["championship", "quarterback", "marathon", "draft", "olympic",\n'
            '               "tournament", "injury", "acl", "franchise"],\n'
            '}\n'
            '\n'
            'def run(problem):\n'
            '    text = problem["text"].lower()\n'
            '    labels = problem.get("labels", [])\n'
            '    scores = {}\n'
            '    for label in labels:\n'
            '        kws = DOMAIN_KEYWORDS.get(label, [])\n'
            '        scores[label] = sum(1 for kw in kws if kw in text)\n'
            '    best = max(scores, key=scores.get) if scores else labels[0]\n'
            '    return {"prediction": best, "context_tokens": len(text.split()),\n'
            '            "method": "keyword_match", "keyword_hits": scores.get(best, 0)}\n'
        ),
        "per_problem": [
            {"problem_id": "custom_1", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 8},
             "output": {"prediction": "technology", "method": "keyword_match", "keyword_hits": 3}},
            {"problem_id": "custom_2", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 9},
             "output": {"prediction": "science", "method": "keyword_match", "keyword_hits": 2}},
            {"problem_id": "custom_3", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 7},
             "output": {"prediction": "business", "method": "keyword_match", "keyword_hits": 4}},
            {"problem_id": "custom_4", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 8},
             "output": {"prediction": "sports", "method": "keyword_match", "keyword_hits": 2}},
            {"problem_id": "custom_5", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 7},
             "output": {"prediction": "technology", "method": "keyword_match"}},
            {"problem_id": "custom_6", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 9},
             "output": {"prediction": "science", "method": "keyword_match"}},
            {"problem_id": "custom_7", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 8},
             "output": {"prediction": "business", "method": "keyword_match"}},
            {"problem_id": "custom_8", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 8},
             "output": {"prediction": "sports", "method": "keyword_match"}},
        ],
        "error": None,
    },
    {
        "harness_id": "failed_llm_caller",
        "iteration": 1,
        "scores": {},
        "source": (
            'def run(p):\n'
            '    import httpx\n'
            '    r = httpx.post("http://localhost:8000/v1/chat/completions",\n'
            '                   json={"model": "qwen", "messages": [{"role": "user", "content": p["text"]}]})\n'
            '    return {"prediction": r.json()["choices"][0]["message"]["content"]}\n'
        ),
        "per_problem": [
            {"problem_id": f"custom_{i}", "correct": False,
             "scores": {"accuracy": 0.0, "context_cost": 0},
             "error": "ConnectError: All connection attempts failed"} for i in range(8)
        ],
        "error": None,
    },
    {
        "harness_id": "proposed_tfidf_hybrid",
        "iteration": 2,
        "scores": {"accuracy": 0.375, "context_cost": 8.0},
        "source": (
            '"""TF-IDF hybrid: keyword fallback + example voting."""\n'
            'import math, re\n'
            'from collections import Counter\n'
            '\n'
            'def _tokenize(text):\n'
            '    return re.findall(r"[a-zA-Z]+", text.lower())\n'
            '\n'
            'def run(problem):\n'
            '    text = problem["text"]\n'
            '    labels = problem.get("labels", [])\n'
            '    examples = problem.get("labeled_examples", [])\n'
            '    tokens = _tokenize(text)\n'
            '    if examples:\n'
            '        votes = Counter()\n'
            '        for ex in examples:\n'
            '            ex_tokens = set(_tokenize(ex["text"]))\n'
            '            overlap = len(set(tokens) & ex_tokens)\n'
            '            if overlap > 2:\n'
            '                votes[ex["label"]] += overlap\n'
            '        if votes:\n'
            '            return {"prediction": votes.most_common(1)[0][0],\n'
            '                    "context_tokens": len(tokens), "method": "tfidf_vote"}\n'
            '    # fallback: first label\n'
            '    return {"prediction": labels[0] if labels else "",\n'
            '            "context_tokens": len(tokens), "method": "fallback"}\n'
        ),
        "per_problem": [
            {"problem_id": "custom_1", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 8},
             "output": {"prediction": "technology", "method": "tfidf_vote"}},
            {"problem_id": "custom_2", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 9},
             "output": {"prediction": "technology", "method": "fallback"}},
            {"problem_id": "custom_3", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 7},
             "output": {"prediction": "business", "method": "tfidf_vote"}},
            {"problem_id": "custom_4", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 8},
             "output": {"prediction": "technology", "method": "fallback"}},
            {"problem_id": "custom_5", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 7},
             "output": {"prediction": "technology", "method": "fallback"}},
            {"problem_id": "custom_6", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 9},
             "output": {"prediction": "science", "method": "tfidf_vote"}},
            {"problem_id": "custom_7", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 8},
             "output": {"prediction": "technology", "method": "fallback"}},
            {"problem_id": "custom_8", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 8},
             "output": {"prediction": "technology", "method": "fallback"}},
        ],
        "error": None,
    },
]

FRONTIER = {
    "objectives": {"accuracy": "maximize", "context_cost": "minimize"},
    "points": [
        {"harness_id": "proposed_keyword_classifier", "iteration": 2,
         "scores": {"accuracy": 1.0, "context_cost": 8.0}},
        {"harness_id": "seed_zero_shot", "iteration": 0,
         "scores": {"accuracy": 0.0, "context_cost": 22.75}},
    ],
}


# ── 24 diagnostic questions in 4 tiers ──────────────────────────

DIAGNOSTIC_QUESTIONS = {
    # ── Tier 1: Direct facts ────────────────────────────────────
    "T1_01_best_accuracy": {
        "tier": 1,
        "question": "What is the highest accuracy achieved?",
        "terms": ["1.0000"],
    },
    "T1_02_best_harness_id": {
        "tier": 1,
        "question": "Which harness achieved the best accuracy?",
        "terms": ["keyword"],
    },
    "T1_03_worst_cost": {
        "tier": 1,
        "question": "Which harness has the highest context cost?",
        "terms": ["97"],
    },
    "T1_04_best_cost": {
        "tier": 1,
        "question": "What is the lowest context cost for a working harness?",
        "terms": ["8.0"],
    },
    "T1_05_how_many_seeds": {
        "tier": 1,
        "question": "How many seed harnesses were there?",
        "terms": ["iteration 0"],
    },
    "T1_06_frontier_size": {
        "tier": 1,
        "question": "How many harnesses are on the Pareto frontier?",
        "terms": ["frontier"],
    },
    "T1_07_source_readable": {
        "tier": 1,
        "question": "Can we read the winning harness source code?",
        "terms": ["def run"],
    },
    # ── Tier 2: Comparison ──────────────────────────────────────
    "T2_08_keyword_vs_tfidf": {
        "tier": 2,
        "question": "How does keyword classifier compare to TF-IDF hybrid?",
        "terms": ["1.0000", "0.375"],
    },
    "T2_09_seed_vs_proposed": {
        "tier": 2,
        "question": "Did proposed harnesses outperform seeds?",
        "terms": ["0.0000", "1.0000"],
    },
    "T2_10_cost_tradeoff": {
        "tier": 2,
        "question": "Is there a cost/accuracy tradeoff on the frontier?",
        "terms": ["accuracy", "context_cost"],
    },
    "T2_11_few_shot_vs_retrieval_cost": {
        "tier": 2,
        "question": "Which seed used more tokens: few-shot or retrieval?",
        "terms": ["70", "97"],
    },
    "T2_12_iteration_progress": {
        "tier": 2,
        "question": "Did accuracy improve from iteration 0 to iteration 2?",
        "terms": ["iteration 0", "iteration 2"],
    },
    # ── Tier 3: Causal reasoning ────────────────────────────────
    "T3_13_why_seeds_failed": {
        "tier": 3,
        "question": "Why did all seeds score 0% accuracy?",
        "terms": ["wrong", "0.0000"],
    },
    "T3_14_why_llm_caller_failed": {
        "tier": 3,
        "question": "Why did the LLM caller harness fail?",
        "terms": ["connect"],
    },
    "T3_15_why_keyword_works": {
        "tier": 3,
        "question": "What technique does the winning harness use?",
        "terms": ["DOMAIN_KEYWORDS"],
    },
    "T3_16_tfidf_failure_mode": {
        "tier": 3,
        "question": "What is the TF-IDF hybrid's main failure mode?",
        "terms": ["fallback"],
    },
    "T3_17_error_pattern_visible": {
        "tier": 3,
        "question": "Are error patterns extracted (not just raw traces)?",
        "terms": ["wrong"],
    },
    "T3_18_connection_error_detail": {
        "tier": 3,
        "question": "What specific error did the localhost LLM call produce?",
        "terms": ["connection"],
    },
    # ── Tier 4: Synthesis ───────────────────────────────────────
    "T4_19_avoid_llm_approach": {
        "tier": 4,
        "question": "Should the next proposer avoid calling external LLMs?",
        "terms": ["connect", "DOMAIN_KEYWORDS"],
        "logic": "both_needed",
    },
    "T4_20_improve_tfidf_strategy": {
        "tier": 4,
        "question": "Can we identify how to improve the TF-IDF hybrid?",
        "terms": ["fallback", "tfidf"],
    },
    "T4_21_keyword_list_extensible": {
        "tier": 4,
        "question": "Is the keyword list visible so a proposer could extend it?",
        "terms": ["gpu", "protein", "revenue", "championship"],
    },
    "T4_22_method_field_visible": {
        "tier": 4,
        "question": "Can the proposer see which method was used per prediction?",
        "terms": ["keyword_match"],
    },
    "T4_23_zero_cost_approach_visible": {
        "tier": 4,
        "question": "Is it clear the winning approach uses zero LLM tokens?",
        "terms": ["keyword", "8.0"],
    },
    "T4_24_all_approaches_visible": {
        "tier": 4,
        "question": "Can the proposer see all distinct approaches tried?",
        "terms": ["zero-shot", "few-shot", "keyword"],
        "logic": "any_two",
    },
}


def check_question(digest_lower: str, qdata: dict) -> bool:
    """Check if a question is answerable from the digest."""
    terms = qdata["terms"]
    logic = qdata.get("logic", "all")

    if logic == "all":
        return all(t.lower() in digest_lower for t in terms)
    elif logic == "both_needed":
        return all(t.lower() in digest_lower for t in terms)
    elif logic == "any_two":
        found = sum(1 for t in terms if t.lower() in digest_lower)
        return found >= 2
    return False


def evaluate_quality():
    print("=" * 72)
    print("COMPACTION QUALITY EVALUATION — 24 questions, 4 tiers")
    print("=" * 72)
    print()

    all_results = []

    for level in range(0, 11):
        c = Compactor(level=level)
        digest, metrics = c.build_digest(REALISTIC_HARNESSES, FRONTIER)
        digest_lower = digest.lower()

        tier_results = {1: [], 2: [], 3: [], 4: []}
        total_pass = 0

        for qname, qdata in DIAGNOSTIC_QUESTIONS.items():
            passed = check_question(digest_lower, qdata)
            tier_results[qdata["tier"]].append((qname, passed))
            if passed:
                total_pass += 1

        tier_scores = {}
        for tier in range(1, 5):
            items = tier_results[tier]
            tier_scores[tier] = sum(1 for _, p in items if p)

        quality = total_pass / len(DIAGNOSTIC_QUESTIONS)

        all_results.append({
            "level": level,
            "chars": metrics.compacted_chars,
            "savings": metrics.savings_pct,
            "total_pass": total_pass,
            "quality": quality,
            "tier_scores": tier_scores,
            "tier_results": tier_results,
        })

        t1 = f"T1:{tier_scores[1]}/7"
        t2 = f"T2:{tier_scores[2]}/5"
        t3 = f"T3:{tier_scores[3]}/6"
        t4 = f"T4:{tier_scores[4]}/6"
        bar = "#" * int(quality * 30)

        print(
            f"Level {level:2d} | {metrics.compacted_chars:5d} chars "
            f"({metrics.savings_pct:4.0f}% saved) | "
            f"{total_pass}/24 | {t1} {t2} {t3} {t4} | "
            f"[{bar:30s}]"
        )

    # Detail: what's lost
    print()
    print("-" * 72)
    print("INFORMATION LOSS BY TIER")
    print("-" * 72)
    for r in all_results:
        lost = []
        for tier in range(1, 5):
            for qname, passed in r["tier_results"][tier]:
                if not passed:
                    lost.append(f"T{tier}:{qname.split('_', 2)[-1]}")
        if lost:
            print(f"Level {r['level']:2d}: LOST [{', '.join(lost)}]")

    # Validations
    print()
    print("-" * 72)
    print("VALIDATION")
    print("-" * 72)

    passed_v = 0
    total_v = 0

    # V1: Level 0 answers all
    total_v += 1
    l0 = all_results[0]
    if l0["quality"] == 1.0:
        print(f"PASS: Level 0 — {l0['total_pass']}/24 questions")
        passed_v += 1
    else:
        print(f"FAIL: Level 0 — {l0['total_pass']}/24 questions")

    # V2: Default (5) answers >= 20/24
    total_v += 1
    l5 = all_results[5]
    if l5["total_pass"] >= 20:
        print(f"PASS: Level 5 (default) — {l5['total_pass']}/24 questions, {l5['savings']:.0f}% saved")
        passed_v += 1
    else:
        print(f"FAIL: Level 5 — {l5['total_pass']}/24 questions")

    # V3: Level 10 answers >= 16/24
    total_v += 1
    l10 = all_results[10]
    if l10["total_pass"] >= 16:
        print(f"PASS: Level 10 (max) — {l10['total_pass']}/24 questions, {l10['savings']:.0f}% saved")
        passed_v += 1
    else:
        print(f"FAIL: Level 10 — {l10['total_pass']}/24 questions")

    # V4: Tier 1 (direct facts) always 100% at levels 0-7
    total_v += 1
    t1_ok = all(all_results[i]["tier_scores"][1] == 7 for i in range(8))
    if t1_ok:
        print("PASS: Tier 1 (direct facts) — 7/7 at levels 0-7")
        passed_v += 1
    else:
        print("FAIL: Tier 1 lost questions before level 8")

    # V5: Tier 3 (causal) still >= 4/6 at level 10
    total_v += 1
    if l10["tier_scores"][3] >= 4:
        print(f"PASS: Tier 3 (causal) at level 10 — {l10['tier_scores'][3]}/6")
        passed_v += 1
    else:
        print(f"FAIL: Tier 3 at level 10 — {l10['tier_scores'][3]}/6")

    # V6: No cliff > 3 questions lost in one step
    total_v += 1
    cliff = False
    for i in range(1, len(all_results)):
        drop = all_results[i - 1]["total_pass"] - all_results[i]["total_pass"]
        if drop > 3:
            print(f"FAIL: Cliff at level {i}: lost {drop} questions")
            cliff = True
    if not cliff:
        print("PASS: No quality cliffs (max 3 questions lost per step)")
        passed_v += 1

    # V7: Savings at default >= 30%
    total_v += 1
    if l5["savings"] >= 30:
        print(f"PASS: Default savings — {l5['savings']:.0f}%")
        passed_v += 1
    else:
        print(f"FAIL: Default savings — {l5['savings']:.0f}%")

    # V8: Tier 4 (synthesis) >= 4/6 at default
    total_v += 1
    if l5["tier_scores"][4] >= 4:
        print(f"PASS: Tier 4 (synthesis) at default — {l5['tier_scores'][4]}/6")
        passed_v += 1
    else:
        print(f"FAIL: Tier 4 at default — {l5['tier_scores'][4]}/6")

    print(f"\n{'=' * 72}")
    print(f"RESULT: {passed_v}/{total_v} validations passed")
    print(f"{'=' * 72}")

    return passed_v == total_v


if __name__ == "__main__":
    success = evaluate_quality()
    sys.exit(0 if success else 1)
