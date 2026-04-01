# Meta-Harness: Automated Harness Optimization on KAOS

> Your LLM is only as good as the code wrapping it. Meta-Harness automatically searches for the best harness — the prompt template, retrieval strategy, and memory management — by letting an AI proposer learn from full execution traces.

Based on [Meta-Harness (arXiv:2603.28052)](https://yoonholee.com/meta-harness/) by Lee, Nair, Zhang, Lee, Khattab, and Finn (Stanford/KRAFTON/MIT). Original code: [stanford-iris-lab/meta-harness-tbench2-artifact](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact).

---

## What Problem Does This Solve?

You have an LLM doing a task — classifying tickets, solving math problems, writing code. The model is fixed. But the **harness** — the code that decides what to put in the prompt, which examples to retrieve, what context to include — makes a **6x performance difference** on the same model.

Currently, you optimize harnesses by hand: try a prompt, check results, adjust, repeat. Meta-Harness automates this entire loop.

## How It Works — Step by Step

Here's what actually happens when you run a Meta-Harness search, using a real example: optimizing a support ticket classifier.

### Step 1: You Define Your Task

```python
# Your data — labeled support tickets
tickets = [
    {"text": "I was charged twice this month", "label": "billing"},
    {"text": "API returns 500 errors on POST", "label": "technical"},
    {"text": "How do I add team members?", "label": "account"},
    ...
]
```

### Step 2: You Provide Seed Harnesses

These are your starting points — different approaches to the same task. Meta-Harness needs at least one, but more gives a better starting signal.

**Seed 1 — Zero-shot** (simplest possible):
```python
def run(problem):
    return {
        "prompt": f"Classify this ticket: {problem['text']}\nCategory:",
        "context_tokens": 20,
    }
```

**Seed 2 — Few-shot** (include recent examples):
```python
def run(problem):
    examples = problem["labeled_examples"][-4:]
    example_block = "\n".join(f"Ticket: {e['text']}\nCategory: {e['label']}" for e in examples)
    return {
        "prompt": f"{example_block}\n\nTicket: {problem['text']}\nCategory:",
        "context_tokens": len(example_block.split()),
    }
```

**Seed 3 — Retrieval** (find similar tickets):
```python
def run(problem):
    # Score by word overlap, pick top 5 similar tickets
    query_words = set(problem["text"].lower().split())
    scored = [(len(query_words & set(e["text"].lower().split())), e) for e in problem["labeled_examples"]]
    scored.sort(reverse=True)
    top = [e for _, e in scored[:5]]
    ...
```

### Step 3: KAOS Runs the Search Loop

```bash
kaos mh search -b support_tickets -n 10 -k 2
```

Here's what happens inside:

#### Iteration 0 — Evaluate Seeds

KAOS spawns 3 agents (one per seed), each in its own isolated VFS:

```
Agent: harness-01HXY1A...    (zero-shot seed)
  /harness.py                  ← the harness source code
  /evaluation/scores.json      ← {"accuracy": 0.45, "context_cost": 20}
  /evaluation/per_problem.jsonl ← per-ticket results

Agent: harness-01HXY1B...    (few-shot seed)
  /harness.py
  /evaluation/scores.json      ← {"accuracy": 0.63, "context_cost": 85}
  /evaluation/per_problem.jsonl

Agent: harness-01HXY1C...    (retrieval seed)
  /harness.py
  /evaluation/scores.json      ← {"accuracy": 0.70, "context_cost": 120}
  /evaluation/per_problem.jsonl
```

All results are stored in the **search archive** — a dedicated KAOS agent's VFS:

```
Search Agent VFS:
  /config.json
  /seeds/seed_0.py, seed_1.py, seed_2.py
  /harnesses/
    01HXY1A.../source.py, scores.json, trace.jsonl, metadata.json
    01HXY1B.../source.py, scores.json, trace.jsonl, metadata.json
    01HXY1C.../source.py, scores.json, trace.jsonl, metadata.json
  /pareto/frontier.json     ← retrieval seed is best so far
```

The **trace.jsonl** files contain the full execution trace for every problem — what the harness produced, what score it got, how long it took. This is the critical ingredient: the paper's ablation shows that giving the proposer access to raw traces (vs. just scores or summaries) improves accuracy by 15+ points.

#### Iteration 1 — Proposer Studies the Archive

KAOS spawns a **proposer agent** — an LLM that can read the entire search archive through tools:

- `mh_ls_archive("/harnesses")` → lists all 3 harness directories
- `mh_read_archive("/pareto/frontier.json")` → sees retrieval is winning
- `mh_read_archive("/harnesses/01HXY1C.../trace.jsonl")` → reads every problem attempt
- `mh_read_archive("/harnesses/01HXY1A.../trace.jsonl")` → reads zero-shot failures

The proposer notices: *"The retrieval harness gets 70% accuracy but fails on tickets where the wording is unusual — 'mysterious charge on my statement' doesn't match 'charged twice' by word overlap. The few-shot harness fails when recent examples don't include the right category."*

It proposes 2 new harnesses:

**Candidate 1** — Semantic grouping: cluster examples by label, include one from each.
**Candidate 2** — Two-stage: make a draft classification, then retrieve examples for the draft label to verify.

Both are submitted via `mh_submit_harness(source_code, rationale)`, validated (AST check for `run()` function), and evaluated.

```
Search Archive after iteration 1:
  /harnesses/
    01HXY1A.../  ← zero-shot seed    (acc=0.45)
    01HXY1B.../  ← few-shot seed     (acc=0.63)
    01HXY1C.../  ← retrieval seed    (acc=0.70)
    01HXY1D.../  ← semantic grouping (acc=0.73)  ← new
    01HXY1E.../  ← two-stage verify  (acc=0.80)  ← new, best!
  /pareto/frontier.json  ← updated with new best
```

#### Iteration 2 — Learning From Success AND Failure

The proposer reads the traces for the two-stage verifier (the new best) and notices it fails on **ambiguous tickets** — "I want to downgrade my plan" could be account or billing. It also reads the semantic grouping traces and sees that including a contrastive example (two similar tickets with different labels) helps.

It proposes:

**Candidate 3** — Two-stage + contrastive examples: verify with similar tickets from DIFFERENT categories.
**Candidate 4** — Adds a label primer: lists all categories with one-line descriptions before classifying.

```
After iteration 2:
  Candidate 3: acc=0.83, cost=150  ← new best accuracy
  Candidate 4: acc=0.77, cost=45   ← lower accuracy but 3x cheaper!
  Pareto frontier: [Candidate 3 (best acc), Candidate 4 (best cost)]
```

#### Iterations 3-10 — Refinement

Each iteration, the proposer has access to ALL prior harnesses and traces. It can:
- Read the source code of the top-3 harnesses to understand what works
- Read traces of failures to understand what doesn't
- Combine ideas from different successful harnesses
- Make targeted fixes for specific failure modes (not rewrites)

The paper found that after ~6 iterations of consecutive regressions, the proposer learned to make **purely additive changes** (add new capability without modifying existing code) — which is less risky.

### Step 4: You Get the Results

```
Meta-Harness Search Complete
  Search agent: 01HXY1234AB...
  Iterations: 10
  Harnesses evaluated: 23
  Duration: 847.3s
  Frontier size: 4
  Best accuracy: 0.8700 (harness 01HXY1F...)
  Best context_cost: 35.0000 (harness 01HXY1G...)
```

Inspect the winning harness:

```bash
kaos mh inspect 01HXY... 01HXY1F... --db support-tickets.db
```

Query anything about the search:

```sql
-- Which harnesses improved over their parents?
SELECT h.metadata->>'$.rationale' as strategy,
       h.scores->>'$.accuracy' as accuracy
FROM ... ORDER BY accuracy DESC;

-- How much did the search cost in tokens?
SELECT SUM(token_count) FROM tool_calls;

-- What did the proposer focus on in iteration 5?
-- (read the proposer conversation)
```

---

## How KAOS Makes This Better Than Vanilla Meta-Harness

The paper's reference implementation uses a flat filesystem. KAOS provides:

**Isolation**: Each harness runs in its own VFS. A buggy harness can't corrupt the archive or other harnesses.

**Checkpoints**: The search is checkpointed before each iteration. If the proposer or an evaluation crashes, restore and resume.

**Audit trail**: Every file read, write, tool call, and state change is logged. You can reconstruct exactly what the proposer looked at and why.

**SQL queries**: Instead of grepping through files, query the entire search with SQL. "Which harnesses used retrieval?" "How many tokens per iteration?" "What was the accuracy trajectory?"

**Portability**: The entire search — every harness, every trace, every proposer conversation — is one `.db` file. Send it to a teammate.

---

## Running the Benchmarks

### Text Classification

```bash
# With synthetic data (testing)
kaos mh search -b text_classify -n 20 -k 3

# With your own dataset (CSV with text,label columns)
kaos mh search -b text_classify -n 20 -k 3 \
  --dataset /path/to/tickets.csv
```

### Math Reasoning

```bash
kaos mh search -b math_rag -n 20 -k 3 \
  --dataset /path/to/problems.jsonl \
  --corpus /path/to/corpus.jsonl
```

### Agentic Coding

```bash
kaos mh search -b agentic_coding -n 10 -k 2 \
  --dataset /path/to/tasks.jsonl
```

---

## Resume Interrupted Searches

If a Meta-Harness search is interrupted (crash, timeout, manual stop), you can resume it from the last completed iteration. All prior harness evaluations, traces, and Pareto frontier state are preserved in the `.db` file.

### CLI

```bash
# Resume from last completed iteration
kaos mh resume <search-agent-id>

# Check where it left off
kaos mh status <search-agent-id>
```

### Python API

```python
from kaos import Kaos
from kaos.metaharness.search import MetaHarnessSearch
from kaos.router import GEPARouter

db = Kaos("search.db")
router = GEPARouter.from_config("kaos.yaml")

search = MetaHarnessSearch(db, router)
result = await search.resume(agent_id="01HXY...")

print(result.summary())
```

### MCP Tool

The `mh_resume` tool is available via the MCP server (18 tools total):

```json
{
  "search_agent_id": "01HXY..."
}
```

Resume reconstructs the search state from the archive stored in the search agent's VFS, determines the last completed iteration, and continues from there with the same configuration (benchmark, candidates per iteration, objectives).

---

## Paper Benchmarks

KAOS includes loaders for three published research benchmarks used in the Meta-Harness paper. These download datasets from HuggingFace and cache them locally for offline use.

| Benchmark | Loader | Task | Source |
|---|---|---|---|
| `lawbench` | `load_lawbench()` | Legal text classification | HuggingFace |
| `symptom2disease` | `load_symptom2disease()` | Medical symptom-to-disease mapping | HuggingFace |
| `uspto_50k` | `load_uspto50k()` | Chemical reaction classification | HuggingFace |

### CLI

```bash
# Run a search with a paper benchmark
kaos mh search -b lawbench -n 20 -k 3
kaos mh search -b symptom2disease -n 20 -k 3
kaos mh search -b uspto_50k -n 20 -k 3
```

### Python API

```python
from kaos.metaharness.benchmarks.paper_datasets import (
    load_lawbench,
    load_symptom2disease,
    load_uspto50k,
)

# Each returns a benchmark object ready for MetaHarnessSearch
bench = load_lawbench()
# or
bench = load_symptom2disease()
# or
bench = load_uspto50k()

search = MetaHarnessSearch(db, router, bench, SearchConfig(
    benchmark="lawbench",
    max_iterations=20,
    candidates_per_iteration=3,
))
result = await search.run()
```

Datasets are downloaded on first use and cached in `~/.cache/kaos/datasets/`. Subsequent runs use the local cache.

---

## CLI Reference

```bash
# Start a search
kaos mh search -b BENCHMARK -n ITERATIONS -k CANDIDATES
    --proposer-model MODEL    # Force model for proposer
    --eval-model MODEL        # Force model for evaluation
    --max-parallel N          # Parallel evaluations
    --eval-subset N           # Subsample problems for speed

# Resume an interrupted search from last completed iteration
kaos mh resume SEARCH_AGENT_ID

# Monitor a running search
kaos mh status SEARCH_AGENT_ID

# View the Pareto frontier
kaos mh frontier SEARCH_AGENT_ID

# Inspect a specific harness
kaos mh inspect SEARCH_AGENT_ID HARNESS_ID
```

---

## Python API

```python
from kaos import Kaos
from kaos.metaharness import SearchConfig
from kaos.metaharness.search import MetaHarnessSearch
from kaos.metaharness.benchmarks import get_benchmark
from kaos.router import GEPARouter

db = Kaos("search.db")
router = GEPARouter.from_config("kaos.yaml")

config = SearchConfig(
    benchmark="text_classify",
    max_iterations=20,
    candidates_per_iteration=3,
    objectives=["+accuracy", "-context_cost"],
)

bench = get_benchmark("text_classify", dataset_path="my_data.csv")
search = MetaHarnessSearch(db, router, bench, config)
result = await search.run()

print(result.summary())
for point in result.frontier.points:
    print(f"  {point.harness_id}: {point.scores}")
```

---

## References

- **Paper:** [Meta-Harness: Optimal LLM Harness Design through Evolutionary Search](https://yoonholee.com/meta-harness/) (arXiv:2603.28052)
- **Original code:** [stanford-iris-lab/meta-harness-tbench2-artifact](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact)
- **Authors:** Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee, Omar Khattab, Chelsea Finn (Stanford / KRAFTON / MIT)

### Examples

**Technical:**
- [Support ticket classifier](../examples/meta_harness_support_tickets.py) — Full walkthrough with custom dataset and benchmark
- [Math retrieval optimization](../examples/meta_harness_math.py) — Find the best retrieval strategy for math problem solving
- [Agentic coding optimization](../examples/meta_harness_coding.py) — Optimize a coding agent harness

**Business:**
- [Customer Lifetime Value (CLV/LTV)](../examples/meta_harness_clv_prediction.py) — Optimize CLV predictions with segment-aware prompting and churn-first reasoning
- [CRM Campaign Messages](../examples/meta_harness_crm_campaigns.py) — Find the best tone, CTA, and personalization strategy per customer segment
- [Fraud Detection](../examples/meta_harness_fraud_detection.py) — Improve fraud recall and precision with red-flag checklists and contrastive examples
