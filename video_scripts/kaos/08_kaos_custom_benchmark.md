# Tutorial 08 — Building a Custom Benchmark for Meta-Harness Search
**Duration:** 5 minutes  
**Level:** Advanced  
**Goal:** Implement a custom KAOS benchmark class so you can run meta-harness search on your own tasks — classification, generation, retrieval, or anything else.

---

## SCENE 1 — Hook [0:00–0:20]

**[VISUAL: List of built-in benchmarks: text_classify, arc_agi3. Then a "+" adding "my_task" — custom benchmark plugs in.]**

> "KAOS ships with built-in benchmarks. But your real task is probably something specific to your domain — a ranking problem, a custom extraction task, a domain-specific evaluation. The benchmark interface is simple: implement three methods and meta-harness search works on your problem out of the box."

---

## SCENE 2 — The Benchmark Interface [0:20–1:15]

**[VISUAL: Base class `benchmarks/base.py`]**

> "Every benchmark inherits from `Benchmark` and implements three things: the objectives it optimizes for, a problem set to evaluate against, and a scorer that grades harness outputs."

```python
from kaos.metaharness.benchmarks.base import Benchmark

class Benchmark:
    name: str                    # unique identifier
    objectives: list[str]        # e.g. ["+accuracy", "-context_cost"]

    def get_seed_harnesses(self) -> list[str]:
        """Return starting harness source code — at least one."""
        ...

    def get_search_set(self) -> list[dict]:
        """Return the list of problems to evaluate against."""
        ...

    def score(
        self, problem: dict, harness_output: dict
    ) -> dict[str, float]:
        """Score one harness output — return metric dict."""
        ...
```

> "That's the full interface. Three methods. The framework handles everything else — parallel evaluation, archive management, Pareto frontier, proposer prompting."

---

## SCENE 3 — A Real Example: Intent Classification [1:15–2:30]

**[VISUAL: Custom benchmark class, built step by step]**

> "Let's build a benchmark for classifying customer support ticket intent — bug report, feature request, or billing question."

```python
# kaos/metaharness/benchmarks/intent_classify.py
from kaos.metaharness.benchmarks.base import Benchmark

INTENTS = ["bug_report", "feature_request", "billing"]

PROBLEMS = [
    {"text": "The app crashes when I upload a PDF",  "label": "bug_report"},
    {"text": "Can you add dark mode to the app?",    "label": "feature_request"},
    {"text": "I was charged twice for my subscription", "label": "billing"},
    # ... more examples
]

SEED_HARNESS = '''
def run(problem: dict) -> dict:
    prompt = (
        "Classify this support ticket as one of: "
        "bug_report, feature_request, billing.\\n\\n"
        f"Ticket: {problem['text']}\\n\\n"
        "Reply with only the category name."
    )
    response = llm(prompt, max_tokens=20)
    prediction = response.strip().lower()
    
    return {
        "prediction":     prediction,
        "context_tokens": len(prompt.split()),
    }
'''


class IntentClassifyBenchmark(Benchmark):
    name = "intent_classify"
    objectives = ["+accuracy", "-context_cost"]

    def get_seed_harnesses(self) -> list[str]:
        return [SEED_HARNESS]

    def get_search_set(self) -> list[dict]:
        return PROBLEMS

    def score(self, problem: dict, harness_output: dict) -> dict[str, float]:
        prediction = harness_output.get("prediction", "").lower()
        correct    = problem["label"]
        tokens     = harness_output.get("context_tokens", 0)

        return {
            "accuracy":     1.0 if prediction == correct else 0.0,
            "context_cost": tokens / 1000,  # normalized cost
        }
```

---

## SCENE 4 — Registering and Running It [2:30–3:15]

**[VISUAL: Registration and launch]**

> "Register the benchmark so KAOS can find it by name."

```python
# kaos/metaharness/benchmarks/__init__.py  — add one line
from kaos.metaharness.benchmarks.intent_classify import IntentClassifyBenchmark

_REGISTRY = {
    "text_classify":   TextClassifyBenchmark,
    "arc_agi3":        ArcAgi3Benchmark,
    "intent_classify": IntentClassifyBenchmark,  # ← add this
}

def get_benchmark(name: str) -> Benchmark:
    return _REGISTRY[name]()
```

> "Now run meta-harness search on it — same command, just a different benchmark name."

```bash
kaos mh search --benchmark intent_classify --iterations 8
```

```python
from kaos.metaharness.benchmarks.intent_classify import IntentClassifyBenchmark

config = SearchConfig(
    benchmark    = "intent_classify",
    max_iterations = 8,
    objectives   = ["+accuracy", "-context_cost"],
)
bench  = IntentClassifyBenchmark()
search = MetaHarnessSearch(db, router, bench, config)
result = asyncio.run(search.run())
```

---

## SCENE 5 — A Subset for Fast Iteration [3:15–3:50]

**[VISUAL: eval_subset_size config and get_subset method]**

> "For large problem sets, use `eval_subset_size` to evaluate against a random sample during search — then run the full set on the final frontier harnesses only."

```python
config = SearchConfig(
    benchmark       = "intent_classify",
    max_iterations  = 15,
    eval_subset_size = 50,   # sample 50 problems per iteration (fast)
)
```

> "The `Benchmark` base class provides a default `get_subset` implementation — random sample, reproducible with a fixed seed. Override it if you need stratified sampling or domain-specific selection."

---

## SCENE 6 — Multi-Objective Scoring [3:50–4:30]

**[VISUAL: Pareto frontier with two dimensions plotted — accuracy vs cost]**

> "The Pareto frontier tracks multiple objectives simultaneously. The `objectives` list uses `+` for maximize and `-` for minimize."

```python
# Optimize three dimensions at once
objectives = [
    "+accuracy",      # maximize correct predictions
    "-context_cost",  # minimize tokens used
    "-latency_ms",    # minimize response time
]
```

> "Your `score()` method just needs to return all three keys. KAOS will find harnesses that represent the best tradeoffs — a harness that's slightly less accurate but 5x cheaper appears on the frontier alongside the most accurate one."

```python
def score(self, problem, harness_output):
    return {
        "accuracy":     1.0 if correct else 0.0,
        "context_cost": tokens / 1000,
        "latency_ms":   harness_output.get("latency_ms", 0),
    }
```

---

## SCENE 7 — Summary [4:30–5:00]

**[VISUAL: Interface summary — three methods, the whole loop behind it]**

> "A custom benchmark is three methods: get_seed_harnesses, get_search_set, and score. Register it by name. Run it with the standard CLI or Python API. The entire meta-harness search loop — proposer, evaluator, Pareto frontier, CORAL skills, pivot prompts — works unchanged on your problem.

That's the complete KAOS tutorial series. You now have everything you need: isolated agents, checkpoints, parallel execution, the MCP server, the audit trail, meta-harness search, CORAL co-evolution, and custom benchmarks. Build something great."

---

## AI VIDEO GENERATION NOTES
- **Voice tone:** Empowering, closing the arc of the series. The final line should feel like a send-off.
- **Code build-up (Scene 3):** Show the class being built method by method — not all at once. `__init__` first, then `get_seed_harnesses`, then `get_search_set`, then `score`.
- **Pareto plot (Scene 6):** Show a 2D scatter plot with accuracy on Y axis, cost on X axis, Pareto frontier line connecting the optimal points.
- **End card:** Show all 8 tutorial titles with checkmarks. Link to KAOS GitHub and docs.
