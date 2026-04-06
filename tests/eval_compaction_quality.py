"""Quality eval: verify compacted digests preserve proposer decision quality.

This is NOT a unit test — it's an evaluation script that measures whether
compaction loses information that would change the proposer's decisions.

Tests 6 diagnostic questions across all 11 compaction levels and verifies:
- Quality degrades gracefully (no cliffs)
- Default level (5) answers >= 5/6 questions
- Level 0 answers all questions
- Level 10 still answers >= 3/6 questions
"""

import json
import sys

from kaos.metaharness.compactor import Compactor


# Realistic archive from actual text_classify search
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
            {"problem_id": f"p{i}", "correct": False,
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
            '"""Few-shot classification."""\n'
            'def run(problem):\n'
            '    text = problem["text"]\n'
            '    examples = problem.get("labeled_examples", [])[-8:]\n'
            '    prompt = "Examples:\\n"\n'
            '    for ex in examples:\n'
            '        prompt += f"Text: {ex[\'text\']}\\nCategory: {ex[\'label\']}\\n"\n'
            '    prompt += f"\\nText: {text}\\nCategory:"\n'
            '    try:\n'
            '        return {"prediction": llm(prompt, max_tokens=32).strip()}\n'
            '    except NameError:\n'
            '        return {"prompt": prompt, "context_tokens": len(prompt.split())}\n'
        ),
        "per_problem": [
            {"problem_id": f"p{i}", "correct": False,
             "scores": {"accuracy": 0.0, "context_cost": 70},
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
            '    "technology": ["gpu", "cpu", "cloud", "compiler", "llm", "distributed"],\n'
            '    "science": ["protein", "quantum", "telescope", "climate", "coral"],\n'
            '    "business": ["revenue", "merger", "startup", "funding", "mortgage"],\n'
            '    "sports": ["championship", "quarterback", "marathon", "draft", "olympic"],\n'
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
            '    return {"prediction": best, "context_tokens": len(text.split())}\n'
        ),
        "per_problem": [
            {"problem_id": f"p{i}", "correct": True,
             "scores": {"accuracy": 1.0, "context_cost": 8},
             "output": {"prediction": cat}}
            for i, cat in enumerate(["technology", "science", "business", "sports",
                                      "technology", "science", "business", "sports"])
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
            '    r = httpx.post("http://localhost:8000/v1/chat/completions", json={})\n'
            '    return {"prediction": r.json()["choices"][0]["message"]["content"]}\n'
        ),
        "per_problem": [
            {"problem_id": f"p{i}", "correct": False,
             "scores": {"accuracy": 0.0, "context_cost": 0},
             "error": "ConnectError: All connection attempts failed"} for i in range(8)
        ],
        "error": None,
    },
]

FRONTIER = {
    "objectives": {"accuracy": "maximize", "context_cost": "minimize"},
    "points": [
        {"harness_id": "proposed_keyword_classifier", "iteration": 2,
         "scores": {"accuracy": 1.0, "context_cost": 8.0}},
    ],
}

# 6 diagnostic questions a proposer must answer to make good decisions
DIAGNOSTIC_QUESTIONS = {
    "Q1_best_harness": {
        "fact": "proposed_keyword_classifier has accuracy=1.0",
        "terms": ["1.0000", "keyword"],
    },
    "Q2_winning_approach": {
        "fact": "keyword matching without LLM calls beats LLM-based",
        "terms": ["DOMAIN_KEYWORDS"],
    },
    "Q3_seed_failure_mode": {
        "fact": "seeds returned empty prediction, scoring 0%",
        "terms": ["0.0000", "wrong"],
    },
    "Q4_connection_error": {
        "fact": "failed_llm_caller got connection refused from localhost:8000",
        "terms": ["connect", "connection"],
    },
    "Q5_best_cost": {
        "fact": "keyword classifier achieves 8.0 context cost",
        "terms": ["8.0"],
    },
    "Q6_source_available": {
        "fact": "winning harness source with DOMAIN_KEYWORDS is readable",
        "terms": ["def run"],
    },
}


def evaluate_quality():
    print("=" * 70)
    print("COMPACTION QUALITY EVALUATION")
    print("=" * 70)
    print()

    results = []
    for level in range(0, 11):
        c = Compactor(level=level)
        digest, metrics = c.build_digest(REALISTIC_HARNESSES, FRONTIER)

        answerable = 0
        details = {}
        for qname, qdata in DIAGNOSTIC_QUESTIONS.items():
            found = any(t.lower() in digest.lower() for t in qdata["terms"])
            details[qname] = found
            if found:
                answerable += 1

        q_score = answerable / len(DIAGNOSTIC_QUESTIONS)
        results.append({
            "level": level,
            "compacted": metrics.compacted_chars,
            "savings_pct": metrics.savings_pct,
            "retention": metrics.retention_score,
            "quality": q_score,
            "answerable": answerable,
            "details": details,
        })

        bar = "#" * int(q_score * 20)
        print(
            f"Level {level:2d} | {metrics.compacted_chars:6d} chars "
            f"({metrics.savings_pct:5.1f}% saved) | "
            f"quality={q_score:.2f} [{bar:20s}] "
            f"({answerable}/{len(DIAGNOSTIC_QUESTIONS)} questions)"
        )

    print()

    # Show what's lost at each level
    print("-" * 70)
    print("INFORMATION LOSS DETAIL")
    print("-" * 70)
    for r in results:
        lost = [qn for qn, found in r["details"].items() if not found]
        if lost:
            print(f"Level {r['level']:2d}: LOST {', '.join(lost)}")

    print()
    print("-" * 70)
    print("VALIDATION")
    print("-" * 70)

    passed = 0
    total = 0

    # Test 1: Level 0 answers all questions
    total += 1
    l0 = results[0]
    if l0["quality"] == 1.0:
        print("PASS: Level 0 answers all 6/6 questions")
        passed += 1
    else:
        print(f"FAIL: Level 0 only answers {l0['answerable']}/6")

    # Test 2: Default level (5) answers >= 5/6
    total += 1
    l5 = results[5]
    if l5["quality"] >= 5 / 6:
        print(f"PASS: Level 5 (default) answers {l5['answerable']}/6 questions")
        passed += 1
    else:
        print(f"FAIL: Level 5 only answers {l5['answerable']}/6")

    # Test 3: Level 10 still answers >= 3/6
    total += 1
    l10 = results[10]
    if l10["quality"] >= 3 / 6:
        print(f"PASS: Level 10 (max) answers {l10['answerable']}/6 questions")
        passed += 1
    else:
        print(f"FAIL: Level 10 only answers {l10['answerable']}/6")

    # Test 4: No quality cliff (>2 questions lost in one step)
    total += 1
    cliff = False
    for i in range(1, len(results)):
        drop = results[i - 1]["answerable"] - results[i]["answerable"]
        if drop > 2:
            print(f"FAIL: Quality cliff at level {i}: lost {drop} questions in one step")
            cliff = True
    if not cliff:
        print("PASS: No quality cliffs (max 2 questions lost per level)")
        passed += 1

    # Test 5: Savings at default level >= 30%
    total += 1
    if l5["savings_pct"] >= 30:
        print(f"PASS: Level 5 saves {l5['savings_pct']:.0f}% (>= 30%)")
        passed += 1
    else:
        print(f"FAIL: Level 5 only saves {l5['savings_pct']:.0f}%")

    print(f"\n{'=' * 70}")
    print(f"RESULT: {passed}/{total} validations passed")
    print(f"{'=' * 70}")

    return passed == total


if __name__ == "__main__":
    success = evaluate_quality()
    sys.exit(0 if success else 1)
