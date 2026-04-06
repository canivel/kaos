"""Multi-domain compaction quality evaluation.

Tests compaction quality across 5 realistic domains:
- Text Classification
- Code Generation
- Research / RAG
- Tool Calling / Agentic
- ML Training / Optimization

Each domain has its own archive data and diagnostic questions covering
direct facts, comparison, causal reasoning, and synthesis.
"""

import json
import sys

from kaos.metaharness.compactor import Compactor


# ═══════════════════════════════════════════════════════════════════
# DOMAIN 1: Text Classification
# ═══════════════════════════════════════════════════════════════════

CLASSIFICATION_HARNESSES = [
    {
        "harness_id": "cls_seed_zero_shot", "iteration": 0,
        "scores": {"accuracy": 0.0, "context_cost": 22.75},
        "source": '"""Zero-shot text classification."""\ndef run(problem):\n    text = problem["text"]\n    labels = problem.get("labels", [])\n    prompt = f"Classify into: {\", \".join(labels)}\\nText: {text}\\nCategory:"\n    try:\n        return {"prediction": llm(prompt, max_tokens=32).strip()}\n    except NameError:\n        return {"prompt": prompt, "context_tokens": len(prompt.split())}\n',
        "per_problem": [{"problem_id": f"cls_{i}", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 22}, "output": {"prediction": ""}} for i in range(8)],
        "error": None,
    },
    {
        "harness_id": "cls_keyword_classifier", "iteration": 2,
        "scores": {"accuracy": 1.0, "context_cost": 8.0},
        "source": '"""Domain keyword classifier."""\nDOMAIN_KEYWORDS = {\n    "technology": ["gpu", "cpu", "cloud", "compiler", "llm"],\n    "science": ["protein", "quantum", "telescope", "climate"],\n    "business": ["revenue", "merger", "startup", "funding"],\n    "sports": ["championship", "quarterback", "marathon"],\n}\ndef run(problem):\n    text = problem["text"].lower()\n    labels = problem.get("labels", [])\n    scores = {l: sum(1 for kw in DOMAIN_KEYWORDS.get(l, []) if kw in text) for l in labels}\n    return {"prediction": max(scores, key=scores.get), "context_tokens": len(text.split()), "method": "keyword_match"}\n',
        "per_problem": [{"problem_id": f"cls_{i}", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 8}, "output": {"prediction": cat, "method": "keyword_match"}} for i, cat in enumerate(["technology", "science", "business", "sports"] * 2)],
        "error": None,
    },
    {
        "harness_id": "cls_failed_api", "iteration": 1, "scores": {},
        "source": 'def run(p):\n    import httpx\n    r = httpx.post("http://localhost:8000/v1/chat/completions", json={})\n    return {"prediction": r.json()["choices"][0]["message"]["content"]}\n',
        "per_problem": [{"problem_id": f"cls_{i}", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 0}, "error": "ConnectError: All connection attempts failed"} for i in range(8)],
        "error": None,
    },
]
CLASSIFICATION_FRONTIER = {"objectives": {"accuracy": "maximize", "context_cost": "minimize"}, "points": [{"harness_id": "cls_keyword_classifier", "iteration": 2, "scores": {"accuracy": 1.0, "context_cost": 8.0}}]}
CLASSIFICATION_QUESTIONS = {
    "cls_best_score": {"terms": ["1.0000"]}, "cls_winning_approach": {"terms": ["DOMAIN_KEYWORDS"]},
    "cls_why_seed_failed": {"terms": ["wrong", "0.0000"]}, "cls_source_readable": {"terms": ["def run"]},
    "cls_method_visible": {"terms": ["keyword_match"]}, "cls_keyword_list": {"terms": ["gpu", "protein", "revenue"], "logic": "any_two"},
    "cls_cost_comparison": {"terms": ["8.0", "22"]}, "cls_frontier_present": {"terms": ["frontier"]},
}

# ═══════════════════════════════════════════════════════════════════
# DOMAIN 2: Code Generation
# ═══════════════════════════════════════════════════════════════════

CODE_HARNESSES = [
    {
        "harness_id": "code_direct_prompt", "iteration": 0,
        "scores": {"pass_rate": 0.3, "context_cost": 150},
        "source": '"""Direct code generation."""\ndef run(problem):\n    task = problem["task_description"]\n    language = problem.get("language", "python")\n    prompt = f"Write {language} code that:\\n{task}\\n\\nCode:"\n    response = llm(prompt, max_tokens=512)\n    return {"prediction": response, "context_tokens": len(prompt.split())}\n',
        "per_problem": [
            {"problem_id": "fizzbuzz", "correct": True, "scores": {"pass_rate": 1.0, "context_cost": 80}, "output": {"prediction": "def fizzbuzz(n):..."}},
            {"problem_id": "binary_search", "correct": True, "scores": {"pass_rate": 1.0, "context_cost": 120}, "output": {"prediction": "def binary_search(arr, target):..."}},
            {"problem_id": "async_retry", "correct": False, "scores": {"pass_rate": 0.0, "context_cost": 200}, "output": {"prediction": "import asyncio..."}, "error": "SyntaxError in generated code"},
            {"problem_id": "parser_combinator", "correct": False, "scores": {"pass_rate": 0.0, "context_cost": 250}, "output": {"prediction": "class Parser:..."}, "error": "TestFailed: 0/12 tests passed"},
            {"problem_id": "graph_shortest", "correct": False, "scores": {"pass_rate": 0.0, "context_cost": 180}, "output": {"prediction": "def dijkstra(graph):..."}, "error": "TestFailed: incomplete implementation"},
        ],
        "error": None,
    },
    {
        "harness_id": "code_env_snapshot_first", "iteration": 3,
        "scores": {"pass_rate": 0.8, "context_cost": 200},
        "source": '"""Environment-aware code generation."""\nimport os\ndef _gather_env(problem):\n    """Gather environment context: language version, available imports."""\n    lang = problem.get("language", "python")\n    deps = problem.get("available_deps", [])\n    test_framework = problem.get("test_framework", "pytest")\n    return f"Language: {lang}\\nDeps: {deps}\\nTests: {test_framework}"\n\ndef run(problem):\n    task = problem["task_description"]\n    env = _gather_env(problem)\n    prompt = (f"Environment:\\n{env}\\n\\nWrite complete, tested code that:\\n{task}\\n\\nInclude error handling and type hints.")\n    response = llm(prompt, max_tokens=1024)\n    return {"prediction": response, "context_tokens": len(prompt.split()), "method": "env_snapshot"}\n',
        "per_problem": [
            {"problem_id": "fizzbuzz", "correct": True, "scores": {"pass_rate": 1.0, "context_cost": 100}, "output": {"prediction": "def fizzbuzz(n)...", "method": "env_snapshot"}},
            {"problem_id": "binary_search", "correct": True, "scores": {"pass_rate": 1.0, "context_cost": 140}, "output": {"prediction": "def binary_search(arr, target)...", "method": "env_snapshot"}},
            {"problem_id": "async_retry", "correct": True, "scores": {"pass_rate": 1.0, "context_cost": 220}, "output": {"prediction": "async def retry_with_backoff(fn, max_retries=3)...", "method": "env_snapshot"}},
            {"problem_id": "parser_combinator", "correct": True, "scores": {"pass_rate": 1.0, "context_cost": 300}, "output": {"prediction": "class Parser: ...", "method": "env_snapshot"}},
            {"problem_id": "graph_shortest", "correct": False, "scores": {"pass_rate": 0.0, "context_cost": 250}, "output": {"prediction": "def dijkstra(graph)..."}, "error": "TestFailed: edge case with negative weights"},
        ],
        "error": None,
    },
]
CODE_FRONTIER = {"objectives": {"pass_rate": "maximize", "context_cost": "minimize"}, "points": [{"harness_id": "code_env_snapshot_first", "iteration": 3, "scores": {"pass_rate": 0.8, "context_cost": 200}}, {"harness_id": "code_direct_prompt", "iteration": 0, "scores": {"pass_rate": 0.3, "context_cost": 150}}]}
CODE_QUESTIONS = {
    "code_best_pass_rate": {"terms": ["0.8"]}, "code_env_technique": {"terms": ["_gather_env"]},
    "code_async_retry_fixed": {"terms": ["async", "retry"], "logic": "any_two"}, "code_parser_failure": {"terms": ["parser", "TestFailed"], "logic": "any_two"},
    "code_graph_edge_case": {"terms": ["negative weights"]}, "code_env_vs_direct": {"terms": ["0.8", "0.3"]},
    "code_type_hints": {"terms": ["type hints"]}, "code_test_framework": {"terms": ["pytest"]},
    "code_cost_tradeoff": {"terms": ["pass_rate", "context_cost"]}, "code_source_readable": {"terms": ["def run"]},
}

# ═══════════════════════════════════════════════════════════════════
# DOMAIN 3: Research / RAG
# ═══════════════════════════════════════════════════════════════════

RESEARCH_HARNESSES = [
    {
        "harness_id": "rag_no_retrieval", "iteration": 0,
        "scores": {"accuracy": 0.2, "context_cost": 50},
        "source": '"""No retrieval -- direct question answering."""\ndef run(problem):\n    question = problem["question"]\n    prompt = f"Answer this math problem:\\n{question}\\nAnswer:"\n    response = llm(prompt, max_tokens=64)\n    import re\n    numbers = re.findall(r"-?\\d+\\.?\\d*", response)\n    return {"prediction": numbers[0] if numbers else response.strip(), "context_tokens": len(prompt.split())}\n',
        "per_problem": [
            {"problem_id": "math_1", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 30}, "output": {"prediction": "56"}},
            {"problem_id": "math_2", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 45}, "output": {"prediction": "9"}, "error": "expected 12"},
            {"problem_id": "math_3", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 60}, "output": {"prediction": "50"}, "error": "expected 78.54"},
            {"problem_id": "math_4", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 55}, "output": {"prediction": "10"}, "error": "expected 120"},
            {"problem_id": "math_5", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 40}, "output": {"prediction": "24"}, "error": "expected 12, GCD confused with LCM"},
        ],
        "error": None,
    },
    {
        "harness_id": "rag_domain_retrieval", "iteration": 2,
        "scores": {"accuracy": 0.8, "context_cost": 120},
        "source": '"""Domain-aware retrieval with BM25 scoring."""\nMATH_DOMAINS = {\n    "geometry": ["area", "circle", "triangle", "perimeter", "radius"],\n    "combinatorics": ["choose", "permutation", "combination", "ways"],\n    "number_theory": ["prime", "gcd", "divisor", "modulo", "factor"],\n    "algebra": ["equation", "solve", "polynomial", "variable"],\n}\n\ndef classify_domain(q):\n    q_lower = q.lower()\n    scores = {d: sum(1 for kw in kws if kw in q_lower) for d, kws in MATH_DOMAINS.items()}\n    return max(scores, key=scores.get)\n\ndef run(problem):\n    question = problem["question"]\n    corpus = problem.get("corpus", [])\n    domain = classify_domain(question)\n    domain_corpus = [d for d in corpus if classify_domain(d["question"]) == domain]\n    if len(domain_corpus) < 3: domain_corpus = corpus\n    query_words = set(question.lower().split())\n    scored = [(len(query_words & set(d["question"].lower().split())), d) for d in domain_corpus]\n    scored.sort(reverse=True)\n    examples = "\\n".join(f"Q: {d[1][\'question\']}\\nA: {d[1][\'answer\']}" for d in scored[:3])\n    prompt = f"Domain: {domain}\\n{examples}\\n\\nQ: {question}\\nA:"\n    response = llm(prompt, max_tokens=64)\n    import re\n    nums = re.findall(r"-?\\d+\\.?\\d*", response)\n    return {"prediction": nums[0] if nums else response, "context_tokens": len(prompt.split()), "method": "domain_retrieval", "domain": domain}\n',
        "per_problem": [
            {"problem_id": "math_1", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 90}, "output": {"prediction": "56", "domain": "algebra", "method": "domain_retrieval"}},
            {"problem_id": "math_2", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 110}, "output": {"prediction": "12", "domain": "algebra", "method": "domain_retrieval"}},
            {"problem_id": "math_3", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 130}, "output": {"prediction": "78.54", "domain": "geometry", "method": "domain_retrieval"}},
            {"problem_id": "math_4", "correct": True, "scores": {"accuracy": 1.0, "context_cost": 140}, "output": {"prediction": "120", "domain": "combinatorics", "method": "domain_retrieval"}},
            {"problem_id": "math_5", "correct": False, "scores": {"accuracy": 0.0, "context_cost": 100}, "output": {"prediction": "6", "domain": "number_theory", "method": "domain_retrieval"}, "error": "expected 12, domain routing correct but retrieval miss"},
        ],
        "error": None,
    },
]
RESEARCH_FRONTIER = {"objectives": {"accuracy": "maximize", "context_cost": "minimize"}, "points": [{"harness_id": "rag_domain_retrieval", "iteration": 2, "scores": {"accuracy": 0.8, "context_cost": 120}}, {"harness_id": "rag_no_retrieval", "iteration": 0, "scores": {"accuracy": 0.2, "context_cost": 50}}]}
RESEARCH_QUESTIONS = {
    "rag_best_accuracy": {"terms": ["0.8"]}, "rag_domain_routing": {"terms": ["MATH_DOMAINS", "classify_domain"], "logic": "any_two"},
    "rag_bm25_scoring": {"terms": ["BM25", "query_words"], "logic": "any_two"}, "rag_retrieval_miss": {"terms": ["retrieval miss"]},
    "rag_domain_categories": {"terms": ["geometry", "algebra", "combinatorics"], "logic": "any_two"},
    "rag_baseline": {"terms": ["0.2"]}, "rag_cost_tradeoff": {"terms": ["50", "120"]},
    "rag_method_field": {"terms": ["domain_retrieval"]}, "rag_source_readable": {"terms": ["def run"]},
}

# ═══════════════════════════════════════════════════════════════════
# DOMAIN 4: Tool Calling / Agentic
# ═══════════════════════════════════════════════════════════════════

TOOL_HARNESSES = [
    {
        "harness_id": "tool_single_step", "iteration": 0,
        "scores": {"success_rate": 0.4, "avg_steps": 1.0},
        "source": '"""Single-step tool calling."""\ndef run(problem):\n    task = problem["task"]\n    tools = problem.get("available_tools", [])\n    tool_desc = "\\n".join(f"- {t[\'name\']}: {t[\'description\']}" for t in tools)\n    prompt = f"Available tools:\\n{tool_desc}\\n\\nTask: {task}\\nCall exactly one tool. Format: TOOL(args)"\n    response = llm(prompt, max_tokens=128)\n    return {"prediction": response, "context_tokens": len(prompt.split()), "method": "single_step"}\n',
        "per_problem": [
            {"problem_id": "search_weather", "correct": True, "scores": {"success_rate": 1.0, "avg_steps": 1}, "output": {"prediction": "SEARCH('weather')", "method": "single_step"}},
            {"problem_id": "multi_step_research", "correct": False, "scores": {"success_rate": 0.0, "avg_steps": 1}, "output": {"prediction": "SEARCH('topic')"}, "error": "required 3 tool calls, only made 1"},
            {"problem_id": "file_edit_chain", "correct": False, "scores": {"success_rate": 0.0, "avg_steps": 1}, "output": {"prediction": "READ('file.py')"}, "error": "required READ then EDIT, only made READ"},
            {"problem_id": "calc_then_store", "correct": True, "scores": {"success_rate": 1.0, "avg_steps": 1}, "output": {"prediction": "CALC('2+2')", "method": "single_step"}},
            {"problem_id": "api_chain", "correct": False, "scores": {"success_rate": 0.0, "avg_steps": 1}, "output": {"prediction": "API_CALL('GET /users')"}, "error": "needed to chain auth then list then filter"},
        ],
        "error": None,
    },
    {
        "harness_id": "tool_plan_then_act", "iteration": 2,
        "scores": {"success_rate": 0.8, "avg_steps": 3.2},
        "source": '"""Plan-then-act: decompose into steps before calling tools."""\ndef run(problem):\n    task = problem["task"]\n    tools = problem.get("available_tools", [])\n    tool_desc = "\\n".join(f"- {t[\'name\']}: {t[\'description\']}" for t in tools)\n    plan_prompt = f"Tools:\\n{tool_desc}\\n\\nTask: {task}\\n\\nList the steps needed (1 tool per step):"\n    plan = llm(plan_prompt, max_tokens=256)\n    exec_prompt = f"Plan:\\n{plan}\\n\\nExecute step 1. Format: TOOL(args)"\n    response = llm(exec_prompt, max_tokens=128)\n    return {"prediction": response, "context_tokens": len(plan_prompt.split()) + len(exec_prompt.split()), "method": "plan_then_act", "plan_steps": plan.count("\\n")}\n',
        "per_problem": [
            {"problem_id": "search_weather", "correct": True, "scores": {"success_rate": 1.0, "avg_steps": 2}, "output": {"prediction": "SEARCH('weather')", "method": "plan_then_act"}},
            {"problem_id": "multi_step_research", "correct": True, "scores": {"success_rate": 1.0, "avg_steps": 4}, "output": {"prediction": "SEARCH->READ->SUMMARIZE", "method": "plan_then_act"}},
            {"problem_id": "file_edit_chain", "correct": True, "scores": {"success_rate": 1.0, "avg_steps": 3}, "output": {"prediction": "READ->EDIT->VERIFY", "method": "plan_then_act"}},
            {"problem_id": "calc_then_store", "correct": True, "scores": {"success_rate": 1.0, "avg_steps": 2}, "output": {"prediction": "CALC->STORE", "method": "plan_then_act"}},
            {"problem_id": "api_chain", "correct": False, "scores": {"success_rate": 0.0, "avg_steps": 5}, "output": {"prediction": "AUTH->LIST->???"}, "error": "plan correct but execution hallucinated step 3"},
        ],
        "error": None,
    },
]
TOOL_FRONTIER = {"objectives": {"success_rate": "maximize", "avg_steps": "minimize"}, "points": [{"harness_id": "tool_plan_then_act", "iteration": 2, "scores": {"success_rate": 0.8, "avg_steps": 3.2}}, {"harness_id": "tool_single_step", "iteration": 0, "scores": {"success_rate": 0.4, "avg_steps": 1.0}}]}
TOOL_QUESTIONS = {
    "tool_best_success": {"terms": ["0.8"]}, "tool_plan_approach": {"terms": ["plan_then_act"]},
    "tool_multi_step_failure": {"terms": ["required 3 tool calls"]}, "tool_api_chain_issue": {"terms": ["hallucinated"]},
    "tool_plan_vs_single": {"terms": ["0.8", "0.4"]}, "tool_step_count": {"terms": ["avg_steps"]},
    "tool_decomposition": {"terms": ["step 1", "plan"], "logic": "any_two"}, "tool_source_readable": {"terms": ["def run"]},
}

# ═══════════════════════════════════════════════════════════════════
# DOMAIN 5: ML Training / Optimization
# ═══════════════════════════════════════════════════════════════════

ML_HARNESSES = [
    {
        "harness_id": "ml_default_config", "iteration": 0,
        "scores": {"val_accuracy": 0.72, "training_cost": 100},
        "source": '"""Default ML config."""\ndef run(problem):\n    dataset = problem["dataset"]\n    model_type = problem.get("model_type", "transformer")\n    prompt = (f"Dataset: {dataset}\\nModel: {model_type}\\n"\n              f"Suggest hyperparameters for training.\\n"\n              f"Output JSON: {{lr, batch_size, epochs, optimizer}}")\n    response = llm(prompt, max_tokens=256)\n    return {"prediction": response, "context_tokens": len(prompt.split()), "method": "default_config"}\n',
        "per_problem": [
            {"problem_id": "cifar10", "correct": True, "scores": {"val_accuracy": 0.85, "training_cost": 80}, "output": {"prediction": '{"lr": 0.001, "batch_size": 64}'}},
            {"problem_id": "imdb_sentiment", "correct": True, "scores": {"val_accuracy": 0.88, "training_cost": 60}, "output": {"prediction": '{"lr": 2e-5, "batch_size": 16}'}},
            {"problem_id": "protein_folding", "correct": False, "scores": {"val_accuracy": 0.45, "training_cost": 200}, "output": {"prediction": '{"lr": 0.01}'}, "error": "lr too high, diverged after epoch 5"},
            {"problem_id": "timeseries", "correct": False, "scores": {"val_accuracy": 0.60, "training_cost": 90}, "output": {"prediction": '{"batch_size": 128}'}, "error": "batch_size too large for small dataset"},
        ],
        "error": None,
    },
    {
        "harness_id": "ml_dataset_aware", "iteration": 3,
        "scores": {"val_accuracy": 0.91, "training_cost": 150},
        "source": '"""Dataset-aware config -- analyzes data characteristics first."""\ndef _analyze_dataset(problem):\n    n_samples = problem.get("n_samples", 10000)\n    n_features = problem.get("n_features", 100)\n    task_type = problem.get("task_type", "classification")\n    return f"Samples: {n_samples}, Features: {n_features}, Task: {task_type}"\n\ndef run(problem):\n    analysis = _analyze_dataset(problem)\n    model_type = problem.get("model_type", "transformer")\n    prompt = (f"Dataset analysis:\\n{analysis}\\nModel: {model_type}\\n\\n"\n              f"Based on the dataset size and task, suggest optimal hyperparameters.\\n"\n              f"For small datasets (<1000), use lower lr and more regularization.\\n"\n              f"For large datasets (>100k), use larger batch sizes.\\n"\n              f"Output JSON: {{lr, batch_size, epochs, optimizer, weight_decay}}")\n    response = llm(prompt, max_tokens=256)\n    return {"prediction": response, "context_tokens": len(prompt.split()), "method": "dataset_aware", "analysis": analysis}\n',
        "per_problem": [
            {"problem_id": "cifar10", "correct": True, "scores": {"val_accuracy": 0.92, "training_cost": 120}, "output": {"prediction": '{"lr": 0.0003}', "method": "dataset_aware"}},
            {"problem_id": "imdb_sentiment", "correct": True, "scores": {"val_accuracy": 0.91, "training_cost": 80}, "output": {"prediction": '{"lr": 2e-5, "weight_decay": 0.01}', "method": "dataset_aware"}},
            {"problem_id": "protein_folding", "correct": True, "scores": {"val_accuracy": 0.89, "training_cost": 250}, "output": {"prediction": '{"lr": 0.0001, "weight_decay": 0.1}', "method": "dataset_aware"}},
            {"problem_id": "timeseries", "correct": False, "scores": {"val_accuracy": 0.82, "training_cost": 100}, "output": {"prediction": '{"lr": 0.0005}'}, "error": "needed specialized architecture hint for temporal data"},
        ],
        "error": None,
    },
]
ML_FRONTIER = {"objectives": {"val_accuracy": "maximize", "training_cost": "minimize"}, "points": [{"harness_id": "ml_dataset_aware", "iteration": 3, "scores": {"val_accuracy": 0.91, "training_cost": 150}}, {"harness_id": "ml_default_config", "iteration": 0, "scores": {"val_accuracy": 0.72, "training_cost": 100}}]}
ML_QUESTIONS = {
    "ml_best_val_accuracy": {"terms": ["0.91"]}, "ml_dataset_analysis": {"terms": ["_analyze_dataset"]},
    "ml_lr_divergence": {"terms": ["lr too high", "diverged"], "logic": "any_two"}, "ml_batch_size_issue": {"terms": ["batch_size too large"]},
    "ml_weight_decay": {"terms": ["weight_decay"]}, "ml_small_dataset_rule": {"terms": ["small datasets"]},
    "ml_default_vs_aware": {"terms": ["0.91", "0.72"]}, "ml_source_readable": {"terms": ["def run"]},
}


# ═══════════════════════════════════════════════════════════════════
# Evaluation
# ═══════════════════════════════════════════════════════════════════

DOMAINS = {
    "Classification": (CLASSIFICATION_HARNESSES, CLASSIFICATION_FRONTIER, CLASSIFICATION_QUESTIONS),
    "Code Generation": (CODE_HARNESSES, CODE_FRONTIER, CODE_QUESTIONS),
    "Research / RAG": (RESEARCH_HARNESSES, RESEARCH_FRONTIER, RESEARCH_QUESTIONS),
    "Tool Calling": (TOOL_HARNESSES, TOOL_FRONTIER, TOOL_QUESTIONS),
    "ML Training": (ML_HARNESSES, ML_FRONTIER, ML_QUESTIONS),
}


def check_question(digest_lower, qdata):
    terms = qdata["terms"]
    logic = qdata.get("logic", "all")
    if logic == "all":
        return all(t.lower() in digest_lower for t in terms)
    elif logic == "any_two":
        return sum(1 for t in terms if t.lower() in digest_lower) >= 2
    return False


def evaluate_quality():
    print("=" * 78)
    print("MULTI-DOMAIN COMPACTION QUALITY EVALUATION")
    print("=" * 78)
    print()

    domain_results = {}
    for domain_name, (harnesses, frontier, questions) in DOMAINS.items():
        domain_results[domain_name] = {}
        for level in range(0, 11):
            c = Compactor(level=level)
            digest, metrics = c.build_digest(harnesses, frontier)
            digest_lower = digest.lower()
            passed = sum(1 for q in questions.values() if check_question(digest_lower, q))
            domain_results[domain_name][level] = {
                "passed": passed, "total": len(questions),
                "pct": passed / len(questions) * 100,
                "savings": metrics.savings_pct,
            }

    for domain_name in DOMAINS:
        print(f"--- {domain_name} ---")
        for level in [0, 3, 5, 7, 10]:
            r = domain_results[domain_name][level]
            bar = "#" * int(r["pct"] / 5)
            print(f"  Level {level:2d} | {r['savings']:4.0f}% saved | {r['pct']:5.1f}% quality [{bar:20s}]")
        print()

    print("=" * 78)
    print("AGGREGATE")
    print("=" * 78)
    for level in range(0, 11):
        total_p = sum(domain_results[d][level]["passed"] for d in DOMAINS)
        total_q = sum(domain_results[d][level]["total"] for d in DOMAINS)
        avg_sav = sum(domain_results[d][level]["savings"] for d in DOMAINS) / len(DOMAINS)
        pct = total_p / total_q * 100
        bar = "#" * int(pct / 5)
        print(f"Level {level:2d} | {avg_sav:4.0f}% saved | {pct:5.1f}% quality [{bar:20s}]")

    print()
    print("-" * 78)
    print("VALIDATION")
    print("-" * 78)
    ok = 0
    total = 0

    total += 1
    if all(domain_results[d][0]["pct"] == 100 for d in DOMAINS):
        print("PASS: All domains 100% at level 0"); ok += 1
    else:
        print("FAIL: Some domains below 100% at level 0")

    total += 1
    if all(domain_results[d][5]["pct"] >= 90 for d in DOMAINS):
        print("PASS: All domains >= 90% at default level"); ok += 1
    else:
        for d in DOMAINS:
            if domain_results[d][5]["pct"] < 90: print(f"  FAIL: {d} = {domain_results[d][5]['pct']:.0f}%")

    total += 1
    if all(domain_results[d][10]["pct"] >= 70 for d in DOMAINS):
        print("PASS: All domains >= 70% at max level"); ok += 1
    else:
        for d in DOMAINS:
            if domain_results[d][10]["pct"] < 70: print(f"  FAIL: {d} = {domain_results[d][10]['pct']:.0f}%")

    total += 1
    cliff = False
    for d in DOMAINS:
        for l in range(1, 11):
            drop = domain_results[d][l-1]["pct"] - domain_results[d][l]["pct"]
            if drop > 30: print(f"  FAIL: {d} cliff at level {l}"); cliff = True
    if not cliff: print("PASS: No quality cliffs"); ok += 1

    total += 1
    avg5 = sum(domain_results[d][5]["savings"] for d in DOMAINS) / len(DOMAINS)
    if avg5 >= 30: print(f"PASS: Average savings at default = {avg5:.0f}%"); ok += 1
    else: print(f"FAIL: Average savings at default = {avg5:.0f}%")

    print(f"\n{'=' * 78}")
    print(f"RESULT: {ok}/{total} validations passed")
    print(f"{'=' * 78}")
    return ok == total


if __name__ == "__main__":
    success = evaluate_quality()
    sys.exit(0 if success else 1)
